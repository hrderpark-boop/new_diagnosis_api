"""사건 추적·탐침 종류·일시중지 제안 — 백엔드 결정론 (2026-09-22, LLM 자기보고 폐기)."""
from datetime import datetime, timedelta

from diag_project.services.event_tracker import (
    is_substantive, plan_event_update, probe_type_for, should_suggest_pause, sitting_stats,
)

NARR = "성향이 다른 두 팀원의 갈등 상황에서 각각의 입장을 경청한 뒤 한자리에 모아 관점 차이를 이해하도록 유도했습니다."


def test_substantive_rejects_short_absence_and_non_substantive_instructions():
    assert is_substantive(NARR, "STAR_INCOMPLETE")
    assert not is_substantive("네", "STAR_INCOMPLETE")
    assert not is_substantive("별거 없어요", "ABSENCE_PROBE")
    assert not is_substantive("그런 경험은 없었는데요", "STAR_INCOMPLETE")
    assert not is_substantive(NARR, "META_QUESTION_FROM_USER")


def test_new_event_after_anchor_or_when_none_active():
    p = plan_event_update(user_text=NARR, instruction_used="STAR_INCOMPLETE", prev_instruction="STAR_COMPLETE_NEW_EVENT",
                          prev_coach_text="최근에 그런 일이 있으셨습니까?", active={"situation": True}, target_changed=False)
    assert p.op == "new" and p.complete_active
    p2 = plan_event_update(user_text=NARR, instruction_used="STAR_INCOMPLETE", prev_instruction="ABSENCE_PROBE",
                           prev_coach_text="", active=None, target_changed=False)
    assert p2.op == "new" and not p2.complete_active


def test_fill_slot_follows_previous_coach_question():
    act = {"situation": True, "task": False, "action": False, "result": False}
    p = plan_event_update(user_text=NARR, instruction_used="STAR_INCOMPLETE", prev_instruction="STAR_INCOMPLETE",
                          prev_coach_text="그 뒤로 달라진 게 있었습니까?", active=act, target_changed=False)
    assert p.op == "fill" and p.slot == "result"
    p2 = plan_event_update(user_text=NARR, instruction_used="STAR_INCOMPLETE", prev_instruction="STAR_INCOMPLETE",
                           prev_coach_text="그때 어떻게 하셨습니까?", active=act, target_changed=False)
    assert p2.op == "fill" and p2.slot == "action"
    p3 = plan_event_update(user_text=NARR, instruction_used="STAR_COMPLETE_NEW_EVENT", prev_instruction="STAR_INCOMPLETE",
                           prev_coach_text="그때 어떻게 하셨습니까?", active=act, target_changed=True)
    assert p3.op == "fill" and p3.complete_after   # 앵커 턴: 답은 옛 타겟의 것 → 채우고 완결


def test_probe_type_from_instruction_and_text():
    assert probe_type_for("CONTRARY_NEEDED", "예상과 달리 흘러간 적은 없으셨습니까?") == "CONTRARY"
    assert probe_type_for("STAR_INCOMPLETE", "그 뒤로 달라진 게 있었습니까?") == "MEASUREMENT"
    assert probe_type_for("STAR_INCOMPLETE", "그때 구체적으로 어떻게 하셨습니까?") == "SPECIFICATION"
    assert probe_type_for("STAR_COMPLETE_NEW_EVENT", "최근에 그런 일이 있으셨습니까?") == "INCIDENT"
    assert probe_type_for("RAPPORT_BUILDING", "안녕하세요") is None


def test_sitting_stats_and_pause_rule():
    t0 = datetime(2026, 9, 22, 14, 0)
    ts = [t0 + timedelta(minutes=i) for i in range(10)] + [t0 + timedelta(minutes=60 + i) for i in range(20)]
    el, n = sitting_stats(ts, now=t0 + timedelta(minutes=80))
    assert n == 20 and 19.9 <= el <= 20.1
    assert not should_suggest_pause(elapsed_min=20, sitting_messages=20, suggest_pause_count=0, turns_since_last_suggest=None, instruction_used="STAR_INCOMPLETE")
    assert should_suggest_pause(elapsed_min=46, sitting_messages=20, suggest_pause_count=0, turns_since_last_suggest=None, instruction_used="STAR_INCOMPLETE")
    assert should_suggest_pause(elapsed_min=10, sitting_messages=62, suggest_pause_count=1, turns_since_last_suggest=20, instruction_used="CONTINUE_NORMAL")
    assert not should_suggest_pause(elapsed_min=90, sitting_messages=80, suggest_pause_count=2, turns_since_last_suggest=None, instruction_used="STAR_INCOMPLETE")
    assert not should_suggest_pause(elapsed_min=90, sitting_messages=80, suggest_pause_count=0, turns_since_last_suggest=3, instruction_used="STAR_INCOMPLETE")
    assert not should_suggest_pause(elapsed_min=90, sitting_messages=80, suggest_pause_count=0, turns_since_last_suggest=None, instruction_used="RAPPORT_BUILDING")
