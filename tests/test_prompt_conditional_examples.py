"""(2026-10-16) 가이드 예시 오독 방지 — 인용 대상이 실제로 있을 때만 인용 지시·예시를 넣는다(LLM·DB 없음).

kjpark 세션: 리더가 '네'만 답한 ALIGN 턴에 예시의 '효과적'이, 기대 답변이 '없어요'였던 INTRO 턴에 예시의
'객관적으로 파악하고 싶으신 마음'이 리더의 말처럼 출력됐다.
"""
import os
import sys
from datetime import datetime, timedelta
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.prompts.phase3a import layer3_state as L  # noqa: E402
from diag_project.services.instruction_decider import extract_expectation_answer  # noqa: E402

_BASE = {
    "chapter": "organization_management", "turn_count": 1, "events_collected": 0, "events_with_star_70": 0,
    "current_event_id": None, "current_event_star_coverage": None, "has_contrary_probe": False,
    "avoidance_count_in_chapter": 0, "first_subcompetency_name": "비전 제시 및 공유",
    "participant_context": {"role_summary": "저는 교육팀장이고 팀원은 5명 정도 되요"},
    "coach_persona": {"name": "Ella"},
    "all_subcompetencies": ["비전 제시 및 공유", "전략적 사고", "변화관리(변화지향)", "혁신적 사고"],
}


def _guide(instr: str, **over) -> str:
    return L._get_instruction_guide(instr, dict(_BASE, instruction_for_this_turn=instr, **over))


# ── 판정 함수 ──
def test_predicates():
    assert not L.leader_definition_present("네")
    assert not L.leader_definition_present("네 좋아요")
    assert not L.leader_definition_present("없어요")
    assert not L.leader_definition_present("잘 모르겠어요")
    assert L.leader_definition_present("사람이요")
    assert L.leader_definition_present("조직을 효율적으로 관리하는 거요")
    assert not L.expectation_usable(None)
    assert not L.expectation_usable("없어요")
    assert not L.expectation_usable("별로 기대하고 오지 않았어요")
    assert not L.expectation_usable("특별히 기대하는 것은 없어요")
    assert not L.expectation_usable("네")
    assert L.expectation_usable("저의 리더십 역량을 파악하고 싶어요")
    assert L.expectation_usable("강점과 약점을 알고 싶어요")


# ── ALIGN ──
def test_align_without_definition_has_no_quote_instruction_or_quote_examples():
    g = _guide("COMPETENCY_ALIGN", last_user_response="네")
    assert "효과적으로 관리한다고 하셨는데" not in g   # 예시 인용문이 통째로 빠진다
    assert "'효과적'이라는 말씀" not in g
    assert "[인용 금지 — 최우선]" in g
    assert "받는 문장은 리더님이 실제로 쓴 단어" not in g
    assert "말씀하신 것과 크게 다르지 않죠" not in g
    # (2026-10-28 P0-1) 정의·목록·안내·다리는 시스템이 붙인다 — 프롬프트에 목록 서식이 없다
    assert "· (하위역량 1)" not in g and "하위역량 목록" in g


def test_align_with_definition_keeps_quote_instruction_and_labels_examples():
    g = _guide("COMPETENCY_ALIGN", last_user_response="조직을 효율적으로 관리하는 거요")
    assert "받는 문장은 리더님이 실제로 쓴 단어·구절을" in g
    assert "[인용 금지 — 최우선]" not in g
    # (2026-10-28 P0-1) 다른 챕터 예시('조직을 효과적으로…')는 일관리 ALIGN 에 그대로 유입됐다 — 예시 자체를 뺐다
    assert "효과적으로 관리한다고 하셨는데" not in g


# ── INTRO ──
def test_intro_without_expectation_is_system_only_no_consolation():
    for exp in (None, "없어요", "별로 기대하고 오지 않았어요"):
        g = _guide("DIAGNOSIS_INTRO", last_user_response="네", expectation_answer=exp)
        assert "시스템 안내만" in g and "LLM 호출 없음" in g, exp
        assert "객관적으로 파악하고 싶으신" not in g and "강점과 약점을 균형 있게" not in g, exp
        assert "괜찮" not in g and "자연스러워요" not in g, exp        # 위로 문장 제거


def test_intro_with_expectation_receives_one_sentence_only():
    g = _guide("DIAGNOSIS_INTRO", last_user_response="네", expectation_answer="저의 리더십 역량을 파악하고 싶어요")
    assert "실제로 하신 답**: '저의 리더십 역량을 파악하고 싶어요'" in g
    assert "받는 문장 하나" in g and "두 문장 이상" in g
    assert "다시 뵙게 되어" in g                       # 재방문 인사 금지 명시
    assert "괜찮습니다' 류" in g                       # 위로 금지
    assert g.count(L.EXAMPLE_LABEL) >= 1


# ── CROSS_CHAPTER ──
def test_cross_chapter_quote_only_with_signals():
    g0 = _guide("CROSS_CHAPTER_OPPORTUNITY", last_user_response="네", cross_chapter_signals=None)
    assert "인용 없이" in g0 and "아까 X 말씀하셨는데" not in g0
    g1 = _guide("CROSS_CHAPTER_OPPORTUNITY", last_user_response="네", cross_chapter_signals=["팀원과 부딪혔다"])
    assert "실제 말" in g1


# ── 기대 답변 추출 (라포 순서: ROLE_ASK → user(담당) → model(기대 질문) → user(기대 답)) ──
def _m(i, role, content, probe=None):
    return SimpleNamespace(role=role, content=content, probe_type_used=probe, turn_index=None,
                           created_at=datetime(2026, 10, 16, 16, 0, 0) + timedelta(seconds=i))


def test_extract_expectation_answer_kjpark_sequence():
    msgs = [_m(0, "model", "인사"), _m(1, "user", "안녕하세요 박기진 입니다."), _m(2, "model", "오후 어떻게"),
            _m(3, "user", "금요일이라 일이 잘 안되네요"), _m(4, "model", "어떤 일을 맡고", "ROLE_ASK"),
            _m(5, "user", "교육팀장, 5명"), _m(6, "model", "기대하시는 게 있으세요?"),
            _m(7, "user", "없어요"), _m(8, "model", "넘어가도 될까요?", "READY_FOR_INTRO"), _m(9, "user", "네")]
    assert extract_expectation_answer(msgs) == "없어요"
    # 기대 턴에서 바로 READY_FOR_INTRO 가 나와 기대 답이 INTRO 를 촉발하는 경우(10/15 Olivia 세션)
    assert extract_expectation_answer(msgs[:8]) == "없어요"
    # 마커 없음 → None (가이드가 paraphrase 생략)
    assert extract_expectation_answer([m for m in msgs if m.probe_type_used != "ROLE_ASK"]) is None
    assert extract_expectation_answer(msgs[:6]) is None
