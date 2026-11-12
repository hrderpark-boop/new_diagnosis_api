"""(2026-11-12 P11d-1) 다시 묻기 턴의 질문 — 전용 호출 1회로 끝낸다.

리더가 직전 질문을 되물었거나('뭔소리야', '무슨 말이야') 내용 없이 수긍만 했을 때('네, 맞아요', 'ㅇㅋ', '네.') 코치는 직전 질문을 **문장을 바꿔** 다시 묻는다.
  clarify      같은 것을 더 쉬운 낱말·더 짧은 문장으로 바꾼 질문 1개(앞의 사과 1문장은 호출자가 붙인다)
  contentless  직전 질문을 한 가지로 좁힌 질문 1개(사과 없음)
시뮬 p11c: 본 호출에 신호만 주고 뒤에서 질문을 골라내던 방식에서는 4턴 모두 직전 질문이 그대로 다시 나갔다. 여기서는 이 일만 하는 호출을 한 번 부르고,
직전 질문과 글자가 같을 때(또는 질문을 못 썼을 때)만 호출자가 그 칸의 기본 질문으로 바꾼다. 다시 쓰기(재시도)는 없다.
"""
from __future__ import annotations

import logging
import os
import re

from diag_project.services.output_guard import is_question, split_sentences

logger = logging.getLogger(__name__)

_KIND_TASK: dict[str, str] = {
    "clarify": ("리더가 방금 한 질문이 무슨 말인지 모르겠다고 했습니다. 같은 것을 더 쉬운 낱말, 더 짧은 문장으로 바꿔 다시 묻습니다. "
                "어려운 한자어와 긴 꾸밈절은 풀어서 씁니다."),
    "contentless": ("리더가 방금 한 질문에 짧게 수긍만 했습니다. 방금 한 질문을 한 가지로 좁혀 다시 묻습니다 — "
                    "그 자리에서 한 말 한마디, 한 행동 하나, 한 사람처럼 답하기 쉬운 한 가지만 묻습니다."),
}


def _norm(t: str | None) -> str:
    return re.sub(r"[\s.,!?~'\"“”‘’…·]+", "", t or "")


def same_text(a: str | None, b: str | None) -> bool:
    """글자가 같은 문장인가(공백·문장부호 무시)."""
    na, nb = _norm(a), _norm(b)
    return bool(na) and na == nb


async def render_reask(llm, *, kind: str, prev_question: str, leader_texts: list[str] | None, persona_name: str | None) -> tuple[str | None, str]:
    """(질문 한 문장 | None, 모드). 모드 'llm' | 'stub' | 'miss:<사유>'(no_llm·error·no_question·same)."""
    from diag_project.services.persona_register import apply_register, register_hint
    if kind not in _KIND_TASK or not (prev_question or "").strip():
        return None, "miss:no_material"
    if os.getenv("FM_LLM_STUB"):
        return None, "stub"
    if llm is None:
        return None, "miss:no_llm"
    said = "\n".join(f"- {re.sub(r'\\s+', ' ', (t or '').strip())[-300:]}" for t in (leader_texts or [])[-4:] if (t or "").strip())
    prompt = (
        f"당신은 리더십 코치 {persona_name or 'Ella'}입니다. {_KIND_TASK[kind]}\n\n"
        f"[방금 한 질문]\n{prev_question.strip()}\n\n"
        + (f"[이 이야기에서 리더가 한 말]\n{said}\n\n" if said else "")
        + "[규칙]\n- 질문 한 문장만 쓴다(물음표로 끝난다). 사과·설명·다른 문장을 덧붙이지 않는다.\n"
        "- 방금 한 질문과 같은 문장을 쓰지 않는다. 묻는 것은 같다 — 새 주제나 다른 이야기로 가지 않는다.\n"
        "- 리더가 말하지 않은 사실을 넣지 않는다. 선택지를 늘어놓지 않는다.\n"
        f"- 말투: {register_hint(persona_name)}\n\n"
        "출력: 질문 한 문장만."
    )
    try:
        out = await llm._generate_with_retry(prompt=prompt, max_tokens=160, thinking_budget=0, call_type="reask_render", temperature=0.4)
    except Exception as e:  # noqa: BLE001
        logger.warning("다시 묻기 질문 렌더 실패: %s", e)
        return None, "miss:error"
    text = re.sub(r"\s*\n+\s*", " ", (out or "").strip().strip('"“”'))
    qs = [x.strip() for x in split_sentences(text) if x.strip() and is_question(x)]
    if not qs:
        return None, "miss:no_question"
    q = apply_register(persona_name, qs[-1], scope="questions")[0]
    if same_text(q, prev_question):
        return None, "miss:same"
    return q, "llm"
