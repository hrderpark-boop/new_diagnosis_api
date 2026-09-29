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
    """배치 게이트 프롬프트. items: [{sub_name, evidence, claimed_level, ref}]."""
    blocks = []
    for i, it in enumerate(items, 1):
        ref = it["ref"]
        ref_txt = "\n".join(f"  · Lv.{lv}: {ref.get(lv, '')}" for lv in (1, 2, 3, 4))
        ev_txt = "\n".join(f"  - {e}" for e in it["evidence"])
        blocks.append(
            f"[{i}] 하위역량: {it['sub_name']} (판정기 주장 레벨: Lv.{it['claimed_level']})\n"
            f"[레벨 기준 서술]\n{ref_txt}\n[리더 발화(근거)]\n{ev_txt}"
        )
    body = "\n\n".join(blocks)
    return (
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
        "3. 주장 레벨보다 높게 올리지 말 것(게이트는 강등 또는 유지만 한다). "
        "발화가 기준에 못 미치면 한 단계씩 낮춘다. Lv.1 기준에도 못 미치면 0.\n\n"
        f"{body}\n\n"
        '출력(JSON, 마크다운 금지): {"results": [{"idx": <번호>, '
        '"supported_level": <0~4>, "category": "구체행동|태도|일반화|부재", '
        '"reason": "판정 근거 한 줄"}]}'
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
GATE_PROMPT_VERSION = "2026-08-17.v1"


def _cache_key(competency_key: str, sub: str, evidence, claimed: int) -> tuple:
    return (competency_key, sub, "|".join(evidence or []), int(claimed or 1))


def _persist_key(competency_key: str, sub: str, evidence, claimed: int) -> str:
    from diag_project.services import analysis_cache as _ac
    # T-1: temperature·thinkingBudget 을 키에 포함(파라미터 다르면 캐시 갈림).
    #   현재 게이트는 temp=0·thinking=dynamic.
    return _ac.make_key(GATE_PROMPT_VERSION, competency_key, sub,
                        "|".join(evidence or []), int(claimed or 1),
                        os.getenv("ANALYSIS_TEMPERATURE", "temp0"),
                        f"tb{os.getenv('GATE_TB', 'dyn')}")


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
    for sub, info in measured.items():
        ref = level_reference(competency_key, sub)
        claimed = info.get("claimed_level") or 1
        ck = _cache_key(competency_key, sub, info.get("evidence"), claimed)
        if ck in _GATE_CACHE:                       # in-mem 적중
            out[sub] = dict(_GATE_CACHE[ck])
            continue
        from diag_project.services import analysis_cache as _ac
        _pk = _persist_key(competency_key, sub, info.get("evidence"), claimed)
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
              "claimed_level": claimed, "ref": ref, "ck": ck}
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
    jobs = [_judge_batch(competency_key, items, llm, out)] if items else []
    res = await asyncio.gather(*jobs, *[_await_shared(it, f) for it, f in shared])
    retry = []
    for it, verdict in res[len(jobs):]:
        if verdict is not None:
            out[it["sub_name"]] = dict(verdict)
        else:
            retry.append(it)                        # 공유 판정 실패 → 직접 재판정
    if retry:
        _register(retry)
        await _judge_batch(competency_key, retry, llm, out)
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


async def _judge_batch(competency_key: str, items: list, llm,
                       out: Dict[str, Dict[str, Any]]) -> None:
    """items 를 한 번의 LLM 호출로 판정해 out 에 기록(+캐시). 실패는 pending."""
    prompt = _build_gate_prompt(items)

    async def _call_gate():
        # 동시성 상한 + 지수 백오프 재시도(빈 응답/오류에 견딤).
        async with _gate_semaphore():
            last = None
            for attempt in range(GATE_MAX_RETRIES):
                try:
                    raw = await llm(prompt)
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
            verdict = {
                "verified_level": verified,
                "category": r.get("category", "구체행동"),
                "reason": str(r.get("reason", ""))[:120],
                "downgraded": verified is not None and verified < claimed,
                "dropped": verified is None,
                "pending": False,
            }
            out[it["sub_name"]] = verdict
            _GATE_CACHE[it["ck"]] = dict(verdict)        # in-mem 저장
            from diag_project.services import analysis_cache as _ac
            _ac.set("level_gate", _persist_key(
                competency_key, it["sub_name"], it["evidence"],
                it["claimed_level"]), dict(verdict))     # 파일 영속
            if verified is None:
                logger.info("🚧 레벨게이트 탈락 [%s/%s] claimed=Lv.%s → 근거미달(%s)",
                            competency_key, it["sub_name"], claimed,
                            verdict["category"])
            elif verified < claimed:
                logger.info("🔽 레벨게이트 강등 [%s/%s] Lv.%s→Lv.%s (%s)",
                            competency_key, it["sub_name"], claimed, verified,
                            verdict["reason"])
    finally:
        # 기다리는 쪽에 판정 공유(pending 은 공유하지 않음 → None → 재판정).
        for it in items:
            v = out.get(it["sub_name"])
            _release(it, None if (not v or v.get("pending")) else dict(v))
