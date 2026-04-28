"""Layer 3: Turn State 를 LLM 프롬프트 텍스트로 변환

build_turn_state() 가 반환한 dict 를 LLM 이 이해할 수 있는
구조화된 텍스트로 변환.

설계 출처: docs/phase3a/01_design.md (Section 7.3)
"""

import json


def format_turn_state_for_llm(state: dict) -> str:
    """state dict 를 LLM 프롬프트 텍스트로 변환.

    Layer 1 (System Prompt) + Layer 2 (Chapter Context) 위에
    매 턴마다 추가되는 동적 정보.
    """
    instruction = state["instruction_for_this_turn"]

    # 핵심 정보만 LLM 에게 전달
    core_state = {
        "chapter": state["chapter"],
        "turn_count": state["turn_count"],
        "events_collected": state["events_collected"],
        "events_with_star_70": state["events_with_star_70"],
        "current_event_id": state["current_event_id"],
        "current_event_star_coverage": state["current_event_star_coverage"],
        "has_contrary_probe": state["has_contrary_probe"],
        "avoidance_count": state["avoidance_count_in_chapter"],
    }

    # 중복 검출 시에만 existing_events 노출
    if state.get("duplicate_suspected"):
        core_state["existing_events"] = state["existing_events"]

    # 크로스 챕터 시에만 노출
    if state.get("cross_chapter_signals"):
        core_state["cross_chapter_signals"] = state["cross_chapter_signals"]

    state_text = json.dumps(core_state, ensure_ascii=False, indent=2)

    instruction_guide = _get_instruction_guide(instruction)

    return f"""[Turn State]
{state_text}

[Instruction for this turn]
{instruction}

{instruction_guide}"""


def _get_instruction_guide(instruction: str) -> str:
    """각 instruction 에 따른 LLM 행동 가이드."""

    guides = {
        "CHAPTER_OPENING": (
            "Layer 2의 챕터 시작 스크립트를 그대로 출력하세요. "
            "절대 변형하지 말고 정확히."
        ),
        "CONTINUE_NORMAL": (
            "특이사항 없음. 현재 사건의 STAR를 보강하는 탐침을 던지세요."
        ),
        "STAR_INCOMPLETE": (
            "현재 사건에서 부족한 STAR 요소를 보완하는 탐침을 사용하세요. "
            "특히 R(Result) 가 비어있으면 Measurement Probe 사용."
        ),
        "STAR_COMPLETE_NEW_EVENT": (
            "현재 사건이 완성됐습니다. 자연스럽게 정리하고 "
            "새로운 사건을 유도하세요. Incident Probe 사용."
        ),
        "CONTRARY_NEEDED": (
            "반례 탐침을 지금 수행하세요. Module 2의 3가지 변형 중 "
            "자연스러운 것 선택. 자기관리 챕터면 '흔들림' 변형 사용."
        ),
        "AVOIDANCE_DETECTED": (
            "회피 응답입니다. Module 5의 패턴별 대응 사용. "
            "재시도 1회 후에도 안 풀리면 건너뛰기 명시적 제안."
        ),
        "DUPLICATE_SUSPECTED": (
            "사용자가 이전 챕터의 사건을 다시 말하려고 합니다. "
            "existing_events 를 확인하고 Module 4의 부드러운 거절 패턴 사용."
        ),
        "CROSS_CHAPTER_OPPORTUNITY": (
            "자기관리 챕터입니다. cross_chapter_signals 의 인용을 "
            "활용해 '아까 X 말씀하셨는데, 그때 내면에서는...' 식으로 깊이 파고드세요."
        ),
        "CHAPTER_READY_TO_END": (
            "이 챕터의 모든 조건이 충족됐습니다. "
            "새로운 탐침 던지지 마세요. 챕터 정리 멘트로 마무리하고 "
            "응답 끝에 [CHAPTER_COMPLETE] 태그 출력 필수."
        ),
        "MAX_TURNS_REACHED": (
            "최대 턴 도달. 강제 종료. 짧게 정리 멘트 + [CHAPTER_COMPLETE]."
        ),
        "USER_REQUESTS_PAUSE": (
            "사용자가 종료/일시중지 요청. 정중하게 인사하고 "
            "지금까지 진행 상황 짧게 요약. 응답 끝에 [SESSION_PAUSE]."
        ),
        "META_QUESTION_FROM_USER": (
            "사용자가 시스템에 대해 물었습니다. 짧게 답하고 "
            "다시 진단 흐름으로 부드럽게 복귀하세요."
        ),
        "FIRST_TURN_AVOIDANCE": (
            "첫 턴부터 회피. 라포 회복 우선. Layer 2의 backup 질문 사용."
        ),
        "INVALID_INPUT": (
            "의미 없는 입력. '답변이 잘 들어왔는지 확인이 안 됐어요' "
            "패턴으로 재요청."
        ),
    }

    return guides.get(instruction, "기본 진행")
