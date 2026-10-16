"""§7-1 온보딩 하드 캡 + 정의 질문 불변식 (스크립트, LLM 없음).

- 투머치토커 원판: 라포 71턴·asked 0 — 캡은 라포가 길어지면 곧바로 정의 질문(DIAGNOSIS_CONFIRM)으로 보낸다.
- (2026-10-16 kjpark 사고) 과거 캡은 '라포 5 + 현재 메시지 1 = 6' 에서 COMPETENCY_ALIGN 으로 직행해 정의 질문을
  건너뛰었다. 비교는 rapport_turn_count 만, 목적지는 항상 DIAGNOSIS_CONFIRM.
- 불변식: definition_asked=False 인 챕터에서는 어떤 경로로도 COMPETENCY_ALIGN 이 나올 수 없다.
"""
import itertools
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.services.instruction_decider import decide_instruction  # noqa: E402


def _onboarding_state(rapport_turns: int, turn_count: int = 0, **over) -> dict:
    """라포·인트로 완료·챕터 미시작(온보딩 CONFIRM 단계) 기본 상태."""
    s = {
        "chapter": "organization_management",
        "session_deflection_count": 0, "session_already_warned": False,
        "disengagement_streak": 0, "probe_cycles": 0, "last_refusal": False,
        "awaiting_abort_decision": False, "pending_abort": False,
        "awaiting_continue_decision": False, "awaiting_next_chapter_choice": False,
        "rapport_complete": True, "intro_done": True, "chapter_started": False,
        "competency_aligned": False, "definition_asked": False,
        "name_extraction_failed": False, "name_reconfirm_asked": False,
        "rapport_turn_count": rapport_turns, "turn_count": turn_count,
        "last_user_response": "네",
        "chapter_message_count": 0, "contains_avoidance_keywords": False,
        "events_collected": 0, "events_with_star_70": 0, "has_contrary_probe": False,
        "avoidance_count_in_chapter": 0, "no_yield_ultimatum_given": False,
        "recent_engaged_streak": 0, "opening_merged": False, "last_instruction": None,
    }
    s.update(over)
    return s


def test_confirm_before_cap():
    assert decide_instruction(_onboarding_state(3)) == "DIAGNOSIS_CONFIRM"


def test_normal_onboarding_with_current_message_counted():
    """kjpark 재현: 라포 user 메시지 5 + 현재 메시지(turn_count=1). 과거엔 합 6 → ALIGN 직행."""
    assert decide_instruction(_onboarding_state(5, turn_count=1)) == "DIAGNOSIS_CONFIRM"
    assert decide_instruction(_onboarding_state(4, turn_count=1)) == "DIAGNOSIS_CONFIRM"


def test_cap_destination_is_always_confirm():
    for t in (6, 8, 20, 71):
        ins = decide_instruction(_onboarding_state(t))
        assert ins == "DIAGNOSIS_CONFIRM", f"라포 {t}턴 → {ins}"
        ins = decide_instruction(_onboarding_state(t, turn_count=1))
        assert ins == "DIAGNOSIS_CONFIRM", f"라포 {t}턴+현재 → {ins}"


def test_cap_skips_detours():
    """캡 초과 시 항의·메타 분기보다 정의 질문이 우선(온보딩이 더 길어지지 않음)."""
    ins = decide_instruction(_onboarding_state(71, last_user_response="이게 지금 뭐 하는 건가요? 왜 자꾸 물어보세요"))
    assert ins == "DIAGNOSIS_CONFIRM"


def test_no_infinite_confirm_after_chapter_started():
    """CONFIRM 은 START_CHAPTER 로 태깅돼 다음 턴 chapter_started=True·definition_asked=True → 다시 CONFIRM 이 아니다."""
    ins = decide_instruction(_onboarding_state(71, turn_count=1, chapter_started=True, definition_asked=True,
                                               last_user_response="조직을 효율적으로 관리하는 거요"))
    assert ins == "COMPETENCY_ALIGN"


def test_invariant_no_align_without_definition_asked():
    """불변식: definition_asked=False 인 챕터에서는 어떤 온보딩 상태 조합에서도 COMPETENCY_ALIGN 이 나오지 않는다."""
    texts = ["네", "없어요", "조직을 효율적으로 관리하는 리더의 역량이요. 늘 한정된 자원에서 결과를 내야 하니까요",
             "이게 지금 뭐 하는 건가요?", "잠깐만요"]
    for chapter_started, rapport, tc, intro_done, rapport_complete, txt in itertools.product(
            (False, True), range(0, 9), range(0, 4), (False, True), (False, True), texts):
        s = _onboarding_state(rapport, turn_count=tc, chapter_started=chapter_started,
                              intro_done=intro_done, rapport_complete=rapport_complete, last_user_response=txt)
        ins = decide_instruction(s)
        assert ins != "COMPETENCY_ALIGN", (
            f"definition_asked=False 인데 ALIGN: chapter_started={chapter_started} rapport={rapport} "
            f"turn_count={tc} intro_done={intro_done} rapport_complete={rapport_complete} text={txt!r}")


def test_align_only_after_definition_asked():
    s = _onboarding_state(5, turn_count=1, chapter_started=True, definition_asked=True,
                          last_user_response="조직을 효율적으로 관리하는 거요")
    assert decide_instruction(s) == "COMPETENCY_ALIGN"
    s["definition_asked"] = False
    assert decide_instruction(s) == "COMPETENCY_ASK"
