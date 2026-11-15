"""(2026-11-15 P13f-4) 사례를 닫는 턴의 받는 말 — 매핑 호출과 동시에 도는 전용 호출 1회.

p13d 6코치: 사례를 닫고 다음 질문을 여는 턴은 슬롯 판정 → 매핑 → 본 호출이 차례로 돌아 평균 6.4초였다(재생성 없이 6.1초).
이 턴에 본 호출이 쓰는 것은 받는 말 한 문장뿐이고 다음 질문은 시스템이 붙인다 — 받는 말은 매핑 결과를 기다릴 필요가 없다.
여기서는 받는 말 한 문장을 리더의 직전 답만 보고 쓴다(first_probe_render 와 같은 구조). 매핑과 함께 asyncio.gather 로 돈다.
  넘기는 것     리더의 직전 답 · 코치 말투
  넘기지 않는 것 다음 질문 · 칸 상태 · 코치 프로필 · 영역 정의
실패하거나 문장을 못 쓰면 None — 호출자는 종전처럼 본 호출을 부른다. 매핑이 실패하면 종전과 같이 그 예외를 그대로 올린다.
받는 말은 뒤 단계(허용 목록 8-wa 등)를 그대로 거친다.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re

from diag_project.services.output_guard import is_question, split_sentences

logger = logging.getLogger(__name__)

ANSWER_TAIL_CHARS = 700


def build_close_receive_prompt(*, leader_answer: str, persona_name: str | None) -> str:
    from diag_project.services.persona_register import register_hint
    ans = re.sub(r"\s+", " ", (leader_answer or "").strip())[-ANSWER_TAIL_CHARS:]
    return (
        "당신은 리더십 코치입니다. 리더가 방금 한 말을 한 문장으로 받습니다.\n\n"
        f"[리더가 방금 한 말]\n{ans}\n\n"
        "[규칙]\n- 평서문 한 문장만 쓴다. 물음, 앞으로 무엇을 할지 알리는 말, 평가·짐작은 쓰지 않는다.\n"
        "- 리더가 방금 한 말에서 리더 본인이 한 일 하나를 리더가 쓴 낱말 둘 이상으로 그대로 다시 말한다. 리더가 말하지 않은 사실은 넣지 않는다.\n"
        "- 12어절을 넘기지 않는다.\n"
        "- 끝은 -셨군요, -셨네요, -말씀이군요 가운데 하나로 맺는다.\n"
        "- 높임은 리더에게만 쓴다. 리더가 아닌 사람이 한 행동에는 높임 어미를 붙이지 않는다.\n"
        f"- 말투: {register_hint(persona_name)}\n"
        "\n출력: 평서문 한 문장만."
    )


async def render_close_receive(llm, *, leader_answer: str, persona_name: str | None) -> tuple[str | None, str]:
    """(받는 말 한 문장 | None, 모드). 모드 'llm' | 'stub' | 'miss:<사유>'(no_material·no_llm·error·empty)."""
    if not (leader_answer or "").strip():
        return None, "miss:no_material"
    if os.getenv("FM_LLM_STUB"):
        return None, "stub"
    if llm is None:
        return None, "miss:no_llm"
    try:
        out = await llm._generate_with_retry(prompt=build_close_receive_prompt(leader_answer=leader_answer, persona_name=persona_name),
                                             max_tokens=120, thinking_budget=0, call_type="close_receive_render", temperature=0.4)
    except Exception as e:  # noqa: BLE001
        logger.warning("close receive render failed: %s", e)
        return None, "miss:error"
    text = re.sub(r"\s*\n+\s*", " ", (out or "").strip().strip('"“”'))
    ss = [x.strip() for x in split_sentences(text) if x.strip() and not is_question(x)]
    if not ss:
        return None, "miss:empty"
    return ss[0], "llm"


async def map_and_receive(map_coro, recv_coro) -> tuple[object, str | None, str]:
    """매핑과 받는 말을 동시에 돌린다. 반환 (매핑 결과, 받는 말 | None, 받는 말 모드).
    매핑이 실패하면 종전(차례로 돌 때)과 같이 그 예외를 올린다. 받는 말만 실패하면 None — 호출자가 종전처럼 본 호출을 부른다."""
    res = await asyncio.gather(map_coro, recv_coro, return_exceptions=True)
    if isinstance(res[0], BaseException):
        raise res[0]
    if isinstance(res[1], BaseException):
        logger.warning("close receive task failed: %s", res[1])
        return res[0], None, "miss:error"
    return res[0], res[1][0], res[1][1]
