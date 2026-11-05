"""(2026-10-21) flash 판정 — 짧은 YES/NO LLM 호출. (2026-11-04 BEI) 의미 반복·자발적 사례·사다리·레벨 판정은 삭제 — 남은 것은 앵커 LLM 렌더(ANCHOR_RENDER=llm) 의 must_ask 판정뿐.

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

