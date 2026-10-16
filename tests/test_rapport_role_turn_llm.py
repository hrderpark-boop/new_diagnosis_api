"""(2026-10-16) 라포 2턴(담당 업무 질문)을 템플릿에서 light LLM 턴으로 — 가이드·light 듣기 절 회귀(LLM·DB 없음).

kjpark 세션: "오늘은 금요일이라 뭔가 일이 잘 안되네요" 에 템플릿 "그러시군요. 어떤 일을 맡고 계신지도…" 가 나갔다.
LLM 을 호출하지 않는 턴이라 어떤 듣기 지시도 작동할 수 없었고, light 시스템 프롬프트에는 듣기 절 자체가 없었다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.prompts.phase3a import layer3_state as L  # noqa: E402
from diag_project.prompts.phase3a.layer1_system import (  # noqa: E402
    LAYER1_LIGHT, LAYER1_LISTEN_LITE, LAYER1_SYSTEM_PROMPT, build_layer1_with_persona,
)
from diag_project.services.instruction_decider import _force_rapport_category  # noqa: E402


def _rapport_guide(category: str, last: str) -> str:
    state = {"instruction_for_this_turn": "RAPPORT_BUILDING", "forced_rapport_category": category,
             "current_hour_text": "오후 4시", "current_time_tone": "활기찬 오후", "last_user_response": last}
    return L._get_instruction_guide("RAPPORT_BUILDING", state)


def test_role_turn_category_is_forced_at_second_rapport_turn():
    assert _force_rapport_category(1) == "담당업무"


def test_role_turn_guide_receives_then_asks_role():
    g = _rapport_guide("담당업무", "오늘은 금요일이라 뭔가 일이 잘 안되네요")
    assert "카테고리 (시스템 강제): 담당업무" in g
    assert "받기(한 문장, 필수)" in g and "리더님이 쓴 말을 넣어" in g
    assert "어떤 일을 맡고 계신지" in g and "팀 규모" in g
    assert "[READY_FOR_INTRO] 절대 금지" in g
    assert "기대 질문" in g                      # 다음 턴 담당임을 명시
    assert L.EXAMPLE_LABEL in g                  # 예시는 라벨 포함


def test_light_system_prompt_has_listen_lite_but_constant_unchanged():
    light = build_layer1_with_persona("1", user_name="박기진", mode="light")
    heavy = build_layer1_with_persona("1", user_name="박기진", mode="heavy")
    assert "# 듣기 (축약)" in light and "리더가 쓴 말을 넣어 한 문장으로 받고" in light
    assert "# 따라가기 (듣기)" not in light     # BEI 전용 전체 절은 light 에 없음
    assert "# 따라가기 (듣기)" in heavy and "# 듣기 (축약)" not in heavy
    assert "따라가기" not in LAYER1_LIGHT      # 기존 테스트 전제 유지
    assert LAYER1_LISTEN_LITE not in LAYER1_SYSTEM_PROMPT
    assert len(LAYER1_LIGHT + LAYER1_LISTEN_LITE) < 4000


def test_route_has_no_role_ask_template():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "diag_project", "routes", "diagnoses.py"), encoding="utf-8").read()
    assert "어떤 일을 맡고 계신지도 간단히 알려주시겠어요" not in src
    assert 'probe_type_used = "ROLE_ASK"' in src   # 마커는 유지(participant_context 저장 근거)
