"""사건(STAR) 추적·세션 제어 — 백엔드 결정론 (2026-09-22, LLM 자기보고 JSON 폐기).

이전: LLM 이 매 턴 state JSON(current_event_id·star_coverage·turn_intent·probe_type_used·event_metadata)을
자기보고하고 백엔드가 그대로 믿었다(코드 리뷰 2-d 🟥 #1~#6, 🟨 #8·#9). 오판 → "방금 말한 것을 또 묻는" A 탐침,
출력 토큰 = JSON 필드 10개 + 답변 → 15초 지연.

지금: LLM 출력은 답변 문장뿐. 아래 순수 함수가 (직전 코치 턴의 instruction·문장, 사용자 발화, 이번 턴 instruction)
만으로 사건 생성·슬롯 채움·완결·탐침 종류·일시중지 제안을 결정한다. 근거 추출(레벨 판정)은 deep_analysis 가
대화 원문으로 한다 — 여기의 사건 기록은 흐름 제어(깊이 게이트·반례·전진)와 관리자 표시용.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from diag_project.services.avoidance_detector import detect_absence_statement
from diag_project.services.traversal import is_result_probe_text

# 사용자 발화가 '사건 서술'로 인정되는 최소 길이(공백 제외). 단답('네'·'별거 없어요')은 슬롯을 채우지 않는다.
SUBSTANTIVE_MIN_CHARS = 12

# 이번 턴 instruction 이 이 집합이면 직전 사용자 발화는 사건 서술이 아니다(회피·부재·메타·중복·이탈).
NON_SUBSTANTIVE_INSTRUCTIONS = frozenset({
    "ABSENCE_PROBE", "AVOIDANCE_DETECTED", "META_QUESTION_FROM_USER", "DUPLICATE_CLAIM",
    "CROSS_CHAPTER_REDIRECT", "INVALID_INPUT", "PROMPT_INJECTION_DETECTED", "USER_REQUESTS_PAUSE",
    "AWAIT_NEXT_CHAPTER_CHOICE", "CHAPTER_CONTINUE_CONFIRMED", "NAME_RECONFIRM",
    # 정의·안내·동의 턴의 답(역량 정의, "네, 다음으로 이어가 주세요")은 사건 서술이 아니다 (리플레이 H 에서 situation 오기록)
    "COMPETENCY_ASK", "COMPETENCY_ALIGN", "DIAGNOSIS_INTRO", "DIAGNOSIS_CONFIRM", "RAPPORT_BUILDING",
    "CHAPTER_READY_TO_END", "CHAPTER_OPENING",
})
_CONSENT_RE = re.compile(r"^(네|넵|예|좋습니다|알겠습니다)[,.!\s]*(다음|이어|계속|시작|편하게|말씀)")

# 직전 코치 턴이 이 instruction 이었으면 사용자의 다음 서술은 '새 사건'의 시작이다.
NEW_EVENT_AFTER = frozenset({
    "STAR_COMPLETE_NEW_EVENT", "COMPETENCY_ALIGN", "CHAPTER_OPENING", "ABSENCE_PROBE", "DIAGNOSIS_CONFIRM",
})

_ACTION_PROBE_RE = re.compile(r"(어떻게 하셨|무엇을 하셨|뭘 하셨|어떤 행동|어떤 조치|어떻게 대응|어떻게 접근|어떻게 이끄|어떻게 진행|어떤 방식으로)")
_TASK_PROBE_RE = re.compile(r"(역할|맡으신 일|책임|과제|목표가 무엇|해야 했|해야 할 일)")


def is_substantive(user_text: str | None, instruction_used: str | None) -> bool:
    """사용자 발화가 STAR 슬롯을 채울 '사건 서술'인가."""
    t = (user_text or "").strip()
    if instruction_used in NON_SUBSTANTIVE_INSTRUCTIONS:
        return False
    if len(t.replace(" ", "")) < SUBSTANTIVE_MIN_CHARS:
        return False
    if _CONSENT_RE.match(t):
        return False
    if detect_absence_statement(t):
        return False
    return True


@dataclass
class EventPlan:
    op: str                     # "none" | "new" | "fill"
    slot: str | None = None     # fill 일 때 "situation"|"task"|"action"|"result"
    complete_active: bool = False   # new 일 때 직전 활성 사건을 완결 처리
    complete_after: bool = False    # fill 뒤 활성 사건을 완결 처리(타겟이 이 턴에 전진 — 답은 옛 타겟의 것)


def plan_event_update(
    *,
    user_text: str | None,
    instruction_used: str | None,
    prev_instruction: str | None,
    prev_coach_text: str | None,
    active: dict | None,
    target_changed: bool,
) -> EventPlan:
    """이번 턴의 사건 갱신 계획.

    active: 활성 사건의 슬롯 상태 {"situation": bool, "task": bool, "action": bool, "result": bool} 또는 None.
    target_changed: 이 턴의 원장 전진으로 타겟 하위역량이 바뀌었는가(앵커 턴).
    """
    if not is_substantive(user_text, instruction_used):
        return EventPlan("none")
    if active is None or prev_instruction in NEW_EVENT_AFTER:
        return EventPlan("new", complete_active=active is not None)
    pt = prev_coach_text or ""
    slot = None
    if is_result_probe_text(pt) and not active.get("result"):
        slot = "result"
    elif _TASK_PROBE_RE.search(pt) and not active.get("task"):
        slot = "task"
    elif not active.get("action"):
        slot = "action"
    elif not active.get("result"):
        slot = "result"
    elif not active.get("task"):
        slot = "task"
    if slot is None:
        return EventPlan("none", complete_after=target_changed)
    return EventPlan("fill", slot, complete_after=target_changed)


def probe_type_for(instruction_used: str | None, coach_text: str | None) -> str | None:
    """코치 턴의 탐침 종류 — instruction 과 문장 표지로 결정(LLM 자기보고 대체).
    decider 의 has_contrary(=CONTRARY), result_probed(=MEASUREMENT) 판정이 이 값을 읽는다."""
    if instruction_used == "CONTRARY_NEEDED":
        return "CONTRARY"
    if instruction_used in ("STAR_COMPLETE_NEW_EVENT", "CHAPTER_OPENING", "COMPETENCY_ALIGN", "ABSENCE_PROBE"):
        return "INCIDENT"
    if instruction_used in ("STAR_INCOMPLETE", "CONTINUE_NORMAL", "PROBE_ONLY"):
        if is_result_probe_text(coach_text or ""):
            return "MEASUREMENT"
        if _ACTION_PROBE_RE.search(coach_text or ""):
            return "SPECIFICATION"
        return "CAUSAL"
    if instruction_used == "AVOIDANCE_DETECTED":
        return "AVOIDANCE"
    if instruction_used == "DUPLICATE_CLAIM":
        return "DUPLICATE"
    if instruction_used == "META_QUESTION_FROM_USER":
        return "META"
    return None


# ── 일시중지 제안(SUGGEST_PAUSE) — 백엔드 기준 (2026-09-22) ──
SITTING_GAP_MIN = 30          # 이 시간 이상 비면 새 '앉은 자리'
PAUSE_SUGGEST_AFTER_MIN = 45  # 한 자리에서 이만큼 지나면
PAUSE_SUGGEST_AFTER_TURNS = 30  # 또는 코치 턴이 이만큼 쌓이면
PAUSE_SUGGEST_COOLDOWN_TURNS = 12  # 한 번 제안한 뒤 이만큼은 다시 안 함
PAUSE_SUGGEST_MAX = 2         # 2-Strike 유지


def sitting_stats(timestamps: list[datetime], now: datetime | None = None) -> tuple[float, int]:
    """(이번 자리 경과 분, 이번 자리 메시지 수). 메시지 간격이 SITTING_GAP_MIN 이상이면 자리가 바뀐 것."""
    if not timestamps:
        return 0.0, 0
    ts = sorted(timestamps)
    start = ts[0]
    for a, b in zip(ts, ts[1:]):
        if (b - a).total_seconds() >= SITTING_GAP_MIN * 60:
            start = b
    end = now or ts[-1]
    n = sum(1 for t in ts if t >= start)
    return max(0.0, (end - start).total_seconds() / 60), n


def should_suggest_pause(
    *,
    elapsed_min: float,
    sitting_messages: int,
    suggest_pause_count: int,
    turns_since_last_suggest: int | None,
    instruction_used: str | None,
) -> bool:
    """프로브 턴에서, 한 자리가 길어졌고(시간 또는 턴), 아직 2회 미만 제안했고, 최근에 제안하지 않았을 때."""
    if instruction_used not in ("STAR_INCOMPLETE", "STAR_COMPLETE_NEW_EVENT", "CONTINUE_NORMAL", "CONTRARY_NEEDED"):
        return False
    if suggest_pause_count >= PAUSE_SUGGEST_MAX:
        return False
    if turns_since_last_suggest is not None and turns_since_last_suggest < PAUSE_SUGGEST_COOLDOWN_TURNS:
        return False
    coach_turns = sitting_messages // 2
    return elapsed_min >= PAUSE_SUGGEST_AFTER_MIN or coach_turns >= PAUSE_SUGGEST_AFTER_TURNS
