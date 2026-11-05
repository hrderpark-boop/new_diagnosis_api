"""세션 제어 보조 — 순수 함수 (2026-09-22 결정론, 2026-11-04 BEI 축소).

(2026-11-04 BEI) STAR 슬롯 휴리스틱(plan_event_update)·탐침 종류(probe_type_for)·태도 진술 판정은 삭제됐다. 사례의 슬롯은
services/slot_judge(Haiku) 가, 사례 행(Event)은 routes/diagnoses 가 사례 종료 시 1건씩 쓴다. 여기 남긴 것:
  · is_substantive        리더 발화가 사례 서술로 볼 만한가(짧은 동의·입력 이상 턴 제외) — 린트·재개 판정 보조
  · sitting_stats / should_suggest_pause  일시정지 제안(한 자리 45분 또는 코치 턴 30, 2회 상한, 12턴 쿨다운)
  · 입력 이상 instruction 집합(INPUT_ANOMALY_INSTRUCTIONS) — build_turn_state 의 BEI 턴 집계 제외용
"""
from __future__ import annotations

import re
from datetime import datetime

from diag_project.services.avoidance_detector import detect_absence_statement

SUBSTANTIVE_MIN_CHARS = 12

# 이번 턴 instruction 이 이 집합이면 직전 사용자 발화는 사례 서술이 아니다.
NON_SUBSTANTIVE_INSTRUCTIONS = frozenset({
    "META_QUESTION_FROM_USER", "INVALID_INPUT", "PROMPT_INJECTION_DETECTED", "USER_REQUESTS_PAUSE",
    "AWAIT_NEXT_CHAPTER_CHOICE", "NAME_RECONFIRM",
    "COMPETENCY_ASK", "COMPETENCY_ALIGN", "DIAGNOSIS_INTRO", "DIAGNOSIS_CONFIRM", "RAPPORT_BUILDING",
    "CHAPTER_READY_TO_END",
    "INPUT_REPEATED", "INPUT_DUPLICATE", "QUESTION_RETURNED", "QUESTION_REASK", "CONFIRM_REASK",
    "DEFINITION_REASK", "ANCHOR_REASK",
})
# (2026-10-28 P0-4) 입력 이상 턴 instruction 이름 — 원장·사례·챕터 BEI 카운트 어디에도 전진을 남기지 않는다.
INPUT_ANOMALY_INSTRUCTIONS = frozenset({
    "INPUT_REPEATED", "INPUT_DUPLICATE", "QUESTION_RETURNED", "QUESTION_REASK", "CONFIRM_REASK",
    "DEFINITION_REASK", "ANCHOR_REASK",
})
_CONSENT_RE = re.compile(r"^(네|넵|예|좋습니다|알겠습니다)[,.!\s]*(다음|이어|계속|시작|편하게|말씀)")


def is_substantive(user_text: str | None, instruction_used: str | None) -> bool:
    """사용자 발화가 사례 서술로 볼 만한가."""
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


# ── 일시중지 제안(SUGGEST_PAUSE) — 백엔드 기준 (2026-09-22) ──
SITTING_GAP_MIN = 30          # 이 시간 이상 비면 새 '앉은 자리'
PAUSE_SUGGEST_AFTER_MIN = 45  # 한 자리에서 이만큼 지나면
PAUSE_SUGGEST_AFTER_TURNS = 30  # 또는 코치 턴이 이만큼 쌓이면
PAUSE_SUGGEST_COOLDOWN_TURNS = 12  # 한 번 제안한 뒤 이만큼은 다시 안 함
PAUSE_SUGGEST_MAX = 2         # 2-Strike 유지
# (2026-11-04 BEI) 제안은 사례 탐침 턴에서만 — 여는 턴·SWEEP 앵커 턴(시스템 질문이 붙는 턴)은 제외
PAUSE_SUGGEST_INSTRUCTIONS = frozenset({"EPISODE_PROBE", "EPISODE_RETRY", "SWEEP_FOLLOWUP"})


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
    """사례 탐침 턴에서, 한 자리가 길어졌고(시간 또는 턴), 아직 2회 미만 제안했고, 최근에 제안하지 않았을 때."""
    if instruction_used not in PAUSE_SUGGEST_INSTRUCTIONS:
        return False
    if suggest_pause_count >= PAUSE_SUGGEST_MAX:
        return False
    if turns_since_last_suggest is not None and turns_since_last_suggest < PAUSE_SUGGEST_COOLDOWN_TURNS:
        return False
    coach_turns = sitting_messages // 2
    return elapsed_min >= PAUSE_SUGGEST_AFTER_MIN or coach_turns >= PAUSE_SUGGEST_AFTER_TURNS
