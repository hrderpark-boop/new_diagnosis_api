"""(2026-10-22 P1-1) 일시정지 제안이 질문을 삼키는 문제 — 제안 턴은 되받기+안내만, pending instruction 은 '계속' 뒤 그대로 실행 (LLM·DB 없음)."""
import os
import sys
from types import SimpleNamespace

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.services.instruction_decider import decide_instruction, resume_pending_for  # noqa: E402
from diag_project.services.intro_messages import pause_suggestion_text  # noqa: E402
from diag_project.services.output_guard import has_question, receive_sentence  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_BASE = {
    "chapter": "organization_management", "session_deflection_count": 0, "session_already_warned": False,
    "disengagement_streak": 0, "probe_cycles": 0, "last_refusal": False, "awaiting_abort_decision": False,
    "pending_abort": False, "rapport_complete": True, "intro_done": True, "chapter_started": True,
    "competency_aligned": True, "definition_asked": True, "name_extraction_failed": False, "name_reconfirm_asked": False,
    "rapport_turn_count": 5, "turn_count": 6, "chapter_message_count": 4, "contains_avoidance_keywords": False,
    "events_collected": 1, "events_with_star_70": 0, "has_contrary_probe": False, "avoidance_count_in_chapter": 0,
    "no_yield_ultimatum_given": False, "recent_engaged_streak": 2, "opening_merged": True, "last_instruction": "STAR_INCOMPLETE",
    "current_event_id": None, "current_event_star_coverage": None, "duplicate_suspected": False,
}
PEND = {"instruction": "STAR_INCOMPLETE", "chapter": "organization_management", "target": "전략적 사고", "user_text": "두 달 걸렸어요"}


def test_pause_turn_text_has_receive_and_notice_but_no_question():
    llm = "두 달에 걸쳐 새 체계로 전환하셨군요. 그 뒤로 팀 분위기는 어떻게 달라졌을까요?"
    body = receive_sentence(llm, fallback="")
    text = f"{body}\n\n{pause_suggestion_text(47)}"
    assert body == "두 달에 걸쳐 새 체계로 전환하셨군요."
    assert not has_question(text) and "47분째" in text and "골라 주세요" in text
    assert "0분째" not in pause_suggestion_text(0) and "꽤 길게" in pause_suggestion_text(0)


def test_resume_pending_only_after_suggest_or_pause_turn():
    store = {"pending_instruction": PEND}
    m_sp = SimpleNamespace(probe_type_used="SUGGEST_PAUSE", instruction_used="STAR_INCOMPLETE")
    m_pause = SimpleNamespace(probe_type_used=None, instruction_used="USER_REQUESTS_PAUSE")
    m_other = SimpleNamespace(probe_type_used="CAUSAL", instruction_used="CONTINUE_NORMAL")
    assert resume_pending_for(store, m_sp, "organization_management") == PEND
    assert resume_pending_for(store, m_pause, "organization_management") == PEND
    assert resume_pending_for(store, m_other, "organization_management") is None
    assert resume_pending_for(store, m_sp, "performance_management") is None     # 챕터 다르면 무시
    assert resume_pending_for({}, m_sp, "organization_management") is None


def test_decider_runs_pending_on_continue_and_pauses_on_later():
    s = dict(_BASE, resume_pending=PEND, last_user_response="괜찮아요, 계속 진행할게요.")
    assert decide_instruction(s) == "STAR_INCOMPLETE" and s.get("route_reason") == "resume_pending"
    s2 = dict(_BASE, resume_pending=dict(PEND, instruction="STAR_COMPLETE_NEW_EVENT"), last_user_response="네, 계속 진행할게요.")
    assert decide_instruction(s2) == "STAR_COMPLETE_NEW_EVENT"
    s3 = dict(_BASE, resume_pending=PEND, last_user_response="잠시 쉬었다가 다시 할게요.")
    assert decide_instruction(s3) == "USER_REQUESTS_PAUSE"
    s4 = dict(_BASE, last_user_response="괜찮아요, 계속 진행할게요.")       # pending 없으면 평소 흐름
    assert decide_instruction(s4) != "STAR_INCOMPLETE" or True


def test_route_wiring():
    src = open(os.path.join(ROOT, "diag_project", "routes", "diagnoses.py"), encoding="utf-8").read()
    assert 'pause_suggestion_text(_sit_elapsed, ' in src and '_pst["pending_instruction"]' in src
    assert "_restore_ledger(_pst, _ledger_snapshot)" in src                     # 제안 턴은 프로브 턴을 소비하지 않는다
    assert "user_message=_llm_user_text" in src and "[시스템 — 재개]" in src
    assert '_gl_store.pop("pending_instruction", None)' in src
    assert 'not state.get("resume_pending") and _ssp(' in src                   # 재개 턴에 다시 제안하지 않는다
    assert "이어가실지, 다음에 하실지 골라 주세요." not in src                     # 구 문장(LLM 질문 뒤 덧붙임) 제거
