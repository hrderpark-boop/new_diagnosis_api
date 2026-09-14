"""2026-09-14 대화 품질 3건 — 회귀 테스트(LLM·DB 없음).

1) 요약 되받기 판정 확장: '네' 없는 '~하셨습니다' 평서문·사용자 명사구 복창도 되받기로
   센다(3턴 1회 이하). 금지 턴 안내는 페르소나별(Ella 공감 / Jessica 관찰·통찰).
2) 앵커 전환 전 결과(R) 탐침 강제: 현재 타겟의 마지막 프로브 턴(turns==3)에 R 을
   안 물었으면 needs_result_probe=True. 3턴 상한은 그대로. 새 타겟에서 리셋.
3) 중복 지적('이 질문 아까 한 것 같은데요') → 항의로 감지되어 META_QUESTION_FROM_USER,
   Layer3 에 '인정 + 무엇을 다르게 보려는지 한 줄' 블록이 들어간다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.services import traversal as T  # noqa: E402
from diag_project.services.style_tracker import (  # noqa: E402
    compute_style_constraints, echoes_user, format_style_constraints,
    is_recap_opening, is_recap_turn,
)
from diag_project.services.instruction_decider import (  # noqa: E402
    detect_duplicate_claim, detect_user_objection,
)

USER = "팀원들과 회의를 통해서 수집한 자료를 분석하기 시작했죠"
# kjpark 세션 T13 — '네' 없이 평서문으로 사용자 어절을 그대로 복창한 되받기
JESSICA_PLAIN = "회의를 통해 자료를 분석하셨습니다. 그 분석의 구체적인 기준은 무엇이었습니까?"
JESSICA_ECHO = "팀원에게 기안을 올리도록 지시하셨습니다. 그 기안이 제출된 후, 어떤 논의가 진행되었습니까?"
USER_ECHO = "팀원이 교육체계 전반을 최신화 하겠다고 의견을 냈어요. 그래서 기안을 올리라고 했죠"
INSIGHT = "그 판단이 쉽지 않으셨겠네요. 그 자리에서 리더님은 무엇을 먼저 하셨습니까?"
PLAIN_Q = "그 분석의 구체적인 기준은 무엇이었습니까?"


# ── 1) 되받기 판정 확장 ──
def test_plain_statement_recap_is_detected():
    assert is_recap_opening(JESSICA_PLAIN)        # '~하셨습니다.' 평서문 요약
    assert not is_recap_opening(INSIGHT)          # 해석 한 줄은 되받기 아님
    assert not is_recap_opening(PLAIN_Q)          # 바로 질문


def test_noun_phrase_echo_counts_as_recap():
    assert echoes_user(JESSICA_ECHO, USER_ECHO)   # '팀원' 은 불용어지만 '기안' + '올리' 복창
    assert is_recap_turn(JESSICA_PLAIN, USER)
    assert not echoes_user(INSIGHT, USER)
    assert not echoes_user(PLAIN_Q, USER)         # 질문문은 복창으로 보지 않음


def test_recap_limited_to_once_per_three_turns_with_user_context():
    sc = compute_style_constraints([JESSICA_PLAIN, INSIGHT], [USER, USER])
    assert sc["forbid_recap"] is True
    sc2 = compute_style_constraints([INSIGHT, PLAIN_Q], [USER, USER])
    assert sc2["forbid_recap"] is False
    # 구형 호출(사용자 발화 없이)도 그대로 동작
    assert compute_style_constraints([JESSICA_PLAIN])["forbid_recap"] is True


def test_persona_specific_hint_in_constraint_text():
    sc = {"forbid_recap": True, "forbid_ne_opening": False}
    j = format_style_constraints(sc, "Jessica (제시카)")
    e = format_style_constraints(sc, "Ella (엘라)")
    assert "관찰·통찰" in j and "쉽지 않으셨겠네요" in j
    assert "감정 한 줄" in e
    assert "복창" in j and "평서문" in j and "요약 되받기 금지" in j


# ── 2) 결과(R) 탐침 강제 ──
ALL = ["비전 제시 및 공유", "전략적 사고", "변화관리(변화지향)", "혁신적 사고"]
CH = "organization_management"


def test_result_probe_forced_on_last_turn_only():
    st, cur = T.apply_probe_turn({}, CH, ALL, event_done=False)     # 앵커 turns=1
    assert cur == ALL[0] and not T.needs_result_probe(st, CH)
    st, _ = T.apply_probe_turn(st, CH, ALL, event_done=False)        # turns=2
    assert not T.needs_result_probe(st, CH)
    st, _ = T.apply_probe_turn(st, CH, ALL, event_done=False)        # turns=3 (마지막)
    assert T.needs_result_probe(st, CH)                              # R 안 물었으면 강제
    st = T.mark_result_probed(st, CH)
    assert not T.needs_result_probe(st, CH)                          # 물었으면 해제
    st, cur2 = T.apply_probe_turn(st, CH, ALL, event_done=False)     # 3턴 상한 → 전진(유지)
    assert cur2 == ALL[1] and st["turns_on_target"][CH] == 1
    assert st["result_probed"][CH] is False                          # 새 타겟에서 리셋


def test_result_probe_text_markers():
    assert T.is_result_probe_text("그 설명 이후, 팀원들의 인식이나 태도에 어떤 변화가 있었습니까?")
    assert T.is_result_probe_text("잘 안되었다는 결과는 어떤 지표나 구체적인 상황으로 확인하셨습니까?")
    assert T.is_result_probe_text("그래서 그 일은 어떻게 됐나요?")
    assert T.is_result_probe_text("그 경험에서 무엇을 배우셨나요?")
    assert not T.is_result_probe_text("그때 팀원들에게 어떤 설명을 해주셨습니까?")
    assert not T.is_result_probe_text("그 분석의 구체적인 기준은 무엇이었습니까?")


def test_ledger_snapshot_includes_result_probed():
    assert "result_probed" in T.LEDGER_KEYS
    st = T.mark_result_probed({}, CH)
    snap = T.snapshot_ledger(st)
    assert snap["result_probed"] == {CH: True}
    assert T.restore_ledger({"result_probed": {CH: False}}, snap)["result_probed"] == {CH: True}


# ── 3) 중복 지적 ──
def test_duplicate_claim_detected_as_objection():
    for t in ["이 질문은 아까 한것 같은데요", "이 질문은 아까 한 것 같은데요",
              "같은 질문 아닌가요?", "아까 물어보셨잖아요", "이미 대답한 것 같은데"]:
        assert detect_duplicate_claim(t), t
        assert detect_user_objection(t), t
    assert not detect_duplicate_claim("팀원들과 회의를 통해서 자료를 분석했죠")


def test_layer3_has_duplicate_block_and_force_block():
    from diag_project.prompts.phase3a.layer3_state import format_turn_state_for_llm
    base = {
        "chapter": CH, "turn_count": 5, "events_collected": 1, "events_with_star_70": 0,
        "current_event_id": None, "current_event_star_coverage": None,
        "has_contrary_probe": False, "avoidance_count_in_chapter": 0,
        "all_subcompetencies": ALL, "explored_subcompetencies": [],
        "unexplored_subcompetencies": [], "asked_in_chapter": [],
        "instruction_for_this_turn": "META_QUESTION_FROM_USER",
        "last_user_response": "이 질문은 아까 한것 같은데요", "current_target_name": "변화관리(변화지향)",
        "coach_persona": {"name": "Jessica (제시카)", "coaching_style": "구조적", "tags": "#냉철함"},
    }
    txt = format_turn_state_for_llm(base)
    assert "중복 지적 대응" in txt and "변화관리(변화지향)" in txt
    assert "유사한 질문이었습니다" in txt         # 금지 예시가 명시됨
    forced = dict(base, instruction_for_this_turn="STAR_INCOMPLETE",
                  last_user_response="정보가 없으니 할 수 있는 것부터 하자고 했죠",
                  force_result_probe=True, current_target_name="전략적 사고")
    txt2 = format_turn_state_for_llm(forced)
    assert "결과 탐침 강제" in txt2 and "전략적 사고" in txt2 and "중복 지적 대응" not in txt2
    plain = dict(forced, force_result_probe=False)
    assert "결과 탐침 강제" not in format_turn_state_for_llm(plain)
