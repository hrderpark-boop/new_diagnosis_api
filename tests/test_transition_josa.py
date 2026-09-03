"""#1 전환 멘트: 예고에서 끝나고(질문 없음) 챕터명 뒤 조사가 받침에 맞는다.

로그 재현: "이제 다음 역량인 '성과관리'에 대해 … 현실에서 '성과관리'을 챙긴다는
건 참 쉽지 않죠. … 포인트는 뭐예요?" — 전환 예고 뒤에 시스템이
build_chapter_thought_question 을 덧붙였고(조사 오류 포함), 정의 질문이 두 번
나가는 순서 어긋남을 만들었다.
"""
import inspect
import re

import pytest

from diag_project.services.korean import get_josa, with_josa
from diag_project.data.competencies import COMPETENCY_FRAMEWORK
from diag_project.prompts.phase3a import layer3_state as L3
from diag_project.routes import diagnoses as D
from diag_project.services import intro_messages as IM

CHAPTERS = [k for k in COMPETENCY_FRAMEWORK if k != "supplementary"]
_BAD_JOSA = re.compile(r"관리'?(을|은|이|과|으로)(?=[\s,.'?)])")


def test_get_josa_basic():
    assert get_josa("성과관리", "을/를") == "를"
    assert get_josa("성과관리", "은/는") == "는"
    assert get_josa("성과관리", "으로/로") == "로"
    assert get_josa("직원", "을/를") == "을"
    assert get_josa("서울", "으로/로") == "로"     # ㄹ받침 특례
    assert get_josa("사람", "으로/로") == "으로"
    assert get_josa("'성과관리'", "을/를") == "를"  # 따옴표 감싼 단어


def test_with_josa_quote():
    assert with_josa("성과관리", "을/를", quote=True) == "'성과관리'를"
    assert with_josa("전략적 사고", "이/가") == "전략적 사고가"


def test_thought_question_pool_removed():
    assert not hasattr(IM, "build_chapter_thought_question")
    src = inspect.getsource(D)
    assert "build_chapter_thought_question" not in src.replace("# ", "")\
        .split("(제거됨)")[0] or "build_chapter_thought_question(" not in src


def test_ready_to_end_branch_appends_no_question():
    """8-d: 전환 예고 뒤에 시스템이 질문을 덧붙이는 코드가 없다."""
    src = inspect.getsource(D._submit_message_phase3a)
    i = src.index('if instruction_used == "CHAPTER_READY_TO_END":')
    j = src.index('if instruction_used == "CHAPTER_CONTINUE_CONFIRMED":')
    block = src[i:j]
    assert '"?" not in' not in block
    assert "thought_question" not in block.replace("build_chapter_thought_question 을", "")


@pytest.mark.parametrize("chapter", CHAPTERS)
def test_guides_have_no_particle_errors(chapter):
    """정의 질문·확인·전환 가이드 예시 문장에 '성과관리을' 류 조사 오류 없음."""
    state = {
        "chapter": chapter, "instruction_for_this_turn": "COMPETENCY_ASK",
        "turn_count": 0, "events_collected": 0, "events_with_star_70": 0,
        "current_event_id": None, "current_event_star_coverage": None,
        "has_contrary_probe": False, "avoidance_count_in_chapter": 0,
        "all_subcompetencies": [], "explored_subcompetencies": [],
        "unexplored_subcompetencies": [], "asked_in_chapter": [],
    }
    for instr in ("COMPETENCY_ASK", "COMPETENCY_ALIGN", "DIAGNOSIS_CONFIRM",
                  "CHAPTER_READY_TO_END", "COMPETENCY_INTRO"):
        guide = L3._get_instruction_guide(instr, state)
        bad = _BAD_JOSA.findall(guide)
        assert not bad, (instr, chapter, _BAD_JOSA.search(guide).group(0))


def test_ready_to_end_guide_ends_with_announcement_only():
    state = {
        "chapter": "organization_management",
        "instruction_for_this_turn": "CHAPTER_READY_TO_END",
        "turn_count": 10, "events_collected": 2, "events_with_star_70": 1,
        "current_event_id": None, "current_event_star_coverage": None,
        "has_contrary_probe": False, "avoidance_count_in_chapter": 0,
        "all_subcompetencies": [], "explored_subcompetencies": [],
        "unexplored_subcompetencies": [], "asked_in_chapter": [],
    }
    guide = L3._get_instruction_guide("CHAPTER_READY_TO_END", state)
    assert "'성과관리'로" in guide or "성과관리로" in guide
    assert "질문 금지" in guide or "질문을 던지지" in guide
