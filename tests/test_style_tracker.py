"""#6 반복 패턴 제거 — 문체 제약 계산(순수)과 프롬프트 주입, 페르소나 상기.

- "네, ~하셨군요" 시작이 직전 턴에 있었으면 이번 턴 금지.
- 요약 되받기는 3턴에 1번 이하(최근 2턴에 있었으면 금지).
- Layer3 상단에 페르소나 상기 블록과 문체 제약 블록이 실제로 들어간다.
- 6개 코치 페르소나 모두 【말투 프로필】을 갖는다(어느 코치든 같은 톤 방지).
"""
from diag_project.data.coaches_persona import COACHES_PERSONA
from diag_project.prompts.phase3a.layer1_system import build_layer1_with_persona
from diag_project.prompts.phase3a.layer3_state import format_turn_state_for_llm
from diag_project.services.style_tracker import (
    compute_style_constraints, format_style_constraints, is_recap_opening,
    starts_with_ne_recap,
)

NE = "네, 팀원들이 스스로 노력해서 교육 효과를 높였다는 말씀이시군요. 그때 어떻게 하셨어요?"
RECAP = "팀원 스스로 할 수 있는 부분과 조직 지원이 필요한 부분을 나누도록 안내하셨군요. 결과는요?"
PLAIN = "그 반발은 어떻게 뚫고 나가셨어요?"
SHORT = "아, 그 장면요. 그때 누가 먼저 움직였어요?"


def test_pattern_detectors():
    assert starts_with_ne_recap(NE)
    assert starts_with_ne_recap(RECAP)          # 첫 문장이 '~군요'로 끝남
    assert not starts_with_ne_recap(PLAIN)
    assert not starts_with_ne_recap(SHORT)
    assert is_recap_opening(NE) and is_recap_opening(RECAP)
    assert not is_recap_opening(PLAIN)


def test_forbid_ne_when_previous_turn_started_with_ne():
    sc = compute_style_constraints([NE, PLAIN, PLAIN])   # 최신 순
    assert sc["forbid_ne_opening"] is True
    sc2 = compute_style_constraints([PLAIN, NE, NE])
    assert sc2["forbid_ne_opening"] is False


def test_recap_at_most_once_per_three_turns():
    assert compute_style_constraints([RECAP, PLAIN])["forbid_recap"] is True
    assert compute_style_constraints([PLAIN, RECAP])["forbid_recap"] is True
    assert compute_style_constraints([PLAIN, PLAIN, RECAP])["forbid_recap"] is False
    assert compute_style_constraints([])["forbid_recap"] is False


def test_format_empty_when_no_constraints():
    assert format_style_constraints(compute_style_constraints([PLAIN, SHORT])) == ""
    assert format_style_constraints(None) == ""


def _state(**kw):
    base = {
        "chapter": "organization_management",
        "instruction_for_this_turn": "CONTINUE_NORMAL",
        "turn_count": 5, "events_collected": 1, "events_with_star_70": 0,
        "current_event_id": None, "current_event_star_coverage": None,
        "has_contrary_probe": False, "avoidance_count_in_chapter": 0,
        "all_subcompetencies": [], "explored_subcompetencies": [],
        "unexplored_subcompetencies": [], "asked_in_chapter": [],
    }
    base.update(kw)
    return base


def test_layer3_includes_persona_and_style_blocks():
    txt = format_turn_state_for_llm(_state(
        coach_persona={"name": "Jessica (제시카)", "coaching_style": "구조적",
                       "tags": "#냉철함"},
        style_constraints=compute_style_constraints([NE, RECAP]),
    ))
    assert "[🎭 페르소나 유지] 당신은 Jessica (제시카)" in txt
    assert "[🎛 이번 턴 문체 제약" in txt
    assert "그 시작 금지" in txt and "요약 되받기 금지" in txt
    # 블록은 Turn State 보다 앞에 온다
    assert txt.index("🎭") < txt.index("[Turn State]")


def test_layer3_without_persona_or_constraints_unchanged_shape():
    txt = format_turn_state_for_llm(_state())
    assert "🎭" not in txt and "🎛" not in txt
    assert txt.lstrip().startswith("[Turn State]")


def test_all_personas_have_speech_profile():
    for k, p in COACHES_PERSONA.items():
        assert "【말투 프로필】" in p["system_prompt"], k
        sp = build_layer1_with_persona(k, user_name="김리더")
        assert "【말투 프로필】" in sp and "어느 코치든 같은 톤이 나오면 실패" in sp
