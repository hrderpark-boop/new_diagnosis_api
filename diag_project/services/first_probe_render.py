"""(2026-11-15 P13d-2) 사례의 첫 꼬리 질문 — 전용 호출 1회로 만든다(다시 묻기 전용 호출 reask_render 와 같은 구조).

사례를 여는 질문에 리더가 답한 바로 다음 턴(훑는 질문의 꼬리 질문 포함)은 리더 본인이 직접 한 말이나 조치만 묻는다.
p13b·p13c: 본 호출에 전용 지시를 줘도 9건 가운데 4건이 때·장면·기준·결과를 물었다 — 본 호출 프롬프트에는 칸 상태·방향 힌트·코치 프로필·영역 정의가
함께 들어 있어 묻는 것이 그쪽으로 끌렸다. 여기서는 그 재료를 넘기지 않는다.
  넘기는 것     리더의 직전 답 · 코치 말투 · 이번 영역에서 이미 쓴 질문 끝맺음
  넘기지 않는 것 칸 상태 · 방향 힌트 · 코치 프로필 · 탐침 선호 · 영역 정의
(2026-11-15 P13e-1 → P13f-2) 묻는 각도는 셋(그때 한 말 / 직접 취한 조치 / 일을 진행한 순서) — 호출자가 리더 답에 이미 나온 각도와
직전에 쓴 각도를 피해 하나를 골라 넘긴다(turn_checks.pick_first_probe_angle). p13d: 57개 가운데 44개가 '직접 어떤 말(씀)을 …' 한 뼈대였다.
받는 말은 만들지 않는다(질문 한 문장). 합격 여부(turn_checks.first_probe_question_ok)는 호출자가 보고, 불합격·실패면 다시 쓰지 않고 대체 문장을 쓴다.
"""
from __future__ import annotations

import logging
import os
import re

from diag_project.services.output_guard import is_question, split_sentences

logger = logging.getLogger(__name__)

ANSWER_TAIL_CHARS = 700            # 리더 직전 답은 끝에서 이만큼만 넘긴다


# 각도별 '묻는 것' — 설명으로만 적는다(완성 문장 꼴을 적으면 그대로 출력에 나온다)
ANGLE_ASK: dict[str, str] = {
    "said": "그 일에서 리더 본인이 상대에게 실제로 한 말",
    "did": "그 일에서 리더 본인이 직접 취한 조치(말이 아니라 한 일)",
    "order": "리더 본인이 그 일을 진행한 순서(무엇부터 했고 그다음에 무엇을 했는지)",
}


def build_first_probe_prompt(*, leader_answer: str, persona_name: str | None, used_endings: list[str] | None = None, angle: str = "said",
                             retry_note: str | None = None) -> str:
    from diag_project.services.persona_register import register_hint
    ans = re.sub(r"\s+", " ", (leader_answer or "").strip())[-ANSWER_TAIL_CHARS:]
    ends = [x for x in (used_endings or []) if x][:6]
    return (
        "당신은 리더십 코치입니다. 리더가 방금 어떤 일을 이야기했습니다. 그 일에서 리더 본인이 직접 한 것을 묻는 질문 한 문장을 씁니다.\n\n"
        f"[리더가 방금 한 말]\n{ans}\n\n"
        "[규칙]\n- 질문 한 문장만 쓴다. 질문 앞뒤에 다른 문장을 덧붙이지 않는다.\n"
        # (2026-11-18 P15-3) 되짚는 앞 절 금지 — 11/18 운영 Lucas: 질문 6개가 '…하셨는데,'로 리더 답을 다시 말하며 시작했다(회귀 p14f: 코치당 4~13턴)
        "- 리더가 방금 한 말에서 명사구 하나(4어절 이하)만 질문에 넣는다. 리더가 한 일을 '-셨는데', '-신 뒤', '-실 때'로 끝나는 앞 절로 다시 말하지 않는다. "
        "리더가 말하지 않은 사실은 넣지 않는다.\n"
        "- 문장을 '리더님'으로 시작하지 않는다. 8어절 이상 20어절 이하로 쓴다.\n"
        f"- 묻는 것은 하나다 — {ANGLE_ASK.get(angle) or ANGLE_ASK['said']}. 이것 말고 다른 것을 함께 묻지 않는다.\n"
        "- 질문에 사람을 넣을 때는 리더가 방금 한 말에 나온 사람만 넣는다. 리더가 말하지 않은 상대를 지어내지 않는다.\n"
        "- 그렇다·아니다로 답하게 되는 꼴로 묻지 않는다 — 무엇을 했는지, 어떻게 했는지를 묻는 꼴로 쓴다.\n"
        "- 같은 것을 한 문장 안에서 두 번 겹쳐 묻지 않는다 — 무엇을 했는지 물었으면 어떻게 했는지를 덧붙이지 않는다.\n"
        "- 리더를 부를 때는 '리더님'이라고만 한다. 리더가 한 일에는 높임을 붙인다.\n"
        "- 묻는 꼴로 끝낸다 — 알고 싶다거나 여쭤봐도 되겠느냐는 말로 끝내지 않는다.\n"
        "- 높임은 리더에게만 쓴다. 리더가 아닌 사람이 한 행동에는 높임 어미를 붙이지 않는다.\n"
        "- 온전한 문장으로 끝내고 물음표로 맺는다.\n"
        "- 묻지 않는 것: 때·자리·장면, 다른 사람의 반응, 리더의 생각·기준, 결과.\n"
        "- 고를 것을 늘어놓지 않는다. 한 문장에 두 가지를 묻지 않는다.\n"
        f"- 말투: {register_hint(persona_name)}\n"
        + ("- 이번 영역에서 이미 쓴 질문 끝맺음: " + " / ".join(f"'{x}'" for x in ends) + " — 이것과 다른 끝맺음으로 끝낸다.\n" if ends else "")
        + (f"- 앞서 쓴 질문은 쓸 수 없었다 — {retry_note}. 그 점을 고쳐 새로 쓴다.\n" if retry_note else "")
        + "\n출력: 질문 한 문장만."
    )


async def render_first_probe(llm, *, leader_answer: str, persona_name: str | None, used_endings: list[str] | None = None,
                             angle: str = "said", retry_note: str | None = None) -> tuple[str | None, str]:
    """(질문 한 문장 | None, 모드). 모드 'llm' | 'stub' | 'miss:<사유>'(no_material·no_llm·error·no_question)."""
    from diag_project.services.persona_register import apply_register
    if not (leader_answer or "").strip():
        return None, "miss:no_material"
    if os.getenv("FM_LLM_STUB"):
        return None, "stub"
    if llm is None:
        return None, "miss:no_llm"
    prompt = build_first_probe_prompt(leader_answer=leader_answer, persona_name=persona_name, used_endings=used_endings, angle=angle, retry_note=retry_note)
    try:
        out = await llm._generate_with_retry(prompt=prompt, max_tokens=160, thinking_budget=0, call_type="first_probe_render", temperature=0.4)
    except Exception as e:  # noqa: BLE001
        logger.warning("첫 꼬리 질문 렌더 실패: %s", e)
        return None, "miss:error"
    from diag_project.services.turn_checks import finish_sentence_marks
    text = finish_sentence_marks(re.sub(r"\s*\n+\s*", " ", (out or "").strip().strip('"“”')))[0]      # (P13e-4) '…궁금해요?' → '.', 끝 부호 없는 물음에 '?'
    qs = [x.strip() for x in split_sentences(text) if x.strip() and is_question(x)]
    if not qs:
        return None, "miss:no_question"
    # (2026-11-15 P13g-2) 문장이 둘 이상이면 호출자의 확인에서 떨어진다(한 번 더 쓴다) — 여기서 첫 문장만 골라내지 않는다. p13f Daniel: 혼잣말이 섞인 원문.
    full = " ".join(x.strip() for x in split_sentences(text) if x.strip())
    from diag_project.services.turn_checks import fix_leader_address
    return fix_leader_address(apply_register(persona_name, full, scope="questions")[0]), "llm"
