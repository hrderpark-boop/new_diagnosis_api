"""(2026-10-21) flash 판정 — 코치 턴 품질을 위한 짧은 YES/NO LLM 호출.

호출 계층은 llm_service.GeminiService._generate_with_retry 를 그대로 쓴다(세션 provider 에 따라 gemini flash / claude haiku).
판정은 보조 신호다: 실패·모호(None)면 호출자는 원문을 그대로 쓴다. FM_LLM_STUB 가 켜져 있으면 호출하지 않는다(None).
"""
from __future__ import annotations

import logging
import os
from typing import Iterable

logger = logging.getLogger(__name__)


async def judge_yes_no(llm, question: str, *, call_type: str = "judge") -> bool | None:
    """question 끝에 'YES/NO 한 단어' 를 요구해 True/False 로. 실패·모호는 None."""
    if os.getenv("FM_LLM_STUB"):
        return None
    prompt = f"{question.strip()}\n\n답은 YES 또는 NO 한 단어만 출력하세요."
    try:
        out = await llm._generate_with_retry(
            prompt=prompt, max_tokens=8, thinking_budget=0, call_type=call_type, temperature=0.0,
        )
    except Exception as e:  # noqa: BLE001 — 판정 실패는 원문 유지
        logger.warning("flash 판정 실패(%s): %s", call_type, e)
        return None
    t = (out or "").strip().upper()
    if t.startswith("YES"):
        return True
    if t.startswith("NO"):
        return False
    return None


async def same_question_as_recent(llm, new_q: str, prev_qs: Iterable[str]) -> bool | None:
    """탐침 질문이 직전 질문들과 '같은 것'을 묻는가(표현이 달라도 의미가 같으면 YES)."""
    prev = [q.strip() for q in prev_qs if q and q.strip()]
    if not new_q.strip() or not prev:
        return False
    listed = "\n".join(f"- {q}" for q in prev)
    return await judge_yes_no(
        llm,
        "아래는 리더십 코칭 대화에서 코치가 직전에 던진 질문들과 이번에 던지려는 질문입니다.\n"
        "이번 질문이 직전 질문 중 하나와 '같은 것'을 묻고 있습니까? 표현·어순이 달라도 묻는 대상·시점·행동이 같으면 YES, "
        "다른 장면·다른 행동·다른 결과를 묻거나 한 걸음 더 들어가는 질문이면 NO.\n\n"
        f"[직전 질문들]\n{listed}\n\n[이번 질문]\n{new_q.strip()}",
        call_type="judge_same_q",
    )


async def volunteered_subcompetency(llm, answer: str, candidates: dict) -> str | None:
    """(2026-10-22 P2-0) 리더가 앵커 질문 없이 말한 사례가 아직 안 다룬 하위역량(candidates: 이름→앵커 설명) 중 하나를
    분명히 다루면 그 이름, 아니면 None. 모호하면 None(기록하지 않는다)."""
    if os.getenv("FM_LLM_STUB") or not candidates or not (answer or "").strip():
        return None
    listed = "\n".join(f"- {n}: {d}" for n, d in candidates.items())
    prompt = ("아래 리더의 답변이 다음 하위역량 중 하나의 '구체 사례'(리더가 실제로 한 행동)를 분명히 담고 있으면 그 하위역량 이름을 "
              "목록의 표기 그대로 한 줄로 출력하세요. 둘 이상에 걸치거나 분명하지 않으면 NONE 만 출력하세요.\n\n"
              f"[하위역량 후보]\n{listed}\n\n[리더 답변]\n{answer.strip()[:1200]}")
    try:
        out = await llm._generate_with_retry(prompt=prompt, max_tokens=30, thinking_budget=0,
                                             call_type="judge_volunteered", temperature=0.0)
    except Exception as e:  # noqa: BLE001
        logger.warning("자발적 사례 판정 실패: %s", e)
        return None
    name = (out or "").strip().splitlines()[0].strip().strip("'\"-·* ") if out else ""
    if not name or name.upper().startswith("NONE"):
        return None
    for n in candidates:
        if n == name or n.replace(" ", "") == name.replace(" ", "") or name in n:
            return n
    return None


async def must_ask_covered(llm, question: str, must_ask: Iterable[str]) -> bool | None:
    """렌더링한 앵커 질문이 must_ask 조건(대상·상황·행동·시점 키워드)을 전부 담았는가."""
    keys = [k for k in must_ask if k]
    if not question.strip() or not keys:
        return None
    return await judge_yes_no(
        llm,
        "아래 질문은 리더에게 과거의 구체적 경험 하나를 묻는 질문입니다. 질문이 다음 조건을 '전부' 담고 있습니까? "
        "조건의 낱말이 그대로 들어가지 않아도 뜻이 분명히 들어 있으면 담긴 것으로 봅니다. 하나라도 빠지면 NO.\n\n"
        f"[조건]\n" + "\n".join(f"- {k}" for k in keys) + f"\n\n[질문]\n{question.strip()}",
        call_type="judge_must_ask",
    )


async def ladder_already_answered(llm, answer: str, ladder_question: str) -> bool | None:
    """(2026-10-29 P1) 사다리 질문이 묻는 행동이 직전 리더 답에 이미 서술돼 있는가 — Haiku 1콜. 실패·스텁이면 None(호출자는 '없음'으로 처리)."""
    if os.getenv("FM_LLM_STUB") or not (answer or "").strip() or not (ladder_question or "").strip():
        return None
    return await judge_yes_no(
        llm,
        "아래 [질문]은 리더가 어떤 행동을 한 적이 있는지 묻습니다. [리더 답변]에 그 행동이 실제로 한 일로 이미 서술돼 있으면 YES, "
        "없거나 다짐·계획·일반론뿐이면 NO. 낱말이 같지 않아도 뜻이 같으면 YES.\n\n"
        f"[질문]\n{ladder_question.strip()}\n\n[리더 답변]\n{answer.strip()[:1500]}",
        call_type="judge_ladder_dup",
    )


async def judge_rubric_level(llm, competency_key: str, sub_name: str, answer: str) -> int | None:
    """(2026-10-23 P3 사다리) 리더 답변이 하위역량 루브릭(Lv.1~4 서술+예시) 중 어느 레벨까지 실제로 도달했는지 1~4 한 숫자.
    대화 중 다음 사다리 질문(현재 레벨 +1)을 고르기 위한 보조 신호다. 실패·모호·스텁이면 None(호출자는 Lv.2 기준으로 폴백)."""
    if os.getenv("FM_LLM_STUB") or not (answer or "").strip():
        return None
    from diag_project.services.level_gate import level_reference
    ref = level_reference(competency_key, sub_name)
    if not ref:
        return None
    ref_txt = "\n".join(f"Lv.{lv}: {ref.get(lv, '')}" for lv in (1, 2, 3, 4))
    prompt = ("아래 리더 답변이 레벨 서술 중 어느 레벨의 행동까지 실제로 담고 있는지 판정하세요. 서술의 핵심 행동이 답변에 "
              "실제로 있을 때만 그 레벨입니다(일부 결락이면 한 단계 아래). 구체 사례가 아니면 1.\n\n"
              f"[레벨 서술]\n{ref_txt}\n\n[리더 답변]\n{answer.strip()[:1500]}\n\n답은 1, 2, 3, 4 중 숫자 하나만 출력하세요.")
    try:
        out = await llm._generate_with_retry(prompt=prompt, max_tokens=4, thinking_budget=0,
                                             call_type="judge_level", temperature=0.0)
    except Exception as e:  # noqa: BLE001
        logger.warning("레벨 판정 실패: %s", e)
        return None
    t = (out or "").strip()
    for ch in t[:3]:
        if ch in "1234":
            return int(ch)
    return None
