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


def test_no_yield_close_uses_neutral_wording():
    g = L3._get_instruction_guide("CHAPTER_READY_TO_END", _state(True))
    assert "충분히 들었" in g
    assert "무수확 강제 전환" not in g and "Fail-Fast" not in g
    assert "'성과관리'로" in g
    # 판정 문구는 '금지' 목록 안에만 등장한다
    forbid_idx = g.index("판정 문구 절대 금지")
    assert all(m.start() > forbid_idx for m in _JUDGE.finditer(g))


def test_normal_close_unchanged_shape():
    g = L3._get_instruction_guide("CHAPTER_READY_TO_END", _state(False))
    assert "Wrap-up" in g and not _JUDGE.search(g)


# ── #2 ──
def test_align_turn_records_target_and_appends_anchor():
    src = inspect.getsource(D._submit_message_phase3a)
    # ALIGN 이 프로브 스텝(LLM 이전 asked 기록) 대상에 포함
    i_probe = src.index("_PROBE_INSTR = {")
    j_probe = src.index("}", i_probe)
    assert '"COMPETENCY_ALIGN"' in src[i_probe:j_probe]
    # 8-b 에서 앵커를 덧붙이고 opening_merged 표식을 남긴다
    i = src.index('if instruction_used == "COMPETENCY_ALIGN" and not _suppress_mechanical_text:')
    j = src.index("_next_ch = _get_next_chapter(chapter)", i)
    block = src[i:j]
    assert "build_chapter_opening_with_user_def(" in block
    assert '"opening_merged"' in block
    # 프로브 스텝(기록)이 LLM 호출·8-b 조립보다 앞에 있다
    assert src.index("apply_probe_turn(") < src.index("generate_phase3a_interaction(") < i


def test_decider_skips_chapter_opening_when_merged():
    base = {
        "chapter": "organization_management", "turn_count": 1,
        "session_deflection_count": 0, "session_already_warned": False,
        "disengagement_streak": 0, "probe_cycles": 1, "last_refusal": False,
        "awaiting_abort_decision": False, "pending_abort": False,
        "awaiting_continue_decision": False,
        "rapport_complete": True, "intro_done": True, "chapter_started": True,
        "competency_aligned": True, "definition_asked": True,
        "chapter_message_count": 0,
        "name_extraction_failed": False, "name_reconfirm_asked": False,
        "rapport_turn_count": 0,
        "last_user_response": "지난달에 팀원들과 새 교육 체계를 놓고 직접 설득했어요.",
        "contains_avoidance_keywords": False,
        "events_with_star_70": 0, "avoidance_count_in_chapter": 0,
        "no_yield_ultimatum_given": False, "has_contrary_probe": False,
        "duplicate_suspected": False, "asked_in_chapter": ["비전 제시 및 공유"],
        "all_subcompetencies": ["a", "b", "c", "d"],
        "unexplored_subcompetencies": ["b", "c", "d"], "events_collected": 0,
        "current_event_id": None, "current_event_star_coverage": None,
        "turns_on_current_target": 1,
    }
    assert decide_instruction({**base, "opening_merged": False}) == "CHAPTER_OPENING"
    ins = decide_instruction({**base, "opening_merged": True})
    assert ins != "CHAPTER_OPENING", ins


def test_align_guide_forbids_confirmation_question():
    g = L3._get_instruction_guide("COMPETENCY_ALIGN", _state(False))
    assert "확인 질문 없이 끝내기" in g
    assert "탐색 전환 예고" not in g
