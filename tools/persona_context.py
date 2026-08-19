"""§6(b): 페르소나 컨텍스트 절삭 + 사건 요약 주입 (순수·추적·테스트 가능).

simulate_personas.py 가 이 모듈을 import 해 쓴다. sim 전용(진단 경로 무영향)
이지만, item 3 지표 검증의 '설정 근거'가 되므로 추적·회귀에 포함한다.
('추적 밖 코드'는 role="assistant"·도달 불가 가드처럼 조용히 사는 버그의 온상.)

  · off(n_turns=0): 절삭 없음(전체 히스토리) — 기본값.
  · n_turns>0: 직전 n_turns 턴(코치+사용자 2n 줄)만 유지 + 이미 말한 사건
    요약(events.summary) 주입 → 같은 사건 반복·모순 방지.
"""
from typing import List, Optional


def truncate_history(chat_history: str, n_turns: int) -> str:
    """직전 n_turns 턴(=2*n_turns 줄)만 유지. n_turns<=0 이면 전체."""
    if n_turns <= 0 or not chat_history:
        return chat_history
    lines = chat_history.rstrip("\n").split("\n")
    return "\n".join(lines[-(n_turns * 2):])


def summary_block(known_events: Optional[List[str]]) -> str:
    """이미 말한 사건 요약 블록(수백 토큰). 없으면 빈 문자열."""
    evs = [s for s in (known_events or []) if s]
    if not evs:
        return ""
    bul = "\n".join(f"- {s}" for s in evs)
    return ("\n[이미 말한 사건 요약 — 새 사건을 지어내지 말고, 아래와 "
            "모순되지 않게 답하세요]\n" + bul + "\n")


def assemble_persona_prompt(persona_prompt: str, chat_history: str,
                            ai_question: str, n_turns: int = 0,
                            known_events: Optional[List[str]] = None) -> str:
    """페르소나 응답 생성 프롬프트 조립(절삭+요약 반영).

    n_turns>0 일 때만 절삭·요약 주입. off 면 사건 요약도 붙이지 않는다
    (요약 fetch 자체가 실행되지 않아 오버헤드 0).
    """
    hist = truncate_history(chat_history, n_turns)
    sblock = summary_block(known_events) if n_turns > 0 else ""
    return (
        f"{persona_prompt}\n[이전 대화 맥락]\n{hist}\n"
        f"{sblock}"
        f"[AI 코치의 방금 질문]\n{ai_question}\n"
        "위 질문에 대해 철저히 이 페르소나를 유지한 채 1인칭 한국어로 대답하세요."
    )
