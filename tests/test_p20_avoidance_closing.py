"""(2026-10-22 P2-0) 회피·종료 판정 — 서술 있으면 회피 아님 · 종료 요청(넓이 충족/미충족) · 자발적 사례 asked · 수치 질문 범위 (LLM·DB 없음)."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.services import output_guard as G  # noqa: E402
from diag_project.services.avoidance_detector import check_avoidance, detect_closing_intent, has_narrative  # noqa: E402
from diag_project.services.instruction_decider import decide_instruction  # noqa: E402
from diag_project.services.llm_judge import volunteered_subcompetency  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P1_INPUT = "원인은 모르겠는데 시간은 없던 문제는, 신규 과정 신청률이 갑자기 떨어졌을 때였어요. 일단 수강생 10명에게 전화로 물어봐서 공지 채널 문제인 걸 찾았죠."


def test_avoidance_not_flagged_when_narrative_present():
    assert has_narrative(P1_INPUT)
    assert not check_avoidance(P1_INPUT)                       # 10/22 재생에서 AVOIDANCE_DETECTED 였던 발화
    assert check_avoidance("모르겠어요")                          # 단독 회피는 그대로
    assert check_avoidance("글쎄요, 기억 안 나요")
    assert not check_avoidance("잘 모르겠지만 그때는 팀원을 따로 불러서 이유를 물었고 바로 바꿨어요.")   # 과거형 2개
    assert not has_narrative("모르겠어요") and not has_narrative("아니요, 됐어요")


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


def test_closing_request_routes_by_breadth():
    # 성과관리 MIN_EXPLORED=3. asked 3 → 넓이 충족 → 요약 + 다음 챕터
    s = dict(_BASE, asked_in_chapter=["a", "b", "c"], last_user_response="네, 그 정도면 성과관리는 충분히 말씀드린 것 같아요.")
    assert decide_instruction(s) == "CHAPTER_READY_TO_END"
    # asked 1 → 미충족 → 하나만 더 (1회)
    s2 = dict(_BASE, asked_in_chapter=["a"], last_user_response="이 정도면 될 것 같아요")
    assert decide_instruction(s2) == "CHAPTER_ONE_MORE_ASK"
    # 이미 한 번 물었으면 → 종료(해당 하위역량 미탐색)
    s3 = dict(s2, one_more_asked=True)
    assert decide_instruction(s3) == "CHAPTER_READY_TO_END"
    # '하나만 더' 뒤 짧은 거절 → 종료, 서술로 답하면 평소 흐름
    s4 = dict(_BASE, asked_in_chapter=["a"], last_instruction="CHAPTER_ONE_MORE_ASK", one_more_asked=True, last_user_response="아니요, 괜찮아요.")
    assert decide_instruction(s4) == "CHAPTER_READY_TO_END"
    s5 = dict(s4, last_user_response="작년에 목표를 못 맞춘 팀원이 있어서 분기마다 따로 면담했고, 두 번째 분기부터는 본인이 계획을 세웠어요.")
    assert decide_instruction(s5) not in ("CHAPTER_READY_TO_END", "CHAPTER_ONE_MORE_ASK")


def test_quantify_scope():
    assert G.needs_quantify_probe("불필요한 회의 시간이 획기적으로 줄고 핵심 사안에만 집중할 수 있었어요.")      # 시간
    assert G.needs_quantify_probe("비용이 대폭 줄었어요.")
    assert not G.needs_quantify_probe("팀원들은 조급한 압박감이 훨씬 줄어 긍정적인 반응을 보였습니다.")         # 반응
    assert not G.needs_quantify_probe("회의 분위기가 훨씬 밝아졌어요.")                                       # 분위기
    assert not G.needs_quantify_probe("회의 시간이 30% 줄었어요.")                                             # 숫자 있음
    assert not G.needs_quantify_probe("훨씬 좋아졌어요.")                                                      # 대상 없음


def test_volunteered_judge_parsing():
    class _LLM:
        def __init__(self, out): self.out = out
        async def _generate_with_retry(self, prompt, **kw): return self.out
    cands = {"문제해결": "원인 모르는 문제를 직접 풀었던 상황", "실행력": "계획대로 안 풀리는 일을 끝까지 밀어붙인 상황"}
    assert asyncio.run(volunteered_subcompetency(_LLM("문제해결"), P1_INPUT, cands)) == "문제해결"
    assert asyncio.run(volunteered_subcompetency(_LLM("NONE"), P1_INPUT, cands)) is None
    assert asyncio.run(volunteered_subcompetency(_LLM("없음"), P1_INPUT, cands)) is None
    assert asyncio.run(volunteered_subcompetency(_LLM("문제해결"), P1_INPUT, {})) is None


def test_route_wiring():
    src = open(os.path.join(ROOT, "diag_project", "routes", "diagnoses.py"), encoding="utf-8").read()
    assert "volunteered_subcompetency as _vol" in src and "_rec_v(_store, chapter, _vsub)" in src
    assert "# 8-m." in src and "하나만 더 여쭤봐도 될까요?" in src and 'probe_type_used = "ONE_MORE_ASK"' in src
    assert '"volunteered": _tm.get("volunteered")' in src
