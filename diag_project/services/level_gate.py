"""레벨 서술 매칭 게이트 (T-A 확장).

기존 D트랙 근거 검증 게이트(인용문 ↔ Lv.4 서술 매칭)를 '모든 레벨 판정'으로
확장한다. 판정기가 서술의 유창함이 아니라 competencies.py 의 레벨 서술과
대조해 레벨을 확정하도록 강제한다.

  현재: evidence → (주제 매칭) → sub_key → (유창함) → level
  수정: evidence → (주제 매칭) → sub_key → (levels[N] 서술 대조) → level
        매칭 실패 시 한 단계 낮추고 재검증. 최하위에서도 실패하면 measured=False.

효율을 위해 대역량 단위로 배치 검증(측정된 하위역량들을 한 번의 LLM 호출로
판정)한다. LLM 이 없으면(단위 테스트 등) 게이트를 건너뛰고 claimed_level 을
그대로 둔다(보수적: 판사 없이 강등하지 않음).
"""
import re
import asyncio
import json
import logging
import os
from typing import Any, Dict

from diag_project.data.competencies import COMPETENCY_FRAMEWORK

logger = logging.getLogger(__name__)

# 게이트 호출 동시성 상한. 과거엔 Semaphore(1) 로 전역 직렬화했다(심층분석 5건
# 병렬 중 게이트까지 겹쳐 빈 응답이 나던 시기 — 이후 max_tokens 8192 로 원인
# 해소). 2026-09-29 item6: outer 3회 병렬화로 게이트가 최대 15건이 되자 직렬
# 게이트(건당 25~40초)가 리포트 시간의 대부분을 차지해, 상한을 env 로 연다.
# 전체 분석 호출은 llm_service 의 ANALYSIS_CONCURRENCY 세마포어가 따로 묶는다.
def _gate_concurrency() -> int:
    try:
        return max(1, int(os.getenv("GATE_CONCURRENCY", "15")))
    except (TypeError, ValueError):
        return 15


_GATE_SEM_STATE: Dict[str, Any] = {"loop": None, "sem": None}


def _gate_semaphore() -> asyncio.Semaphore:
    """이벤트 루프마다 1개(모듈 import 시 생성하면 테스트 루프 교체에 깨진다)."""
    loop = asyncio.get_running_loop()
    if _GATE_SEM_STATE["loop"] is not loop:
        _GATE_SEM_STATE["loop"] = loop
        _GATE_SEM_STATE["sem"] = asyncio.Semaphore(_gate_concurrency())
    return _GATE_SEM_STATE["sem"]


def level_reference(competency_key: str, sub_name: str) -> Dict[int, str]:
    """해당 하위역량의 레벨(1~4) 서술 + 행동 예시를 합쳐 반환.

    게이트가 evidence 를 대조할 '기준 서술'. 없으면 빈 dict.
    """
    comp = COMPETENCY_FRAMEWORK.get(competency_key) or {}
    for ind in (comp.get("indicators") or {}).values():
        if ind.get("name") == sub_name:
            levels = ind.get("levels") or {}
            examples = ind.get("examples") or {}
            out: Dict[int, str] = {}
            for lv in (1, 2, 3, 4):
                desc = str(levels.get(lv, "")).strip()
                ex = str(examples.get(lv, "")).strip()
                out[lv] = (desc + ("\n" + ex if ex else "")).strip()
            return out
    return {}


def _build_gate_prompt(items: list) -> str:
    """배치 게이트 프롬프트 전문(정적 지시 + 본문) — 테스트·로그용. 실제 호출은 _build_gate_body + GATE_SYSTEM(system, cache)."""
    return GATE_SYSTEM + "\n\n" + _build_gate_body(items)


async def _call_gate_llm(llm, prompt: str, episodes_text: str = ""):
    """(2026-10-29 P2-4) llm(prompt, system) 을 지원하면 정적 지시를 system 으로 넘기고, 1인자 콜러블(테스트·구형)은 전문을 넘긴다.
    (2026-11-06 P6) 사례 전문 블록은 세 번째 인자(별도 캐시 블록) — 2인자 콜러블이면 본문 앞에 이어 붙인다."""
    import inspect
    try:
        n_params = len(inspect.signature(llm).parameters)
    except (TypeError, ValueError):
        n_params = 1
    if n_params >= 3:
        return await llm(prompt, GATE_SYSTEM, episodes_text or None)
    body = (episodes_text + "\n\n" + prompt) if episodes_text else prompt
    if n_params >= 2:
        return await llm(body, GATE_SYSTEM)
    return await llm(GATE_SYSTEM + "\n\n" + body)


def _episodes_block_for(items: list) -> str:
    """(P6) 배치의 사례 전문 블록(사례 하나는 한 번만, [사례 A]…). 항목에 사례가 없으면 빈 문자열."""
    from diag_project.services.episode_context import assign_letters, episodes_block
    letters = assign_letters(items)
    for it in items:
        it["_letters"] = [letters[e["id"]] for e in (it.get("episodes") or [])]
    return episodes_block(items, letters)


def _build_gate_body(items: list) -> str:
    """배치 게이트 본문. items: [{sub_name, evidence, claimed_level, ref, episodes?}].
    (P6) 항목에 사례가 있으면 '[사례 참조] 사례 A 의 일부 — 레벨은 사례 A 전체의 행동으로' 한 줄을 붙인다(사례 전문은 _episodes_block_for)."""
    blocks = []
    for i, it in enumerate(items, 1):
        ref = it["ref"]
        ref_txt = "\n".join(f"  · Lv.{lv}: {ref.get(lv, '')}" for lv in (1, 2, 3, 4))
        ev_txt = "\n".join(f"  - {e}" for e in it["evidence"])
        letters = it.get("_letters") or []
        ep_line = (f"\n[사례 참조] 위 인용은 사례 {', '.join(letters)} 의 일부다 — 어디를 보라는 표시일 뿐이며, 레벨은 그 사례 전체에서 리더가 실제로 한 행동으로 판정한다."
                   if letters else "")
        blocks.append(
            f"[{i}] 하위역량: {it['sub_name']} (판정기 주장 레벨: Lv.{it['claimed_level']})\n"
            f"[레벨 기준 서술]\n{ref_txt}\n[리더 발화(근거)]\n{ev_txt}{ep_line}"
        )
    body = "\n\n".join(blocks)
    return (
        f"{body}\n\n"
        '출력(JSON, 마크다운 금지): {"results": [{"idx": <번호>, '
        '"supported_level": <0~4>, "category": "구체행동|태도|일반화|부재", '
        '"reason": "판정 근거 한 줄"}]}'
    )


# (2026-10-29 P2-4) 게이트 정적 지시 — system 으로 보내 42콜에 걸쳐 prompt cache 를 공유한다(본문만 호출마다 다름).
GATE_SYSTEM = (
        "당신은 BEI(행동사건면접) 채점 감사관이다. 아래 각 하위역량에 대해, "
        "제시된 '리더 발화'가 어느 레벨의 '기준 서술'에 실제로 부합하는지 "
        "냉정하게 판정하라.\n\n"
        "🚨 판정 원칙 (엄격 적용):\n"
        "1. BEI 근거는 '구체 행동 사례'여야 한다 = 시점 + 상황 + 리더가 실제로 "
        "한 행동. 아래는 근거가 아니므로 supported_level=0:\n"
        "   · 태도·신념 진술('~가 중요하다고 생각합니다')\n"
        "   · 일반화 서술('보통 제가 직접 처리하는 편입니다')\n"
        "   · 부재 진술('그런 경험은 없습니다') — 오히려 낮은 수준의 신호\n"
        "2. 구체 행동 사례라면, 그 행동이 '실제로 도달한 가장 높은 레벨'을 고른다. "
        "서술이 유창하다고 레벨을 올리지 말 것. 기준 서술과의 '행동 수준' 일치만 본다.\n"
        "3. 레벨 n 은 'Lv.n 서술의 핵심 행동'이 근거 문장에 실제로 있을 때만 준다. Lv.n 요건이 일부라도 "
        "결락이면 Lv.n-1 이다. '~는 없지만/부족하지만 Lv.n 이 더 맞다' 식으로 상위 레벨을 주지 말 것 — "
        "사유에 결락을 적었으면 레벨은 n-1 이어야 한다.\n"
        "4. 단 n-1 이 Lv.1 이면: Lv.1 서술(역할 인식 부재·단기 수습 같은 부정형)이 발화에 실제로 맞을 때만 1, "
        "아니면 2 다.\n"
        "5. 주장 레벨보다 높게 올리지 말 것(게이트는 강등 또는 유지만 한다). 구체 행동 사례가 아니면(태도·일반화·부재) 0.\n"
        "6. (설계 = Lv.3) 리더가 기준·틀·지표·절차를 직접 제안해 팀이 채택했다는 행동이 근거 문장에 있으면 Lv.3 을 유지한다 — "
        "기존 기준을 따라 점검·공유만 한 것은 Lv.2, 제안한 틀이 팀의 합의·운영 방식이 된 것은 Lv.3. 목표치·점검 주기 같은 세부가 "
        "비어 있다는 이유로 Lv.3 → Lv.2 로 강등하지 말 것(그 결락은 Lv.4 를 주지 않는 이유다).\n"
        "7. (사례 단위 판정) '[사례 전문]' 블록이 주어지면 인용은 어디를 보라는 표시일 뿐이다 — 레벨은 그 사례 전체에서 리더가 실제로 한 "
        "행동으로 판정한다. 같은 사례를 여러 하위역량이 가리키면 각 하위역량의 기준 서술에 해당하는 행동이 그 사례에 '실제로' 있는지 "
        "따로 본다(한 사례가 모든 칸을 자동으로 올리지 않는다). 사례에 없는 행동은 상상하지 않는다. 사례 블록이 없는 항목은 인용만으로 판정한다.\n"
        "8. (사례 묶기) 한 항목이 사례를 여럿 가리키면, 같은 대역량 챕터의 사례끼리만 합쳐 요건을 볼 수 있다. 다른 챕터에서 온 사례는 "
        "단독 근거로만 쓰고, 다른 사례와 합쳐 요건을 채우지 않는다.\n"
        "9. (Lv.4 범위) Lv.4 는 행동의 범위가 팀 밖(타 부서·다른 팀·전사·조직 단위·외부 기관)일 때만 준다. 팀 안의 구성원·직군끼리 만든 "
        "장치(합동 리뷰·규칙·도구·교육)는 아무리 정착했어도 Lv.3 이 상한이다. 사유에 팀 밖 대상이 없으면 Lv.4 를 쓰지 않는다."
)


# (evidence, sub_key, claimed_level) → 게이트 판정 캐시 (중복 호출 제거).
#   §3: 프로세스 내 in-mem(_GATE_CACHE) + 파일 영속(analysis_cache)의 2단.
#   프롬프트를 바꾸면 GATE_PROMPT_VERSION 을 올려 캐시를 무효화한다.
_GATE_CACHE: Dict[tuple, Dict[str, Any]] = {}
# 진행 중인 게이트 판정(키 → Future[verdict|None]). outer run 이 순차일 땐 뒤 run
# 이 앞 run 의 판정을 캐시로 재사용했다. 병렬이면 같은 (근거, 레벨) 후보가 동시에
# 게이트로 들어올 수 있어, 먼저 나간 판정을 기다려 공유한다(중복 호출·판정 갈림
# 방지). 실패(None)면 기다린 쪽이 직접 다시 판정한다 — 순차에서 pending 이
# 캐시되지 않아 다음 run 이 재시도하던 것과 같다.
_INFLIGHT: Dict[tuple, "asyncio.Future"] = {}
GATE_MAX_RETRIES = 3  # 지수 백오프 재시도 횟수
GATE_VOTES_DEFAULT = 3  # (2026-10-23 D) 같은 근거 5회 측정: 업무계획 [2,3,X,X,2] 처럼 2개 레벨에 걸쳐 3표 중앙값으로 고정
# (2026-11-02 P3 비용) 적응 투표 — 먼저 2표를 받고, 두 표가 일치한 칸은 그대로, 갈린 칸만 남은 표를 그 칸에 한정해 받는다.
#   an_cache5 실측: 54칸 중 53칸이 1·2표 일치 → 게이트 콜 ~1/3 절감. GATE_VOTES_ADAPTIVE=0 이면 전부 n표.
GATE_VOTES_ADAPTIVE = os.getenv("GATE_VOTES_ADAPTIVE", "1") != "0"


def vote_agrees(a: Dict[str, Any] | None, b: Dict[str, Any] | None) -> bool:
    """두 표가 같은 판정인가(탈락 여부·검증 레벨). pending 이 있으면 불일치로 본다."""
    if not a or not b or a.get("pending") or b.get("pending"):
        return False
    return bool(a.get("dropped")) == bool(b.get("dropped")) and a.get("verified_level") == b.get("verified_level")
GATE_PROMPT_VERSION = "2026-11-06.v4-scope"       # (P6 승인 반영) 규칙 8(같은 챕터 사례만 묶기)·9(Lv.4 는 팀 밖 범위) — 게이트 캐시 무효화
# (2026-10-23 E) claude 경로의 게이트 캐시만 새 판정 규칙 버전으로 가른다 — gemini 키(420f1341 캐시)는 그대로 둔다(사용자 결정).
GATE_PROMPT_VERSION_CLAUDE = "2026-10-23.v3"   # E-2: 결락 → n-1, Lv.1 은 부정형 서술이 맞을 때만


def _cache_key(competency_key: str, sub: str, evidence, claimed: int,
               provider: str | None = None, ep_hash: str = "") -> tuple:
    # (2026-10-15) provider 성분: gemini 는 빈 튜플(기존 키 보존), claude 는 별도 키.
    from diag_project import llm_provider as _lp
    return (competency_key, sub, "|".join(evidence or []), int(claimed or 1),
            *_lp.cache_key_parts(provider), *_claude_version_parts(provider), ep_hash or "")


def _claude_version_parts(provider: str | None) -> tuple:
    from diag_project import llm_provider as _lp
    return (GATE_PROMPT_VERSION_CLAUDE,) if _lp.resolve_session(provider) == _lp.CLAUDE else ()


def _persist_key(competency_key: str, sub: str, evidence, claimed: int,
                 provider: str | None = None, ep_hash: str = "") -> str:
    from diag_project.services import analysis_cache as _ac
    from diag_project import llm_provider as _lp
    # T-1: temperature·thinkingBudget 을 키에 포함(파라미터 다르면 캐시 갈림).
    #   현재 게이트는 temp=0·thinking=dynamic.
    # (2026-10-15) provider 성분(gemini 빈 튜플 → 기존 gemini 캐시 그대로, claude 는 별도 캐시).
    return _ac.make_key(GATE_PROMPT_VERSION, competency_key, sub,
                        "|".join(evidence or []), int(claimed or 1),
                        os.getenv("ANALYSIS_TEMPERATURE", "temp0"),
                        f"tb{os.getenv('GATE_TB', 'dyn')}",
                        *_lp.cache_key_parts(provider), *_claude_version_parts(provider), ep_hash or "")


# (2026-10-23 E-2) 사유 검증 — "~는 없지만/부족하나 … Lv.n" 처럼 결락 요건을 적고도 n 을 줬으면 n-1 로 내린다.
#   같은 문장 안에서 더 높은 레벨(Lv.n+1 이상)의 결락을 말한 것은 정상(그 레벨을 안 준 이유)이라 건드리지 않는다.
#   n-1 이 Lv.1 이면 Lv.1 서술 일치를 알 수 없으므로 2 에 둔다(규칙 4).
_CONCESSION_RE = re.compile(
    r"(없지만|없으나|없어도|없더라도|없는데도|않지만|않으나|않았지만|않더라도|못하지만|못했지만|부족하지만|부족하나|부족해도|"
    r"약하지만|약하나|약해도|미흡하지만|미흡하나|불충분하지만|불충분하나|"
    r"(부합하나|해당하나|맞으나|부합하지만|해당하지만|맞지만)[^.]{0,80}(없음|없다|없어|않음|않았|부족|미흡)|"
    r"다만[^.]{0,40}(없|않|부족|미흡|약하|불충분))"
)
# 문장 경계를 넘는 꼴: "… 근거는 없음. 그래도 Lv.3 …"
_CONCESSION_CROSS_RE = re.compile(r"(없음|없다|없었다|않음|않는다|부족하다|부족함)\.\s*(그래도|그러나|하지만|그렇지만|다만)[^.]{0,80}Lv\.?\s?(\d)")
_LV_RE = re.compile(r"Lv\.?\s?(\d)")


# (2026-11-06 P6 승인 반영) Lv.4 범위 검증 — 사유에 '팀 밖' 대상이 없으면 Lv.4 → Lv.3. p6b 팀워크(강사·운영·기획 합동 리뷰 = 팀 안 장치)가 4 로 갔다.
_OUTSIDE_TEAM_RE = re.compile(r"(타\s*부서|다른\s*부서|부서\s*간|타\s*팀|다른\s*팀|여러\s*팀|팀\s*밖|전사|회사\s*(전체|차원)|조직\s*(전체|단위|차원)|본부|사업부|"
                              r"외부\s*(기관|업체|파트너|강사진|조직)|협력사|고객사|계열사|경영진|임원진|유관\s*부서|현업\s*부서|사내\s*전체)")


def scope_fix(verified: int | None, reason: str) -> tuple:
    """(verified_level, fixed:bool, note). Lv.4 인데 사유에 팀 밖 범위 표지가 없으면 Lv.3."""
    if verified != 4:
        return verified, False, ""
    if _OUTSIDE_TEAM_RE.search(reason or ""):
        return verified, False, ""
    return 3, True, "Lv.4 범위 미충족(팀 안 장치) → Lv.3"


def concession_fix(verified: int | None, reason: str) -> tuple:
    """(verified_level, fixed:bool, note). 결락 서술 + 같은 레벨 수여 → n-1(최소 2)."""
    if not verified or verified < 2 or not reason:
        return verified, False, ""
    mx = _CONCESSION_CROSS_RE.search(reason)
    if mx and int(mx.group(3)) == verified:
        new = max(2, verified - 1)
        if new != verified:
            return new, True, f"결락 서술 후 Lv.{verified} 수여 → Lv.{new} (E-2): {mx.group(0)[:80]}"
    for sent in re.split(r"(?<=[.!?。])\s+", reason):
        m = _CONCESSION_RE.search(sent)
        if not m:
            continue
        higher = [int(x) for x in _LV_RE.findall(sent) if int(x) > verified]
        if higher:
            continue                      # 상위 레벨 결락 언급 — 정상
        new = max(2, verified - 1)
        if new == verified:
            return verified, False, ""
        return new, True, f"결락 서술 후 Lv.{verified} 수여 → Lv.{new} (E-2): {sent.strip()[:80]}"
    return verified, False, ""


# (2026-10-23 E-3) 일반화 결정론 전처리 — 시점 표지 없음 + 습관 표지 있는 근거 문장은 게이트 전에 '일반화'로 고정(4번 탐침과 같은 사전).
def split_generalized(evidence: list) -> tuple:
    """(남는 근거, 일반화로 걸러진 근거)."""
    from diag_project.services.avoidance_detector import is_generalized_evidence   # (2026-11-02 핫픽스) 대화용 넓은 규칙 금지
    keep, gen = [], []
    for e in evidence or []:
        (gen if is_generalized_evidence(e) else keep).append(e)
    return keep, gen


def deterministic_generalization_verdict(gen: list) -> Dict[str, Any]:
    return {"verified_level": None, "category": "일반화",
            "reason": f"결정론: 시점 표지 없음·습관 표지(~일수록·~때는·~하는 편·늘·항상·보통) — 근거 {len(gen)}문장 전부 일반화",
            "downgraded": False, "dropped": True, "pending": False, "deterministic": True}


def _pending(reason: str) -> Dict[str, Any]:
    """게이트가 판정을 '내리지 못한' 상태 — fail-closed 표식.

    measured 를 유지하지 않는다. 점수 산출 보류(gate_status=pending) 후
    리포트에 '검증 미완료'로 표기해 조용한 fail-open 을 막는다.
    """
    return {"verified_level": None, "category": "검증불가",
            "reason": reason, "downgraded": False, "dropped": False,
            "pending": True}


async def gate_verify_levels(
    competency_key: str,
    measured: Dict[str, Dict[str, Any]],
    llm,
    provider: str | None = None,
) -> Dict[str, Dict[str, Any]]:
    """측정 후보 하위역량들의 레벨을 배치 검증 (fail-closed).

    measured: {sub_name: {"evidence": [str...], "claimed_level": int}}
    반환: {sub_name: {"verified_level": int|None, "category", "reason",
                      "downgraded", "dropped", "pending"}}
      · pending=True  → 게이트가 판정 불가(응답 실패/미가동). measured 유지 금지,
                        점수 보류(gate_status=pending). 🚨 fail-open 하지 않는다.
      · dropped=True  → 게이트 실행됨, 근거 자격 미달 → measured=False(근거미확보).
      · verified_level<claimed → 강등. =claimed → 유지(통과).
    """
    out: Dict[str, Dict[str, Any]] = {}
    items = []
    shared = []  # 다른 코루틴이 이미 판정 중인 후보 → 그 결과를 기다린다
    from diag_project.services.episode_context import episode_hash as _eph
    for sub, info in measured.items():
        ref = level_reference(competency_key, sub)
        claimed = info.get("claimed_level") or 1
        _eps = list(info.get("episodes") or [])          # (P6) 이 근거가 속한 사례들 — 호출자가 붙인다
        _h = _eph(_eps)
        ck = _cache_key(competency_key, sub, info.get("evidence"), claimed, provider, _h)
        if ck in _GATE_CACHE:                       # in-mem 적중
            out[sub] = dict(_GATE_CACHE[ck])
            continue
        from diag_project.services import analysis_cache as _ac
        _pk = _persist_key(competency_key, sub, info.get("evidence"), claimed, provider, _h)
        _persisted = _ac.get("level_gate", _pk)
        if _persisted is not None:                  # 파일 캐시 적중
            _GATE_CACHE[ck] = dict(_persisted)
            out[sub] = dict(_persisted)
            continue
        if not ref or not info.get("evidence"):
            # 기준 서술이 없으면 판정 불가 → fail-closed(pending)
            out[sub] = _pending("레벨 기준 서술 없음")
            continue
        it = {"sub_name": sub, "evidence": info["evidence"],
              "claimed_level": claimed, "ref": ref, "ck": ck, "episodes": _eps, "ep_hash": _h}
        if llm is not None and ck in _INFLIGHT:
            shared.append((it, _INFLIGHT[ck]))
            continue
        items.append(it)

    if not items and not shared:
        return out
    if llm is None:
        # 🚨 fail-closed: 게이트 미가동 시 통과시키지 않고 pending 처리.
        for it in items:
            out[it["sub_name"]] = _pending("LLM 게이트 미가동")
        return out

    # 자기 배치를 먼저 '진행 중'으로 등록(await 전, 동기) → 동시에 들어온 다른
    #   run 은 같은 후보를 다시 부르지 않고 이 판정을 기다린다.
    _register(items)

    async def _await_shared(it, fut):
        return it, await asyncio.shield(fut)

    # 자기 배치와 공유 대기를 함께 진행(자기 배치는 누구도 기다리지 않으므로
    #   run 끼리 서로를 기다리는 교착이 없다).
    jobs = [_judge_batch_voted(competency_key, items, llm, out, provider)] if items else []
    res = await asyncio.gather(*jobs, *[_await_shared(it, f) for it, f in shared])
    retry = []
    for it, verdict in res[len(jobs):]:
        if verdict is not None:
            out[it["sub_name"]] = dict(verdict)
        else:
            retry.append(it)                        # 공유 판정 실패 → 직접 재판정
    if retry:
        _register(retry)
        await _judge_batch_voted(competency_key, retry, llm, out, provider)
    return out


def _register(items: list) -> None:
    loop = asyncio.get_running_loop()
    for it in items:
        fut = loop.create_future()
        it["_fut"] = fut
        _INFLIGHT.setdefault(it["ck"], fut)


def _release(it: dict, verdict) -> None:
    fut = it.pop("_fut", None)
    if fut is None:
        return
    if _INFLIGHT.get(it["ck"]) is fut:
        _INFLIGHT.pop(it["ck"], None)
    if not fut.done():
        fut.set_result(verdict)


def gate_votes() -> int:
    """(2026-10-23 D) 같은 근거를 몇 번 판정해 중앙값을 쓸지. 기본 GATE_VOTES_DEFAULT; 환경변수 GATE_VOTES 로 덮어쓴다."""
    try:
        return max(1, int(os.getenv("GATE_VOTES", str(GATE_VOTES_DEFAULT))))
    except ValueError:
        return GATE_VOTES_DEFAULT


def merge_votes(votes: list, claimed: int) -> Dict[str, Any]:
    """투표 병합(순수 함수): 과반이 탈락이면 탈락, 아니면 통과표의 verified_level 중앙값(짝수면 낮은 쪽).
    category 는 최빈값, reason 은 채택 레벨을 낸 표의 사유. votes 필드에 표별 레벨(탈락 0)을 남긴다."""
    from collections import Counter
    valid = [v for v in votes if v and not v.get("pending")]
    if not valid:
        return _pending("게이트 투표 응답 부족")
    dropped = [v for v in valid if v.get("dropped")]
    passed = [v for v in valid if not v.get("dropped") and v.get("verified_level")]
    tally = [int(v.get("verified_level") or 0) for v in valid]
    if len(dropped) * 2 > len(valid) or not passed:
        base = dict(dropped[0] if dropped else valid[0])
        cat = Counter(v.get("category") for v in dropped or valid).most_common(1)[0][0]
        base.update({"verified_level": None, "dropped": True, "downgraded": False, "category": cat, "votes": tally})
        return base
    lv_sorted = sorted(int(v["verified_level"]) for v in passed)
    level = lv_sorted[(len(lv_sorted) - 1) // 2]
    pick = next(v for v in passed if int(v["verified_level"]) == level)
    out = dict(pick)
    out.update({"verified_level": level, "dropped": False, "downgraded": level < int(claimed or 1),
                "category": Counter(v.get("category") for v in passed).most_common(1)[0][0], "votes": tally})
    return out


async def _judge_batch_voted(competency_key: str, items: list, llm,
                             out: Dict[str, Dict[str, Any]],
                             provider: str | None = None) -> None:
    """GATE_VOTES>1 이면 같은 배치를 n 회 독립 판정해 merge_votes 로 합친다(캐시·공유는 병합 결과로)."""
    n = gate_votes()
    if n <= 1:
        return await _judge_batch(competency_key, items, llm, out, provider)
    temps: list = [dict() for _ in range(n)]
    try:
        if GATE_VOTES_ADAPTIVE and n >= 3:
            await asyncio.gather(*[_judge_batch(competency_key, items, llm, temps[i], provider, cache=False, release=False)
                                   for i in range(2)])
            undecided = [it for it in items if not vote_agrees(temps[0].get(it["sub_name"]), temps[1].get(it["sub_name"]))]
            if undecided:
                await asyncio.gather(*[_judge_batch(competency_key, undecided, llm, temps[i], provider, cache=False, release=False)
                                       for i in range(2, n)])
            logger.info("🗳️ 게이트 적응 투표 [%s] %d칸 중 %d칸 %d표째", competency_key, len(items), len(undecided), n)
        else:
            await asyncio.gather(*[_judge_batch(competency_key, items, llm, temps[i], provider, cache=False, release=False)
                                   for i in range(n)])
        from diag_project.services import analysis_cache as _ac
        for it in items:
            merged = merge_votes([t.get(it["sub_name"]) for t in temps], it["claimed_level"])
            out[it["sub_name"]] = merged
            if not merged.get("pending"):
                _GATE_CACHE[it["ck"]] = dict(merged)
                _ac.set("level_gate", _persist_key(competency_key, it["sub_name"], it["evidence"],
                                                  it["claimed_level"], provider), dict(merged))
                logger.info("🗳️ 레벨게이트 투표 [%s/%s] %s → %s", competency_key, it["sub_name"],
                            merged.get("votes"), merged.get("verified_level") or "탈락")
    finally:
        for it in items:
            v = out.get(it["sub_name"])
            _release(it, None if (not v or v.get("pending")) else dict(v))


async def _judge_batch(competency_key: str, items: list, llm,
                       out: Dict[str, Dict[str, Any]],
                       provider: str | None = None, *, cache: bool = True, release: bool = True) -> None:
    """items 를 한 번의 LLM 호출로 판정해 out 에 기록(+캐시). 실패는 pending. cache/release=False 는 투표용(병합 결과만 캐시·공유)."""
    _ep_block = _episodes_block_for(items)          # (P6) 사례 전문은 배치당 한 번, 별도 캐시 블록
    prompt = _build_gate_body(items)

    async def _call_gate():
        # 동시성 상한 + 지수 백오프 재시도(빈 응답/오류에 견딤).
        async with _gate_semaphore():
            last = None
            for attempt in range(GATE_MAX_RETRIES):
                try:
                    raw = await _call_gate_llm(llm, prompt, _ep_block)
                    if raw and raw.strip():
                        return raw
                    last = "빈 응답"
                except Exception as e:  # noqa: BLE001
                    last = str(e)
                await asyncio.sleep(2.0 * (2 ** attempt))  # 2,4,8s
            raise RuntimeError(last or "게이트 응답 없음")

    try:
        try:
            raw = await _call_gate()
            raw = (raw or "").replace("```json", "").replace("```", "").strip()
            res = json.loads(raw)
            by_idx = {int(r.get("idx")): r for r in (res.get("results") or [])}
        except Exception as e:  # noqa: BLE001
            # 🚨 fail-closed: 응답 실패 시 measured 유지 금지 → 전 항목 pending.
            logger.warning("레벨 게이트 판정 실패(%s) → pending(fail-closed)", e)
            for it in items:
                out[it["sub_name"]] = _pending(f"게이트 응답 실패: {e}")
            return

        for i, it in enumerate(items, 1):
            r = by_idx.get(i)
            claimed = it["claimed_level"]
            if not r:  # 판정 항목 누락 → pending
                out[it["sub_name"]] = _pending("게이트 판정 항목 누락")
                continue
            sup = r.get("supported_level")
            sup = int(sup) if isinstance(sup, (int, float)) else claimed
            sup = max(0, min(sup, claimed))  # 강등/유지만, 상향 금지
            verified = None if sup <= 0 else sup
            _reason_full = str(r.get("reason", ""))
            verified, _cfix, _cnote = concession_fix(verified, _reason_full)      # (E-2) 결락 서술 검증
            if _cfix:
                logger.info("🔧 레벨게이트 사유 검증 [%s/%s] %s", competency_key, it["sub_name"], _cnote)
            verified, _sfix, _snote = scope_fix(verified, _reason_full)           # (P6) Lv.4 범위 검증
            if _sfix:
                logger.info("🔧 레벨게이트 범위 검증 [%s/%s] %s", competency_key, it["sub_name"], _snote)
            verdict = {
                "verified_level": verified,
                "category": r.get("category", "구체행동"),
                "reason": _reason_full[:120],
                "downgraded": verified is not None and verified < claimed,
                "dropped": verified is None,
                "pending": False,
                **({"concession_fix": True} if _cfix else {}),
                **({"scope_fix": True} if _sfix else {}),
            }
            out[it["sub_name"]] = verdict
            if cache:
                _GATE_CACHE[it["ck"]] = dict(verdict)        # in-mem 저장
                from diag_project.services import analysis_cache as _ac
                _ac.set("level_gate", _persist_key(
                    competency_key, it["sub_name"], it["evidence"],
                    it["claimed_level"], provider, it.get("ep_hash", "")), dict(verdict))  # 파일 영속
            if verified is None:
                logger.info("🚧 레벨게이트 탈락 [%s/%s] claimed=Lv.%s → 근거미달(%s)",
                            competency_key, it["sub_name"], claimed,
                            verdict["category"])
            elif verified < claimed:
                logger.info("🔽 레벨게이트 강등 [%s/%s] Lv.%s→Lv.%s (%s)",
                            competency_key, it["sub_name"], claimed, verified,
                            verdict["reason"])
    finally:
        # 기다리는 쪽에 판정 공유(pending 은 공유하지 않음 → None → 재판정). 투표 모드에서는 병합 뒤 호출자가 공유한다.
        if release:
            for it in items:
                v = out.get(it["sub_name"])
                _release(it, None if (not v or v.get("pending")) else dict(v))


# ── (2026-10-23 A) evidence 재선택 — 게이트가 태도·일반화로 거절한 근거를 같은 답변에서 '행동 문장'으로 1회 다시 고른다 ──
RESELECT_PROMPT_VERSION = "2026-10-23.v1"
RESELECT_CATEGORIES = ("태도", "일반화")


def _norm_ws(t: str) -> str:
    return re.sub(r"\s+", "", t or "")


def leader_answer_lines(chapter_text: str, old_evidence: list[str]) -> list[str]:
    """챕터 전사('리더: …' 줄)에서 기존 근거가 들어 있던 리더 답변 줄들을 고른다. 못 찾으면 리더 줄 전부(앞 6000자)."""
    lines = [ln[len("리더:"):].strip() for ln in (chapter_text or "").split("\n") if ln.startswith("리더:")]
    hits = []
    for ln in lines:
        n = _norm_ws(ln)
        if any(_norm_ws(e)[:40] and _norm_ws(e)[:40] in n for e in old_evidence or []):
            hits.append(ln)
    if hits:
        return hits
    out, total = [], 0
    for ln in lines:
        if total + len(ln) > 6000:
            break
        out.append(ln); total += len(ln)
    return out


def filter_verbatim(candidates: list, source_lines: list[str], max_n: int = 3) -> list[str]:
    """LLM 이 고른 문장 중 원문에 실제로 있는 것만(공백 무시 부분 일치), 최대 max_n."""
    src = _norm_ws(" ".join(source_lines))
    out: list[str] = []
    for c in candidates or []:
        c = str(c or "").strip()
        if len(c) < 8:
            continue
        if _norm_ws(c) in src and c not in out:
            out.append(c)
        if len(out) >= max_n:
            break
    return out


def build_reselect_prompt(sub_name: str, answer_lines: list[str], old_evidence: list[str]) -> str:
    body = "\n".join(f"- {ln}" for ln in answer_lines)
    old = "\n".join(f"- {e}" for e in old_evidence or [])
    return (
        "당신은 BEI(행동사건면접) 근거 선별관이다. 아래 '리더 답변'에서 하위역량 "
        f"'{sub_name}' 과 관련해 리더가 **실제로 한 행동 문장**(결정·실행·대화)만 고르라.\n"
        "제외: 이유·판단·신념·가치관 문장('~라고 생각했다', '~가 중요하다', '~기 때문이다'), "
        "평소 방식 일반화('~하는 편이다', '~일수록'), 부재 진술.\n"
        "원문 그대로(verbatim) 복사하고 요약·창작하지 않는다. 최대 3문장, 없으면 빈 배열.\n\n"
        f"[리더 답변]\n{body}\n\n"
        f"[앞서 거절된 근거 — 이유·일반화 문장이었다. 이것과 다른 '행동' 문장을 고른다]\n{old}\n\n"
        '출력(JSON, 마크다운 금지): {"evidence": ["...", "..."]}'
    )


async def reselect_evidence(llm, competency_key: str, sub_name: str, old_evidence: list[str],
                            chapter_text: str, provider: str | None = None) -> list[str]:
    """같은 답변에서 행동 문장을 1회 다시 고른다(결정론 캐시). 실패·없음은 []."""
    from diag_project.services import analysis_cache as _ac
    lines = leader_answer_lines(chapter_text, old_evidence)
    if not lines or llm is None:
        return []
    key = _ac.make_key(RESELECT_PROMPT_VERSION, competency_key, sub_name, "|".join(old_evidence or []),
                       "|".join(lines)[:4000], provider or "")
    cached = _ac.get("evidence_reselect", key)
    if cached is not None:
        return list(cached)
    try:
        raw = await llm(build_reselect_prompt(sub_name, lines, old_evidence))
        raw = (raw or "").replace("```json", "").replace("```", "").strip()
        cands = (json.loads(raw) or {}).get("evidence") or []
    except Exception as e:  # noqa: BLE001
        logger.warning("근거 재선택 실패 [%s/%s]: %s", competency_key, sub_name, str(e)[:120])
        return []
    picked = filter_verbatim(cands, lines)
    _ac.set("evidence_reselect", key, picked)
    return picked
