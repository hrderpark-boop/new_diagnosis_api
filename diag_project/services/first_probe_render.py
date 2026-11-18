"""(2026-11-15 P13d-2) 사례의 첫 꼬리 질문 — 전용 호출 1회로 만든다(다시 묻기 전용 호출 reask_render 와 같은 구조).

사례를 여는 질문에 리더가 답한 바로 다음 턴(훑는 질문의 꼬리 질문 포함)은 리더 본인이 직접 한 말이나 조치만 묻는다.
p13b·p13c: 본 호출에 전용 지시를 줘도 9건 가운데 4건이 때·장면·기준·결과를 물었다 — 본 호출 프롬프트에는 칸 상태·방향 힌트·코치 프로필·영역 정의가
함께 들어 있어 묻는 것이 그쪽으로 끌렸다. 여기서는 그 재료를 넘기지 않는다.
  넘기는 것     리더의 직전 답 · 코치 말투 · 이번 영역에서 이미 쓴 질문 끝맺음
  넘기지 않는 것 칸 상태 · 방향 힌트 · 코치 프로필 · 탐침 선호 · 영역 정의
(2026-11-15 P13e-1 → P13f-2) 묻는 각도는 셋(그때 한 말 / 직접 취한 조치 / 일을 진행한 순서) — 호출자가 리더 답에 이미 나온 각도와
직전에 쓴 각도를 피해 하나를 골라 넘긴다(turn_checks.pick_first_probe_angle). p13d: 57개 가운데 44개가 '직접 어떤 말(씀)을 …' 한 뼈대였다.
받는 말은 만들지 않는다. (2026-11-18 P15 판정 2) 한 번의 호출에서 질문 후보를 둘 받는다 — 호출자가 차례로 확인해 먼저 통과하는 것을 쓰고,
둘 다 떨어지면 대체 문장을 쓴다. 다시 부르지 않는다(p15: 첫 꼬리 턴 21개 가운데 19개가 한 번 더 써서 지연이 1초 늘었다).
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


def build_first_probe_prompt(*, leader_answer: str, persona_name: str | None, used_endings: list[str] | None = None, angle: str = "said") -> str:
    from diag_project.services.persona_register import register_hint
    ans = re.sub(r"\s+", " ", (leader_answer or "").strip())[-ANSWER_TAIL_CHARS:]
    ends = [x for x in (used_endings or []) if x][:6]
    return (
        "당신은 리더십 코치입니다. 리더가 방금 어떤 일을 이야기했습니다. 그 일에서 리더 본인이 직접 한 것을 묻는 질문을 두 개 씁니다.\n\n"
        f"[리더가 방금 한 말]\n{ans}\n\n"
        "[규칙]\n- 질문은 각각 한 문장이다. 질문 앞뒤에 다른 문장을 덧붙이지 않는다.\n"
        # (2026-11-18 P15-3 → 판정 1) 앞 절 금지는 철회 — 리더 답을 옮기는 부분의 길이로 묶는다(절 하나, 6어절 이하). 질문 전체는 8~20어절.
        "- 리더가 방금 한 말을 다시 쓰는 부분은 절 하나, 6어절 이하다. 리더가 말하지 않은 사실은 넣지 않는다.\n"
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
        # (P15 판정 2) 순차 다시 쓰기 대신 한 번에 후보 둘 — 코드가 먼저 통과하는 것을 고른다
        + "\n출력: 서로 다른 질문 두 개를 한 줄에 하나씩. 번호와 설명은 붙이지 않는다."
    )


_CAND_HEAD_RE = re.compile(r"^\s*(?:\d+\s*[.)]|[-•·*]|[①②])\s*")


def split_candidates(raw: str | None) -> list[str]:
    """전용 호출 출력에서 질문 후보를 꺼낸다 — 줄마다 하나(번호·글머리표는 뗀다). 한 줄에 두 문장을 이어 쓴 경우는 문장으로 가른다."""
    lines = [_CAND_HEAD_RE.sub("", ln).strip().strip('"“”') for ln in (raw or "").split("\n")]
    lines = [ln for ln in lines if ln]
    if len(lines) == 1:
        sents = [x.strip() for x in split_sentences(lines[0]) if x.strip()]
        if len(sents) == 2 and all(is_question(x) for x in sents):
            lines = sents
    return lines


async def render_first_probe(llm, *, leader_answer: str, persona_name: str | None, used_endings: list[str] | None = None,
                             angle: str = "said") -> tuple[list[str], str]:
    """(질문 후보 목록(최대 2), 모드). 모드 'llm' | 'stub' | 'miss:<사유>'(no_material·no_llm·error·no_question).
    (2026-11-18 P15 판정 2) 호출은 한 번뿐이다 — 확인에서 떨어져도 다시 부르지 않는다. 후보의 합격 여부는 호출자가 차례로 본다."""
    from diag_project.services.persona_register import apply_register
    from diag_project.services.turn_checks import finish_sentence_marks, fix_leader_address
    if not (leader_answer or "").strip():
        return [], "miss:no_material"
    if os.getenv("FM_LLM_STUB"):
        return [], "stub"
    if llm is None:
        return [], "miss:no_llm"
    prompt = build_first_probe_prompt(leader_answer=leader_answer, persona_name=persona_name, used_endings=used_endings, angle=angle)
    try:
        out = await llm._generate_with_retry(prompt=prompt, max_tokens=280, thinking_budget=0, call_type="first_probe_render", temperature=0.4)
    except Exception as e:  # noqa: BLE001
        logger.warning("첫 꼬리 질문 렌더 실패: %s", e)
        return [], "miss:error"
    cands: list[str] = []
    for ln in split_candidates(out)[:2]:
        text = finish_sentence_marks(ln)[0]      # (P13e-4) '…궁금해요?' → '.', 끝 부호 없는 물음에 '?'
        if not any(is_question(x) for x in split_sentences(text) if x.strip()):
            continue
        # 문장이 둘 이상인 후보는 호출자의 확인에서 떨어진다(여기서 첫 문장만 골라내지 않는다 — 혼잣말이 섞인 출력)
        full = " ".join(x.strip() for x in split_sentences(text) if x.strip())
        cands.append(fix_leader_address(apply_register(persona_name, full, scope="questions")[0]))
    return (cands, "llm") if cands else ([], "miss:no_question")
