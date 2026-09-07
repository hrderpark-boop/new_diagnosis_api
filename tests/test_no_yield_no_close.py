"""1-c(2026-09-07): 무수확(no-yield)은 챕터를 종료하지 못한다.

원칙: events_with_star_70 은 대화 흐름 제어용 신호(LLM 사건 추적)이고 실제 근거는
세션 후 deep_analysis 가 다시 읽는다. 추적이 실패해도 잘못 종료되면 안 된다.
- 종료 경로는 넓이 충족 / 예산 소진 / 이탈(abort) 셋뿐. 넓이·예산 종료도
  '미탐색 하위역량 없음 + 마지막 타겟 1회 심화' 를 요구한다.
- 무수확 최후통첩은 탐침으로 유지하되, 최근 답변 2개가 실질적이면 발동하지 않는다.
"""
from diag_project.services.instruction_decider import decide_instruction

CH = "organization_management"
SUBS = ["비전 제시 및 공유", "전략적 사고", "변화관리(변화지향)", "혁신적 사고"]
LONG = "지난달에 팀원들과 새 교육 체계를 놓고 직접 설득했고 결국 운영 방식을 바꿨습니다."


def _state(asked, turn_count, turns_on_target, **kw):
    base = {
        "chapter": CH, "turn_count": turn_count, "chapter_message_count": turn_count,
        "session_deflection_count": 0, "session_already_warned": False,
        "disengagement_streak": 0, "probe_cycles": turn_count, "last_refusal": False,
        "awaiting_abort_decision": False, "pending_abort": False,
        "awaiting_continue_decision": False,
        "rapport_complete": True, "intro_done": True, "chapter_started": True,
        "competency_aligned": True, "definition_asked": True,
        "name_extraction_failed": False, "name_reconfirm_asked": False,
        "rapport_turn_count": 0, "opening_merged": True,
        "last_user_response": LONG, "contains_avoidance_keywords": False,
        # STAR 추적 실패 시나리오: 강한 사건 0
        "events_with_star_70": 0, "events_collected": 1,
        "avoidance_count_in_chapter": 0, "no_yield_ultimatum_given": False,
        "has_contrary_probe": True, "duplicate_suspected": False,
        "all_subcompetencies": SUBS, "asked_in_chapter": SUBS[:asked],
        "explored_subcompetencies": SUBS[:asked],
        "unexplored_subcompetencies": SUBS[asked:],
        "current_event_id": None, "current_event_star_coverage": None,
        "turns_on_current_target": turns_on_target,
        "recent_engaged_streak": 3,
    }
    base.update(kw)
    return base


PROBES = {"CONTINUE_NORMAL", "STAR_INCOMPLETE", "STAR_COMPLETE_NEW_EVENT",
          "CONTRARY_NEEDED", "ABSENCE_PROBE"}


def test_engaged_leader_reaches_fourth_anchor_despite_star_zero():
    # 3/4 asked, 성실 답변 연속, STAR 0, 5턴 이상 → 최후통첩도 종료도 아님 → 계속 탐침
    for turn in (5, 7, 9, 12, 13, 14):
        ins = decide_instruction(_state(asked=3, turn_count=turn, turns_on_target=3))
        assert ins in PROBES, (turn, ins)
    # 4/4 asked + 마지막 타겟 심화 1회 → 이제 닫힌다
    assert decide_instruction(_state(asked=4, turn_count=14, turns_on_target=2)) \
        == "CHAPTER_READY_TO_END"
    # 4/4 asked 이지만 심화 전 → 아직
    assert decide_instruction(_state(asked=4, turn_count=13, turns_on_target=1)) \
        in PROBES


def test_no_yield_flag_and_ultimatum_cannot_close():
    s = _state(asked=3, turn_count=9, turns_on_target=3,
               no_yield_ultimatum_given=True, no_yield_forced=True,
               avoidance_count_in_chapter=3)
    ins = decide_instruction(s)
    assert ins != "CHAPTER_READY_TO_END", ins
    assert ins != "CHAPTER_NO_YIELD_ULTIMATUM"


def test_ultimatum_suppressed_for_engaged_streak_but_kept_as_probe():
    # 실질 답변 연속 2 이상 → 최후통첩 미발동
    assert decide_instruction(_state(asked=2, turn_count=6, turns_on_target=2,
                                     recent_engaged_streak=2)) \
        != "CHAPTER_NO_YIELD_ULTIMATUM"
    # 실질 답변이 이어지지 않으면(짧은 답 반복) 탐침으로 1회 발동
    assert decide_instruction(_state(asked=2, turn_count=6, turns_on_target=2,
                                     recent_engaged_streak=0,
                                     last_user_response="네 그랬던 것 같아요")) \
        == "CHAPTER_NO_YIELD_ULTIMATUM"


def test_budget_does_not_close_while_unexplored_remain():
    # 조직관리 cap=13. 13턴이어도 미탐색이 남으면 계속, 전부 탐색+심화면 닫힘
    assert decide_instruction(_state(asked=2, turn_count=13, turns_on_target=3)) \
        in PROBES
    assert decide_instruction(_state(asked=4, turn_count=13, turns_on_target=2)) \
        == "CHAPTER_READY_TO_END"


def test_avoider_goes_to_abort_logic():
    # 명시적 거부 → 즉시 ABORT_CONFIRM
    assert decide_instruction(_state(asked=1, turn_count=3, turns_on_target=1,
                                     last_refusal=True, recent_engaged_streak=0)) \
        == "ABORT_CONFIRM"
    # 연속 이탈 3회 & 5사이클 이상 → ABORT_CONFIRM
    assert decide_instruction(_state(asked=2, turn_count=6, turns_on_target=2,
                                     disengagement_streak=3, probe_cycles=6,
                                     recent_engaged_streak=0,
                                     last_user_response="네")) \
        == "ABORT_CONFIRM"


def test_max_turns_backstop_still_ends():
    assert decide_instruction(_state(asked=2, turn_count=40, turns_on_target=1)) \
        == "MAX_TURNS_REACHED"
