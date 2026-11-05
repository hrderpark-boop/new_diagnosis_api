"""(2026-10-22 P2-0) 회피·종료 판정 — 서술 있으면 회피 아님 · 종료 요청(넓이 충족/미충족) · 자발적 사례 asked · 수치 질문 범위 (LLM·DB 없음)."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.services import output_guard as G  # noqa: E402
from diag_project.services.avoidance_detector import check_avoidance, detect_closing_intent, has_narrative  # noqa: E402
from diag_project.services.instruction_decider import decide_instruction  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P1_INPUT = "원인은 모르겠는데 시간은 없던 문제는, 신규 과정 신청률이 갑자기 떨어졌을 때였어요. 일단 수강생 10명에게 전화로 물어봐서 공지 채널 문제인 걸 찾았죠."




def test_closing_phrases_detected():
    for t in ("네, 그 정도면 성과관리는 충분히 말씀드린 것 같아요.", "이 정도면 될 것 같아요", "다음으로 넘어가죠", "이제 끝내죠"):
        assert detect_closing_intent(t) == "explicit", t
    assert detect_closing_intent("다음으로 넘어가서 설명했어요. 팀원들이 이해했고요.") is None
    assert detect_closing_intent("감사합니다") == "soft"


_BASE = {
    "chapter": "performance_management", "session_deflection_count": 0, "session_already_warned": False,
    "disengagement_streak": 0, "probe_cycles": 0, "last_refusal": False, "awaiting_abort_decision": False,
    "pending_abort": False, "rapport_complete": True, "intro_done": True, "chapter_started": True,
    "competency_aligned": True, "definition_asked": True, "name_extraction_failed": False, "name_reconfirm_asked": False,
    "rapport_turn_count": 5, "turn_count": 8, "chapter_message_count": 6, "contains_avoidance_keywords": False,
    "events_collected": 2, "events_with_star_70": 1, "has_contrary_probe": False, "avoidance_count_in_chapter": 0,
    "no_yield_ultimatum_given": False, "recent_engaged_streak": 2, "opening_merged": True, "last_instruction": "STAR_INCOMPLETE",
    "current_event_id": None, "current_event_star_coverage": None, "duplicate_suspected": False, "one_more_asked": False,
}








