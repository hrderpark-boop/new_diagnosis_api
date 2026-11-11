"""(2026-10-21) 앵커 렌더링 — ANCHOR_RENDER=dict(기본) | llm. 결정용 플래그.

dict : 앵커 사전(SUBCOMPETENCY_ANCHOR_QUESTIONS)의 문장을 그대로 쓴다(기존 동작).
llm  : 직전 2턴 + role_summary + must_ask 로 질문 1문장을 렌더링 → flash 판정 "must_ask 전부 담겼는가" →
       아니면 사전 문장 폴백(폴백은 로그·guard_log 에 남는다).
규칙(두 모드 공통): 하위역량 이름 미노출 · 시점+행동이 드러나는 구체 경험 1개 · 은유 없음 · 질문 한 문장.
"""
from __future__ import annotations

import logging
import os
import re

from diag_project.data.competencies import (
    COMPETENCY_FRAMEWORK, SUBCOMPETENCY_MUST_ASK, get_anchor_questions,
)
from diag_project.services.llm_judge import must_ask_covered
from diag_project.services.output_guard import find_sub_names, is_question, split_sentences

logger = logging.getLogger(__name__)

_METAPHOR_RE = re.compile(r"항해|나침반|무대|여정|등대|키를 잡|닻|파도|바람을 타|뿌리|씨앗|불씨|터널")
_ALL_SUB_NAMES = [v.get("name") for c in COMPETENCY_FRAMEWORK.values() for v in (c.get("indicators") or {}).values()]


def anchor_render_mode() -> str:
    m = (os.getenv("ANCHOR_RENDER") or "dict").strip().lower()
    return "llm" if m == "llm" else "dict"


def dict_anchor(sub_key: str | None, pos: int = 0) -> str:
    qs = get_anchor_questions(sub_key) if sub_key else []
    if not qs:
        return "최근에 리더님이 직접 나서서 풀어야 했던 일이 하나 있으셨어요?"
    return qs[pos % len(qs)]


def _valid_rendered(q: str) -> bool:
    s = (q or "").strip()
    if not s or not is_question(s) or s.count("?") != 1:
        return False
    if find_sub_names(s, _ALL_SUB_NAMES) or _METAPHOR_RE.search(s):
        return False
    return len(s) <= 120


async def render_anchor(
    llm, sub_key: str | None, *, recent_turns: list[str], role_summary: str | None, pos: int = 0,
) -> tuple[str, str]:
    """(질문, 모드) — 모드는 'dict' | 'llm' | 'fallback'. llm 이 None 이거나 dict 모드면 사전 문장."""
    base = dict_anchor(sub_key, pos)
    if anchor_render_mode() != "llm" or llm is None or not sub_key:
        return base, "dict"
    must = SUBCOMPETENCY_MUST_ASK.get(sub_key) or []
    if not must:
        return base, "dict"
    ctx = "\n".join(f"- {t.strip()[:200]}" for t in recent_turns if t and t.strip()) or "- (없음)"
    prompt = (
        "당신은 리더십 BEI 코치입니다. 리더에게 과거의 구체적 경험 하나를 청하는 질문을 **한 문장**으로 만드세요.\n\n"
        f"[직전 대화 2턴]\n{ctx}\n\n"
        f"[리더의 담당 업무] {role_summary or '(모름)'}\n\n"
        "[반드시 담을 것 — 전부]\n" + "\n".join(f"- {k}" for k in must) + "\n\n"
        f"[결 참고 — 그대로 쓰지 말고 리더의 맥락에 맞게 새로] {base}\n\n"
        "규칙: 역량·하위역량 이름을 말하지 않는다. 시점(최근/언제)과 리더가 실제로 한 행동이 드러나게 묻는다. "
        "은유·비유 금지. 평가·칭찬 금지. 존댓말. 물음표 하나, 한 문장만 출력."
    )
    try:
        out = await llm._generate_with_retry(
            prompt=prompt, max_tokens=120, thinking_budget=0, call_type="anchor_render", temperature=0.4,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("앵커 렌더링 실패 → 사전 폴백: %s", e)
        return base, "fallback"
    qs = [s for s in split_sentences((out or "").strip()) if is_question(s)]
    q = qs[-1].strip() if qs else (out or "").strip()
    if not _valid_rendered(q):
        logger.info("앵커 렌더링 형식 불합격 → 사전 폴백: %r", q[:80])
        return base, "fallback"
    ok = await must_ask_covered(llm, q, must)
    if ok is not True:
        logger.info("앵커 렌더링 must_ask 판정 %s → 사전 폴백: %r", ok, q[:80])
        return base, "fallback"
    return q, "llm"


# ── (2026-11-05 P4-4) 사례 여는 질문 = [왜 묻는지 1문장] + [있었는지 질문] ────────────────────────────────
#   LLM 이 하위역량 정의를 리더 말로 풀어 쓴다. '~받으셨을 때 어떻게' 처럼 있었음을 전제하는 문형 금지. 검사 불합격·실패는 사전 앵커 폴백.
_PRESUPPOSE_RE = re.compile(r"(하셨을 때|받으셨을 때|했을 때|겪으셨을 때|들으셨을 때|생겼을 때|때 어떻게|때는 어떻게|때 무엇을|때 뭘|때 어떤 식)")
_EXIST_RE = re.compile(r"(있으셨|있었|있으세요|있나요|있을까요|있으신가요|있습니까|있으십니까|떠오르|기억(나|에 남)|겪으신 적|하신 적|해 ?보신 적|"
                       r"들려주(세요|시겠|실래|시지요|시죠)|말씀해 주|얘기해 주|꼽으신다면|하나만)")
_WHY_CLAUSE_RE = re.compile(r"^(.{8,}?(인데요|건데요|것인데요|거든요|보려고요|보려고 해요|궁금해서요|보는 쪽이에요|입니다만|습니다만))[,，]\s*(.{6,}\?)$")
_OPENER_EXAMPLE_WORDS = ("장바구니", "장을 보", "장 볼", "장 보는")   # (P10) 결 참고 예시(다른 분야)의 낱말 — 출력에 들어오면 베낀 것
_OPENER_WHY_MAX = 2       # 질문 앞 평서문 최대 2문장
_OPENER_TAIL_MAX = 1      # 질문 뒤 짧은 덧붙임('작은 일이어도요.') 최대 1문장


def opener_shape_ok(text: str) -> tuple[bool, str]:
    """여는 문장 형식 검사 — (통과, 사유). 질문 1개 · 질문 앞 평서문 1~2 · 있었는지 묻는 문형 · 전제형 아님 · 이름·은유 없음 · 길이."""
    sents = [x.strip() for x in split_sentences((text or "").strip()) if x.strip()]
    if not sents:
        return False, "empty"
    qs = [i for i, x in enumerate(sents) if is_question(x)]
    if len(qs) != 1:
        return False, f"questions={len(qs)}"
    qi = qs[0]
    if qi == 0:
        # '…보는 쪽인데요, 최근에 …있으셨어요?' — 왜 묻는지 절이 쉼표로 질문에 붙은 한 문장도 허용
        m = _WHY_CLAUSE_RE.match(sents[0])
        if not m:
            return False, "no_why"
        sents = [m.group(1).strip(), m.group(3).strip()] + sents[1:]
        qi = 1
    if qi > _OPENER_WHY_MAX or len(sents) - qi - 1 > _OPENER_TAIL_MAX:
        return False, "too_long"
    q = sents[qi]
    if _PRESUPPOSE_RE.search(q):
        return False, "presupposes"
    if not _EXIST_RE.search(q):
        return False, "not_existence_question"
    if find_sub_names(text, _ALL_SUB_NAMES) or _METAPHOR_RE.search(text):
        return False, "name_or_metaphor"
    if len(text) > 240 or len(q) > 130:
        return False, "length"
    if any(w in text for w in _OPENER_EXAMPLE_WORDS):
        return False, "example_copied"
    from diag_project.services.phrase_caps import is_filler_sentence
    if any(is_filler_sentence(x) for x in sents[:qi]):
        return False, "filler"                      # (P10-3) '~은 팀마다, 사람마다 다릅니다' 류 채움 문장
    return True, ""


def _sub_material(chapter: str | None, sub_key: str | None) -> dict:
    ind = ((COMPETENCY_FRAMEWORK.get(chapter or "", {}) or {}).get("indicators") or {}).get(sub_key or "", {}) or {}
    cues = [c.split(":", 1)[1].strip() for c in (SUBCOMPETENCY_MUST_ASK.get(sub_key or "") or []) if c.startswith("행동")]
    ex2 = str((ind.get("examples") or {}).get(2) or "")
    lv2 = next((ln.strip().lstrip("・•·-").strip() for ln in ex2.split("\n") if ln.strip()), "")
    return {"name": ind.get("name", ""), "lv2": str((ind.get("levels") or {}).get(2) or ""), "lv3": str((ind.get("levels") or {}).get(3) or ""),
            "example": lv2, "cue": cues[0] if cues else ""}


# (2026-11-10 P9-7 → 2026-11-11 P10-3) 여는 문장(왜 묻는지) 틀 3종 — 세션에서 연 사례 순번으로 돌린다.
#   P10-3: 채움 문장 틀('~하는 방식은 팀마다, 사람마다 다릅니다')은 삭제 — 어느 주제에나 붙는 일반론이었다. 대신 '주제 절 + 질문' 한 문장 틀.
#   '이번에는 ~ 쪽 이야기' 틀은 세션 2회만(순번 1·5). 틀 설명은 어미를 싣지 않는다 — 합쇼체로 쓴 틀을 해요체 코치가 그대로 베꼈다(11/11 Olivia).
OPENER_FRAMES = (
    "무엇을 듣고 싶은지 말하는 한 문장('~을 어떻게 하시는지 듣고 싶다'는 뜻). 그 다음 문장이 질문.",
    "주제를 바꾸는 짧은 한 문장('이번에는 ~ 쪽 이야기'라는 뜻). 그 다음 문장이 질문.",
    "평서문을 따로 두지 않고 질문 한 문장으로만 쓴다 — 무엇에 관한 것인지를 앞 절에 넣고 쉼표로 이어서 묻는다('~에 관한 건데요, 최근에 ~ 있으셨어요?' 꼴).",
)
OPENER_FRAME_EXAMPLES = (
    "장을 볼 때 무엇부터 담으시는지 듣고 싶어요. 최근에 계획에 없던 것을 장바구니에 담으신 적 있으셨어요?",
    "이번에는 장을 보는 쪽 이야기예요. 최근에 계획에 없던 것을 장바구니에 담으신 적 있으셨어요?",
    "장 볼 때 순서를 정하는 일에 관한 건데요, 최근에 계획에 없던 것을 장바구니에 담으신 적 있으셨어요?",
)
_OPENER_FRAME_SEQ = (0, 1, 2, 0, 2, 1, 0, 2)


def opener_frame_for(n_opened: int) -> int:
    """세션에서 n 번째(0부터)로 여는 사례의 틀 — '이번에는 ~ 쪽 이야기'(1번 틀)는 세션에서 두 번만, 그 뒤로는 0·2번을 번갈아."""
    n = max(0, int(n_opened))
    if n < len(_OPENER_FRAME_SEQ):
        return _OPENER_FRAME_SEQ[n]
    return 0 if n % 2 == 0 else 2


def _frame_example(persona_name: str | None, frame: int) -> str:
    """틀 예시를 그 페르소나의 말투로 — 해요체 예시를 합쇼체 코치에게 주면 어미가 섞인다."""
    from diag_project.services.persona_register import apply_register
    ex = OPENER_FRAME_EXAMPLES[int(frame) % len(OPENER_FRAME_EXAMPLES)]
    out = apply_register(persona_name, ex, scope="strict")[0]
    return out.replace("건데요,", "것입니다만,") if out != ex or "습니까" in out else out


async def render_opener(
    llm, *, chapter: str | None, sub_key: str | None, persona_name: str | None, leader_text: str | None, fallback_question: str,
    register_hint: str = "", frame: int = 0,
) -> tuple[str, str]:
    """(여는 문장 전체, 모드). 모드 'llm' | 'llm_regen' | 'fallback'. 폴백은 fallback_question(사전 앵커, 이미 페르소나 어미) 그대로."""
    mat = _sub_material(chapter, sub_key)
    if os.getenv("FM_LLM_STUB"):
        return fallback_question, "stub"          # 스텁 스모크·pytest: LLM 0콜, 사전 앵커 그대로
    if llm is None or not sub_key or not mat.get("name"):
        return fallback_question, "fallback"
    lead = re.sub(r"\s+", " ", (leader_text or "").strip())[-200:]
    from diag_project.services.persona_register import apply_register as _areg_r, register_hint as _rh_r, register_violations as _rv_r
    frame = int(frame) % len(OPENER_FRAMES)
    one_sentence = frame == 2
    base = (
        "당신은 리더십 BEI 코치입니다. 리더에게 새 사례 하나를 청하는 '여는 문장'을 만드세요. "
        + ("출력은 정확히 한 문장(질문)입니다.\n\n" if one_sentence else "출력은 정확히 두 문장입니다.\n\n")
        + "① 왜 묻는지 — 아래 [무엇을 보는지]를 리더가 쓰는 일상어로 풀어 씁니다. 역량·하위역량 이름, '역량'·'항목'·'지표' 같은 말은 쓰지 않습니다.\n"
        f"   이번 틀: {OPENER_FRAMES[frame]} '살펴보려고'·'궁금'이라는 말은 쓰지 않습니다. "
        "'~은 팀마다, 사람마다 다르다' 같은 누구에게나 맞는 일반론은 쓰지 않습니다.\n"
        "② 있었는지 묻는 질문 — '최근에 ~한 일이 있으셨어요?' 처럼 그런 일이 있었는지 여는 질문. "
        "있었음을 전제하는 문형('~받으셨을 때 어떻게', '~하셨을 때 무엇을')은 금지합니다. 선택지·가정형 금지. 은유 금지. 평가·칭찬 금지.\n"
        "질문 뒤 덧붙임은 없어도 되고, 쓰면 1문장(범위를 낮추는 말)으로 — 세션 안에서 같은 덧붙임을 되풀이하지 않는다.\n\n"
        f"[무엇을 보는지 — {mat['name']}(이름은 쓰지 말 것)]\n- 정의: {mat['lv2']}\n- 한 단계 위: {mat['lv3']}\n"
        + (f"- 행동 예: {mat['example']}\n" if mat.get("example") else "") + (f"- 행동 단서: {mat['cue']}\n" if mat.get("cue") else "")
        # (P10 p10a) 한 문장 틀에서는 리더의 직전 말을 주지 않는다 — 주제 절 대신 직전 답을 되물어('…먼저 꺼내 보신 적이 있으셨나요?') 2회 다 불합격했다
        + (f"\n[리더가 방금 한 말(결만 참고, 되받지 않는다)] {lead}\n" if (lead and not one_sentence) else "")
        + f"\n[코치 말투] {persona_name or 'Ella'} — {_rh_r(persona_name)}" + (f" ({register_hint})" if register_hint else "") + "\n"
        "\n[결 참고 — 진단과 무관한 분야의 예. 낱말을 그대로 쓰지 말 것] " + _frame_example(persona_name, frame) + "\n"
        + ("\n한 문장입니다: 앞 절(무엇에 관한 것인지) + 쉼표 + 그런 일이 있었는지 묻는 질문.\n" if one_sentence else
           "\n순서가 중요합니다: 첫 문장은 물음표 없는 평서문(무엇을 보는지), 그 다음 문장이 질문입니다. 질문으로 시작하면 실패입니다.\n")
        + "\n출력: 문장만. 따옴표·머리말·설명 없이."
    )
    mode = "llm"
    prompt = base
    for attempt in range(2):
        try:
            out = await llm._generate_with_retry(prompt=prompt, max_tokens=200, thinking_budget=0, call_type="opener_render", temperature=0.5)
        except Exception as e:  # noqa: BLE001
            logger.warning("여는 문장 렌더링 실패 → 사전 폴백: %s", e)
            return fallback_question, "fallback"
        text = re.sub(r"\s*\n+\s*", " ", (out or "").strip().strip('"“”'))
        text = _areg_r(persona_name, text, scope="strict")[0]          # (P10-4) 여는 문장은 코치 어미 강제 — 표로 고칠 수 있는 꼴은 여기서
        ok, why = opener_shape_ok(text)
        if ok and _rv_r(persona_name, text, scope="strict"):
            ok, why = False, "register"
        if ok:
            return text, mode
        logger.info("여는 문장 형식 불합격(%s) → %s: %r", why, "재생성" if attempt == 0 else "사전 폴백", text[:90])
        mode = "llm_regen"
        prompt = base + (f"\n\n🚨 방금 출력은 형식이 어긋났습니다({why}). "
                         + ("앞 절 + 쉼표 + 그런 일이 있었는지 묻는 질문, 한 문장으로만 다시 쓰세요." if one_sentence else
                            "첫 문장 = 물음표 없는 평서문(이 영역에서 무엇을 보는지), 둘째 문장 = 그런 일이 있었는지 묻는 질문. 이 순서로 두 문장만 다시 쓰세요.")
                         + f" 말투는 {_rh_r(persona_name)}")   # p4b: 2/2 가 질문부터 시작(no_why)
    return fallback_question, "fallback"

