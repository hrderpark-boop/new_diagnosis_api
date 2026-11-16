"""(2026-11-16 P14b-3) 구체화 질문 — 전용 호출 1회로 질문 한 문장을 쓴다(첫 꼬리 전용 호출 first_probe_render 와 같은 구조).

P14: 방향만 사례 카드로 넘기고 본 호출이 쓰게 했더니 3건 가운데 2건이 구체화가 아니라 다른 사람의 반응을 물었다 — 본 호출 지시문에는
칸 상태·코치 프로필이 함께 들어 있다. 여기서는 리더의 직전 답과 대상(행동/결과)·말투·쓴 끝맺음만 넘긴다.
확인(turn_checks.specify_question_ok)에서 떨어지면 사유를 넘겨 한 번 더 쓴다. 그래도 안 되면 None — 호출자는 본 호출로 넘어간다.
"""
from __future__ import annotations

import logging
import os
import re

from diag_project.services.output_guard import is_question, split_sentences

logger = logging.getLogger(__name__)

ANSWER_TAIL_CHARS = 700
_TARGET_WHAT: dict[str, str] = {
    "action": "리더가 방금 말한 자기 행동 가운데 두루뭉술한 대목 하나",
    "result": "리더가 방금 말한 결과 가운데 두루뭉술한 대목 하나",
}
RETRY_NOTES: dict[str, str] = {
    "off": "다른 사람의 반응이나 생각·이유를 물었다",
    "no_mark": "숫자나 장면을 청하지 않았다",
    "meta": "질문 말고 다른 말이 섞였거나 문장이 둘 이상이었다",
    "unfinished": "문장을 끝맺지 않았다",
    "no_question": "질문 문장이 없었다",
}


def build_specify_prompt(*, leader_answer: str, target: str, persona_name: str | None, used_endings: list[str] | None = None, retry_note: str | None = None) -> str:
    from diag_project.services.persona_register import register_hint
    ans = re.sub(r"\s+", " ", (leader_answer or "").strip())[-ANSWER_TAIL_CHARS:]
    ends = [x for x in (used_endings or []) if x][:6]
    return (
        "당신은 리더십 코치입니다. 리더가 방금 한 말이 두루뭉술합니다. 그 말을 구체로 만드는 질문 한 문장을 씁니다.\n\n"
        f"[리더가 방금 한 말]\n{ans}\n\n"
        "[규칙]\n- 질문 한 문장만 쓴다. 질문 앞뒤에 다른 문장을 덧붙이지 않는다.\n"
        f"- {_TARGET_WHAT.get(target) or _TARGET_WHAT['action']}를 리더가 쓴 낱말로 집는다.\n"
        "- 그 대목을 보여 주는 숫자·횟수·기간, 또는 실제로 있었던 장면 하나를 청한다. 둘 가운데 하나만 청한다.\n"
        "- 다른 사람의 반응·생각, 리더의 이유는 묻지 않는다. 새로운 주제로 넘어가지 않는다.\n"
        "- 리더가 말하지 않은 사실은 넣지 않는다. 리더를 부를 때는 '리더님'이라고만 한다.\n"
        "- 묻는 꼴로 끝낸다. 온전한 문장으로 끝내고 물음표로 맺는다.\n"
        f"- 말투: {register_hint(persona_name)}\n"
        + ("- 이번 영역에서 이미 쓴 질문 끝맺음: " + " / ".join(f"'{x}'" for x in ends) + " — 이것과 다른 끝맺음으로 끝낸다.\n" if ends else "")
        + (f"- 앞서 쓴 질문은 쓸 수 없었다 — {retry_note}. 그 점을 고쳐 새로 쓴다.\n" if retry_note else "")
        + "\n출력: 질문 한 문장만."
    )


async def render_specify(llm, *, leader_answer: str, target: str, persona_name: str | None, used_endings: list[str] | None = None) -> tuple[str | None, str]:
    """(질문 한 문장 | None, 모드). 모드 'llm' | 'llm_retry' | 'stub' | 'miss:<사유>'."""
    from diag_project.services.persona_register import apply_register
    from diag_project.services.turn_checks import finish_sentence_marks, fix_leader_address, specify_question_ok
    if not (leader_answer or "").strip():
        return None, "miss:no_material"
    if os.getenv("FM_LLM_STUB"):
        return None, "stub"
    if llm is None:
        return None, "miss:no_llm"
    note = None
    why = "no_question"
    for attempt in (0, 1):
        try:
            out = await llm._generate_with_retry(
                prompt=build_specify_prompt(leader_answer=leader_answer, target=target, persona_name=persona_name, used_endings=used_endings, retry_note=note),
                max_tokens=160, thinking_budget=0, call_type="specify_render", temperature=0.4)
        except Exception as e:  # noqa: BLE001
            logger.warning("specify render failed: %s", e)
            return None, "miss:error"
        text = finish_sentence_marks(re.sub(r"\s*\n+\s*", " ", (out or "").strip().strip('"“”')))[0]
        full = " ".join(x.strip() for x in split_sentences(text) if x.strip())
        q = fix_leader_address(apply_register(persona_name, full, scope="questions")[0]) if any(is_question(x) for x in split_sentences(full)) else ""
        ok, why = specify_question_ok(q)
        if ok:
            return q, ("llm_retry" if attempt else "llm")
        note = RETRY_NOTES.get(why.split(":")[0], "질문으로 쓸 수 없는 문장이었다")
    return None, f"miss:{why}"
