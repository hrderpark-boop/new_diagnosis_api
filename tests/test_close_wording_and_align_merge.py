"""2026-09-07 조직관리 재주행 후속.

1-a: 부재 진술("최근에 없었는데요")·사건 재언급은 회피(AVOIDANCE_DETECTED/카운터)가
     아니다. 길이 규칙 제거 — 필러만 있는 단답("네")만 회피.
1-b: 종료 문구는 종료 사유와 분리 — 무수확(no_yield_forced) 종료도 '충분히 들었다'
     계열 중립 문구. "유의미한 진단이 어렵다" 류 판정 문구는 가이드에서 사라진다.
#2 : 정의 제시(COMPETENCY_ALIGN) + 첫 앵커를 한 메시지로 — asked 는 LLM 이전 기록,
     다음 턴 decider 는 CHAPTER_OPENING 을 다시 내지 않는다(opening_merged).
"""
import inspect
import re

from diag_project.prompts.phase3a import layer3_state as L3
from diag_project.routes import diagnoses as D
from diag_project.services.avoidance_detector import (
    check_avoidance, detect_absence_statement, is_unproductive_response,
)
from diag_project.services.instruction_decider import decide_instruction

_JUDGE = re.compile(r"유의미한 진단이 어려|진단을 이어가기 어려|진단이 어렵")


# ── 1-a ──
def test_absence_and_remention_are_not_avoidance():
    for t in ["최근에 없었는데요", "없었습니다", "마찬가지에요 앞서 얘기한게",
              "마찬가지에요 앞서 얘기한게 당장 올해 어떻게 하겠다보다 내년의 변화를 위해서 시도한거죠"]:
        assert check_avoidance(t) is False, t
        assert is_unproductive_response(t) is False, t


def test_short_negative_is_absence_statement():
    assert detect_absence_statement("최근에 없었는데요") is True
    assert detect_absence_statement("딱히 없었습니다") is True
    # 긴 서술 속 '없었어요'는 사건 설명 — 부재 진술 아님
    assert detect_absence_statement(
        "팀원들 반발은 없었어요. 오히려 먼저 나서서 기획서를 다시 써 왔고 "
        "그 뒤로 운영 방식이 바뀌었습니다") is False


def test_filler_only_is_still_avoidance():
    for t in ["네", "글쎄요", "음 그냥 뭐", ""]:
        assert check_avoidance(t) is True, t


# ── 1-b ──
def _state(no_yield):
    return {
        "chapter": "organization_management",
        "instruction_for_this_turn": "CHAPTER_READY_TO_END",
        "turn_count": 9, "events_collected": 1, "events_with_star_70": 0,
        "current_event_id": None, "current_event_star_coverage": None,
        "has_contrary_probe": False, "avoidance_count_in_chapter": 0,
        "all_subcompetencies": [], "explored_subcompetencies": [],
        "unexplored_subcompetencies": [], "asked_in_chapter": ["a", "b", "c"],
        "no_yield_forced": no_yield,
    }



def test_normal_close_unchanged_shape():
    g = L3._get_instruction_guide("CHAPTER_READY_TO_END", _state(False))
    assert "Wrap-up" in g and not _JUDGE.search(g)


# ── #2 ──




def test_align_guide_forbids_confirmation_question():
    g = L3._get_instruction_guide("COMPETENCY_ALIGN", _state(False))
    # (2026-10-28 P0-1) ALIGN 은 백엔드 결정론 조립 — LLM 은 되받기만. 다리·목록·질문은 시스템이 붙인다.
    assert "질문은 전부 시스템이 뒤에 붙이므로" in g and "동의를 구하는 확인 질문" in g and "크게 다르지 않죠" not in g
    assert "탐색 전환 예고" not in g and "크게 다르지 않죠?처럼" not in g
