"""#5: 마지막 하위역량도 최소 1회 심화 후 챕터 종료.

로그: 혁신적 사고 앵커 → "만족도 조사 문항 바꾸라고 했어요" 한 문장 → 즉시 종료.
넓이(4/4) 충족 직후 탈출구 A/B 가 챕터를 닫았다. 현재 타겟에서 앵커(1턴) 뒤
후속 질문이 1회 이상 나간 뒤(turns_on_current_target ≥ 2)에만 닫는다.
서킷브레이커(턴 상한)는 예외.
"""
from diag_project.services.instruction_decider import decide_instruction

CH = "organization_management"
SUBS = ["비전 제시 및 공유", "전략적 사고", "변화관리(변화지향)", "혁신적 사고"]


def _state(turns_on_target, **kw):
    base = {
        "chapter": CH, "turn_count": 10, "chapter_message_count": 10,
        "session_deflection_count": 0, "session_already_warned": False,
        "disengagement_streak": 0, "probe_cycles": 0, "last_refusal": False,
        "awaiting_abort_decision": False, "pending_abort": False,
        "awaiting_continue_decision": False,
        "rapport_complete": True, "intro_done": True, "chapter_started": True,
        "competency_aligned": True, "definition_asked": True,
        "name_extraction_failed": False, "name_reconfirm_asked": False,
        "rapport_turn_count": 0,
        "last_user_response": "만족도 조사 문항을 바꾸라고 했어요.",
        "contains_avoidance_keywords": False,
        "events_with_star_70": 1, "avoidance_count_in_chapter": 0,
        # 반례 탐침은 이미 수행됨(안 그러면 #10 CONTRARY_NEEDED 가 종료보다 먼저)
        "no_yield_ultimatum_given": False, "has_contrary_probe": True,
        "duplicate_suspected": False,
        # 넓이 충족: 4/4 전부 asked, 미탐색 없음
        "all_subcompetencies": SUBS, "asked_in_chapter": list(SUBS),
        "explored_subcompetencies": list(SUBS), "unexplored_subcompetencies": [],
        "events_collected": 4,
        "current_event_id": None, "current_event_star_coverage": None,
        "turns_on_current_target": turns_on_target,
    }
    base.update(kw)
    return base


def test_exit_b_waits_for_one_followup():
    # 앵커 직후(턴 1) → 아직 닫지 않고 후속 질문
    ins = decide_instruction(_state(1))
    assert ins != "CHAPTER_READY_TO_END", ins
    assert ins in ("CONTINUE_NORMAL", "STAR_INCOMPLETE", "CONTRARY_NEEDED"), ins
    # 후속 1회 뒤(턴 2) → 종료 허용
    assert decide_instruction(_state(2)) == "CHAPTER_READY_TO_END"


def test_exit_a_complete_event_waits_for_one_followup():
    cov = {"S": True, "T": True, "A": True, "R": True}
    ins = decide_instruction(_state(1, current_event_id="e1",
                                    current_event_star_coverage=cov))
    assert ins == "CONTINUE_NORMAL", ins
    ins2 = decide_instruction(_state(2, current_event_id="e1",
                                     current_event_star_coverage=cov))
    assert ins2 == "CHAPTER_READY_TO_END", ins2


def test_circuit_breaker_ignores_followup_gate():
    # 조직관리 cap = 3*3+4 = 13 → 상한이면 심화 여부와 무관하게 닫는다.
    ins = decide_instruction(_state(1, turn_count=13, chapter_message_count=13))
    assert ins == "CHAPTER_READY_TO_END", ins


def test_legacy_state_without_key_unchanged():
    s = _state(1)
    s.pop("turns_on_current_target")
    assert decide_instruction(s) == "CHAPTER_READY_TO_END"
