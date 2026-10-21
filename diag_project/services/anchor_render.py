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
