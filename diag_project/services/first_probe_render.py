"""(2026-11-15 P13d-2) 사례의 첫 꼬리 질문 — 전용 호출 1회로 만든다(다시 묻기 전용 호출 reask_render 와 같은 구조).

사례를 여는 질문에 리더가 답한 바로 다음 턴(훑는 질문의 꼬리 질문 포함)은 리더 본인이 직접 한 말이나 조치만 묻는다.
p13b·p13c: 본 호출에 전용 지시를 줘도 9건 가운데 4건이 때·장면·기준·결과를 물었다 — 본 호출 프롬프트에는 칸 상태·방향 힌트·코치 프로필·영역 정의가
함께 들어 있어 묻는 것이 그쪽으로 끌렸다. 여기서는 그 재료를 넘기지 않는다.
  넘기는 것     리더의 직전 답 · 코치 말투 · 이번 영역에서 이미 쓴 질문 끝맺음
  넘기지 않는 것 칸 상태 · 방향 힌트 · 코치 프로필 · 탐침 선호 · 영역 정의
받는 말은 만들지 않는다(질문 한 문장). 합격 여부(turn_checks.first_probe_question_ok)는 호출자가 보고, 불합격·실패면 다시 쓰지 않고 대체 문장을 쓴다.
"""
from __future__ import annotations

import logging
import os
import re

from diag_project.services.output_guard import is_question, split_sentences

logger = logging.getLogger(__name__)

ANSWER_TAIL_CHARS = 700            # 리더 직전 답은 끝에서 이만큼만 넘긴다


def build_first_probe_prompt(*, leader_answer: str, persona_name: str | None, used_endings: list[str] | None = None) -> str:
    from diag_project.services.persona_register import register_hint
    ans = re.sub(r"\s+", " ", (leader_answer or "").strip())[-ANSWER_TAIL_CHARS:]
    ends = [x for x in (used_endings or []) if x][:6]
    return (
        "당신은 리더십 코치입니다. 리더가 방금 어떤 일을 이야기했습니다. 그 일에서 리더 본인이 직접 한 말이나 조치를 묻는 질문 한 문장을 씁니다.\n\n"
        f"[리더가 방금 한 말]\n{ans}\n\n"
        "[규칙]\n- 질문 한 문장만 쓴다. 질문 앞뒤에 다른 문장을 덧붙이지 않는다.\n"
        "- 리더가 방금 한 말에 나온 사람이나 일의 낱말 하나를 질문에 넣는다. 리더가 말하지 않은 사실은 넣지 않는다.\n"
        "- 묻는 것은 하나다 — 그 일에서 리더 본인이 직접 한 말이나 조치.\n"
        "- 묻지 않는 것: 때·자리·장면, 다른 사람의 반응, 리더의 생각·기준, 결과.\n"
        "- 고를 것을 늘어놓지 않는다. 한 문장에 두 가지를 묻지 않는다.\n"
        f"- 말투: {register_hint(persona_name)}\n"
        + ("- 이번 영역에서 이미 쓴 질문 끝맺음: " + " / ".join(f"'{x}'" for x in ends) + " — 이것과 다른 끝맺음으로 끝낸다.\n" if ends else "")
        + "\n출력: 질문 한 문장만."
    )


async def render_first_probe(llm, *, leader_answer: str, persona_name: str | None, used_endings: list[str] | None = None) -> tuple[str | None, str]:
    """(질문 한 문장 | None, 모드). 모드 'llm' | 'stub' | 'miss:<사유>'(no_material·no_llm·error·no_question)."""
    from diag_project.services.persona_register import apply_register
    if not (leader_answer or "").strip():
        return None, "miss:no_material"
    if os.getenv("FM_LLM_STUB"):
        return None, "stub"
    if llm is None:
        return None, "miss:no_llm"
    prompt = build_first_probe_prompt(leader_answer=leader_answer, persona_name=persona_name, used_endings=used_endings)
    try:
        out = await llm._generate_with_retry(prompt=prompt, max_tokens=160, thinking_budget=0, call_type="first_probe_render", temperature=0.4)
    except Exception as e:  # noqa: BLE001
        logger.warning("첫 꼬리 질문 렌더 실패: %s", e)
        return None, "miss:error"
    text = re.sub(r"\s*\n+\s*", " ", (out or "").strip().strip('"“”'))
    qs = [x.strip() for x in split_sentences(text) if x.strip() and is_question(x)]
    if not qs:
        return None, "miss:no_question"
    return apply_register(persona_name, qs[0], scope="questions")[0], "llm"      # 질문 문장이 둘이면 첫 문장만
