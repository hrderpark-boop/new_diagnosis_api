"""(2026-10-19) 라포 2·3턴: LLM 은 되받기 한 문장만, 질문은 백엔드 고정 문장. 기대 답변 → 바로 INTRO(LLM·DB 없음).

2026-10-16: 2턴이 템플릿이라 "금요일이라 일이 잘 안되네요" 를 받을 수 없었다 → light LLM 호출로.
2026-10-19: LLM 이 질문까지 쓰면 '오늘' 같은 단어가 새고 길어진다 → LLM 은 되받기 1문장, 질문은 백엔드가 붙인다.
            기대 질문 뒤 '진단_대화' 턴 삭제 — 기대 답변 다음 턴이 바로 DIAGNOSIS_INTRO.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.prompts.phase3a import layer3_state as L  # noqa: E402
from diag_project.prompts.phase3a.layer1_system import (  # noqa: E402
    LAYER1_LIGHT, LAYER1_LISTEN_LITE, LAYER1_SYSTEM_PROMPT, build_layer1_with_persona,
)
from diag_project.services.instruction_decider import _force_rapport_category, decide_instruction  # noqa: E402
from diag_project.services.intro_messages import RAPPORT_EXPECTATION_QUESTION, RAPPORT_ROLE_QUESTION  # noqa: E402
from diag_project.services.output_guard import echoes_user, receive_sentence  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _rapport_guide(category: str, last: str) -> str:
    state = {"instruction_for_this_turn": "RAPPORT_BUILDING", "forced_rapport_category": category,
             "current_hour_text": "오후 4시", "current_time_tone": "활기찬 오후", "last_user_response": last}
    return L._get_instruction_guide("RAPPORT_BUILDING", state)


def test_categories_no_diagnosis_chat_turn():
    assert _force_rapport_category(0) == "일상"
    assert _force_rapport_category(1) == "스몰톡"      # (2026-10-21) 스몰톡 받기 턴
    assert _force_rapport_category(2) == "담당업무"
    assert _force_rapport_category(3) == "기대"
    assert _force_rapport_category(4) == "기대"       # 진단_대화 삭제
    assert "진단_대화" not in open(os.path.join(ROOT, "diag_project", "prompts", "phase3a", "layer3_state.py"),
                                  encoding="utf-8").read().split("category_guides = {")[1]


def test_fixed_questions():
    assert "오늘" not in RAPPORT_ROLE_QUESTION                 # 담당 업무는 오늘 일과가 아니다
    assert RAPPORT_ROLE_QUESTION.startswith("평소 어떤 일을 맡고 계신지")
    assert RAPPORT_ROLE_QUESTION.endswith("팀 규모나 주로 하시는 업무 정도면 됩니다.")
    assert RAPPORT_EXPECTATION_QUESTION.endswith("?")


def test_receive_only_guides():
    for cat in ("담당업무", "기대"):
        g = _rapport_guide(cat, "그럭저럭 지내고 있어요")
        assert ("받는 문장 하나" in g or "반응 한 문장" in g) and "시스템이 뒤에 붙이므로" in g
        assert "그대로 반복하지 않는다" in g and "추측을 보태지 않는다" in g
        assert "(반복)" in g and "(추측)" in g                 # 금지 예 둘 다(입력과 겹치지 않는 문장)
        assert "그럭저럭" not in g                            # 2026-10-19: 금지 예가 입력과 겹쳐 복사됐던 문장 제거
        assert "[READY_FOR_INTRO] 를 반드시 포함" not in g
        assert "어떤 일을 맡고 계신지 간단히" not in g      # 질문 문장은 LLM 가이드에 없다(백엔드가 붙임)
        assert "공감 표현 — 매우 중요" not in g             # 공감·예시 블록 제거
        assert L.EXAMPLE_LABEL in g


def test_receive_sentence_drops_questions_and_caps_one():
    assert receive_sentence("금요일이라 일이 잘 안 풀리는 날이죠. 어떤 일을 맡고 계세요?") == "금요일이라 일이 잘 안 풀리는 날이죠."
    assert receive_sentence("팀원 다섯 분과 함께하시는군요. 챙기실 게 많겠어요. 기대하시는 게 있으세요?") == "팀원 다섯 분과 함께하시는군요."
    assert receive_sentence("어떤 일을 맡고 계세요?") == "그러셨군요."
    assert receive_sentence("", fallback="") == ""


def test_echo_guard_detects_verbatim_repeat():
    assert echoes_user("그럭저럭 지내고 계시는군요.", "그럭저럭 지내고 있어요")          # 명사구+서술부
    assert not echoes_user("네, 오늘 하루도 평소처럼 업무를 보고 계시는군요.", "오늘 하루요? 원래 하던 일을 하고 있지요")   # 명사구만
    assert not echoes_user("평소대로 보내셨군요.", "오늘 하루요? 원래 하던 일을 하고 있지요")
    assert echoes_user("원래 하던 일을 하고 계셨군요.", "오늘 하루요? 원래 하던 일을 하고 있지요")   # '원래하던일을하고'
    assert not echoes_user("그러시군요.", "그럭저럭 지내고 있어요")
    assert not echoes_user("회의로 꽉 찬 오전이셨네요.", "오전에 회의가 많았어요")
    assert not echoes_user("바쁘셨군요.", "바빴어요")                                   # 6자 미만 발화는 판정 안 함


def test_echo_guard_wired_and_logged():
    src = open(os.path.join(ROOT, "diag_project", "routes", "diagnoses.py"), encoding="utf-8").read()
    assert "_echoes(_recv, request.content)" in src and '_repl_stmts(_recv, "그러셨군요.")' in src   # 평서문만 대체, 되물음 보존
    assert '"echo": int(_tm.get("echo") or 0)' in src


def test_ready_for_intro_forced_at_expectation_turn_and_next_is_intro():
    """기대 질문 턴(rapport_turn_count>=2) 뒤 라포 완료 → 다음 턴 DIAGNOSIS_INTRO. 진단_대화 없음."""
    base = {"chapter": "organization_management", "session_deflection_count": 0, "session_already_warned": False,
            "disengagement_streak": 0, "probe_cycles": 0, "last_refusal": False, "awaiting_abort_decision": False,
            "pending_abort": False, "intro_done": False, "chapter_started": False, "competency_aligned": False,
            "definition_asked": False, "name_extraction_failed": False, "name_reconfirm_asked": False,
            "turn_count": 1, "chapter_message_count": 0, "contains_avoidance_keywords": False,
            "events_collected": 0, "events_with_star_70": 0, "has_contrary_probe": False}
    # 기대 답변 '없어요' 가 도착한 턴: 라포 완료(READY_FOR_INTRO 백엔드 확정) → INTRO
    s = dict(base, rapport_complete=True, rapport_turn_count=4, last_user_response="없어요")
    assert decide_instruction(s) == "DIAGNOSIS_INTRO"
    # 그 다음 '네' → CONFIRM (rapport_turn_count=5 < 캡 6)
    s2 = dict(base, rapport_complete=True, intro_done=True, rapport_turn_count=5, last_user_response="네")
    assert decide_instruction(s2) == "DIAGNOSIS_CONFIRM"


def test_route_wiring():
    src = open(os.path.join(ROOT, "diag_project", "routes", "diagnoses.py"), encoding="utf-8").read()
    assert '_pl_r("role_q") if _rc == 2 else _pl_r("expect_q")' in src   # 페르소나별 고정 질문
    assert 'probe_type_used = "ROLE_ASK"' in src
    assert "'intro_bridge')}\\n\\n{build_intro_anchor_section()}" in src   # 기대 없음 → 페르소나 다리 + 안내
    assert "어떤 일을 맡고 계신지도 간단히 알려주시겠어요" not in src
    dec = open(os.path.join(ROOT, "diag_project", "services", "instruction_decider.py"), encoding="utf-8").read()
    assert "force_ready_for_intro = rapport_turn_count >= 3" in dec


def test_light_system_prompt_has_listen_lite_but_constant_unchanged():
    light = build_layer1_with_persona("1", user_name="박기진", mode="light")
    heavy = build_layer1_with_persona("1", user_name="박기진", mode="heavy")
    assert "# 듣기 (축약)" in light and "# 따라가기 (듣기)" not in light
    assert "# 따라가기 (듣기)" in heavy and "# 듣기 (축약)" not in heavy
    assert "따라가기" not in LAYER1_LIGHT
    assert LAYER1_LISTEN_LITE not in LAYER1_SYSTEM_PROMPT
