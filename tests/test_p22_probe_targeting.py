"""(2026-10-22 P2-2) 탐침 겨냥 — A 원장·S-A-R 완비 답변·감정 질문 챕터 1회 (LLM·DB 없음)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.services import traversal as T  # noqa: E402
from diag_project.services.avoidance_detector import has_full_star  # noqa: E402
from diag_project.services.output_guard import is_emotion_question  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_action_probe_ledger_mirrors_result_probe():
    store = {}
    assert not T.action_probed(store, "organization_management")
    store = T.mark_action_probed(store, "organization_management")
    assert T.action_probed(store, "organization_management")
    # 새 타겟으로 전진하면 리셋
    store = {"asked_subs": {}, "current_target": {}, "turns_on_target": {}, "action_probed": {"organization_management": True}}
    store, cur = T.apply_probe_turn(store, "organization_management", ["비전 제시 및 공유", "전략적 사고"], False)
    assert cur == "비전 제시 및 공유" and store["action_probed"]["organization_management"] is False
    assert T.is_action_probe_text("그때 리더님이 직접 하신 일은 무엇이었어요?") and T.is_action_probe_text("어떻게 설득하셨어요?")
    assert not T.is_action_probe_text("그 뒤로 어떻게 됐어요?")


def test_full_star_answer_detection():
    full = ("작년에 교육 체계를 개편하라고 했는데 팀원들이 불평했어요. 그래서 한 명씩 따로 만나서 이유를 설명했고, "
            "두 달 뒤에는 반대하던 팀원도 직접 커리큘럼을 짰습니다. 결과적으로 새 체계로 안정됐어요.")
    assert has_full_star(full)
    assert not has_full_star("팀원들이 불평했어요.")                                   # 짧음
    assert not has_full_star("조직관리는 구성원의 역량을 결집하고 환경을 조성하는 과정이라고 생각합니다. 명확한 방향 제시와 소통이 중요하다고 봅니다.")  # 행동·결과 없음


def test_emotion_question_detection():
    assert is_emotion_question("그때 어떤 마음이 드셨어요?") and is_emotion_question("팀원들 표정은 어땠나요?")
    assert not is_emotion_question("그때 직접 무엇을 하셨어요?") and not is_emotion_question("결과는 어떻게 나왔어요?")


def test_route_wiring():
    src = open(os.path.join(ROOT, "diag_project", "routes", "diagnoses.py"), encoding="utf-8").read()
    assert 'state["force_action_probe"] = _force_a' in src and 'state["sar_complete_answer"] = True' in src
    assert "ACTION_FALLBACK_QUESTION as _AFQ" in src and '_gl_store["emotion_q_count"] = _eqc' in src
    assert "_map_g(_gl_store, chapter)" in src
    l3 = open(os.path.join(ROOT, "diag_project", "prompts", "phase3a", "layer3_state.py"), encoding="utf-8").read()
    assert "[🎯 행동 탐침 — 시스템 계산, 반드시 준수]" in l3
