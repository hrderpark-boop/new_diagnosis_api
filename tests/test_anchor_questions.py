"""#2 앵커 질문 사전(52개) 기준 고정 + LLM 턴 앵커 가이드에 질문 주입.

기준(HR 확정): 26×2, 역량명·하위역량명 없음, 시점(최근/근래/요즘) 포함,
물음표 하나(이중 질문 금지), 어미 3종 혼합 + 한 챕터 안에서 같은 어미 3연속 금지.
situation 사전은 그대로(분석·게이트 무변경 호환층).
"""
import re

from diag_project.data.competencies import (
    COMPETENCY_FRAMEWORK, SUBCOMPETENCY_ANCHORS, SUBCOMPETENCY_ANCHOR_QUESTIONS,
    SUBCOMPETENCY_ANCHOR_SETS, find_sub_key_by_name, get_anchor_questions,
)
from diag_project.prompts.phase3a import layer3_state as L3

CHAPTERS = [k for k in COMPETENCY_FRAMEWORK if k != "supplementary"]
ALL_NAMES = [
    v["name"] for ck in CHAPTERS
    for v in COMPETENCY_FRAMEWORK[ck]["indicators"].values()
] + [COMPETENCY_FRAMEWORK[ck]["name"] for ck in CHAPTERS]
_TIME = re.compile(r"최근|근래|요즘")


def _ending(q: str) -> str:
    if q.endswith("그때 어떻게 하셨어요?"):
        return "B"
    if q.endswith("있었다면 어떤 일이었어요?"):
        return "C"
    return "A"


def test_52_questions_cover_all_subs():
    total = 0
    for ck in CHAPTERS:
        for key in COMPETENCY_FRAMEWORK[ck]["indicators"]:
            qs = get_anchor_questions(key)
            assert len(qs) == 2, key
            total += len(qs)
    assert total == 52


def test_question_criteria():
    for key, qs in SUBCOMPETENCY_ANCHOR_QUESTIONS.items():
        for q in qs:
            assert q.count("?") == 1, (key, q)          # 이중 질문 금지
            assert _TIME.search(q), (key, q)            # 시점
            for nm in ALL_NAMES:                        # 역량명·하위역량명 없음
                core = nm.split("(")[0].strip()
                assert core not in q, (key, q, core)


def test_ending_mix_and_no_three_in_a_row():
    bc_total = 0
    for ck in CHAPTERS:
        seq = []
        for key in COMPETENCY_FRAMEWORK[ck]["indicators"]:
            seq += [_ending(q) for q in get_anchor_questions(key)]
        bc_total += sum(1 for e in seq if e != "A")
        for i in range(len(seq) - 2):
            assert not (seq[i] == seq[i + 1] == seq[i + 2]), (ck, seq)
    assert 52 * 0.25 <= bc_total <= 52 * 0.45, bc_total   # 약 1/3


def test_situation_dictionary_unchanged_shape():
    """호환층: 분석·게이트가 읽는 situation 리스트는 그대로."""
    for key, sits in SUBCOMPETENCY_ANCHORS.items():
        assert isinstance(sits, list) and len(sits) == 2
        assert all(s.endswith(("상황", "순간")) for s in sits), key
        assert SUBCOMPETENCY_ANCHOR_SETS[key]["situation"] == sits
        assert SUBCOMPETENCY_ANCHOR_SETS[key]["question"] == get_anchor_questions(key)


def test_find_sub_key_by_name():
    assert find_sub_key_by_name("organization_management", "전략적 사고") == "strategic_thinking"
    assert find_sub_key_by_name("organization_management", "없는 이름") is None


def test_llm_turn_guide_injects_target_questions_and_forbids_name():
    state = {
        "chapter": "organization_management",
        "instruction_for_this_turn": "STAR_COMPLETE_NEW_EVENT",
        "turn_count": 4, "events_collected": 1, "events_with_star_70": 1,
        "current_event_id": None, "current_event_star_coverage": None,
        "has_contrary_probe": False, "avoidance_count_in_chapter": 0,
        "all_subcompetencies": ["비전 제시 및 공유", "전략적 사고",
                                "변화관리(변화지향)", "혁신적 사고"],
        "explored_subcompetencies": ["비전 제시 및 공유"],
        "unexplored_subcompetencies": ["전략적 사고", "변화관리(변화지향)",
                                       "혁신적 사고"],
        "asked_in_chapter": ["비전 제시 및 공유", "전략적 사고"],
        "current_target_sub": "전략적 사고",
    }
    guide = L3._get_instruction_guide("STAR_COMPLETE_NEW_EVENT", state)
    for q in get_anchor_questions("strategic_thinking"):
        assert q in guide
    assert "이름 노출 금지" in guide
    assert "한 번 언급" not in guide          # 과거 '이름 언급해도 좋다' 삭제
