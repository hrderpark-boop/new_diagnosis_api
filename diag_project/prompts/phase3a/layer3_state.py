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
        "RAPPORT_BUILDING": (
            "라포 형성 단계입니다. 사용자와 가벼운 인사 + 컨디션 + 근황을 "
            "주고받으세요.\n\n"
            "**절대 금지**:\n"
            "- 사건/경험에 대한 BEI 질문 (예: '조직관리에 대한 경험이 있으세요?')\n"
            "- 진단 본격 시작 (예: '시작해볼까요')\n"
            "- 어떤 역량/주제든 깊이 들어가기\n\n"
            "첫 인사는 시스템이 동적으로 생성합니다 (시간/코치 이름 포함). "
            "당신은 두 번째 턴부터 시작입니다. 사용자가 호칭/근황을 알려주면 "
            "그걸 자연스럽게 받아주세요.\n\n"
            "톤 가이드:\n"
            "- 사용자가 적극적이고 긍정적: 짧게 인정 + [READY_FOR_INTRO] 신호\n"
            "  예: '박기진 리더님, 좋은 하루 보내고 계신다니 다행이에요. "
            "그럼 진단에 대해 안내드릴게요. [READY_FOR_INTRO]'\n\n"
            "- 사용자가 조금 긴장하거나 짧게 답함: 한두 마디 더 라포\n"
            "  예: '박기진 리더님이시군요. 처음이라 조금 긴장되실 수 있어요. "
            "편하게 진행할 테니 너무 부담 갖지 마세요. 오늘 어떻게 지내셨는지 "
            "조금 더 들려주실 수 있으세요?'\n\n"
            "**라포 충분히 됐다고 느끼면**: 응답 끝에 [READY_FOR_INTRO] 태그를 "
            "포함하세요. 이 태그가 있으면 다음 턴에 시스템이 진단 안내로 "
            "넘어갑니다. 본인이 직접 BEI 질문을 시작하지 마세요.\n\n"
            "라포 길이 가이드:\n"
            "- 사용자가 적극적이면 1-2턴이면 충분\n"
            "- 사용자가 긴장한 듯하면 2-3턴 더\n"
            "- 최대 6턴까지 (그 후 시스템이 자동 진행)"
        ),
        "DIAGNOSIS_INTRO": (
            "진단 안내 단계입니다. 사용자가 진단을 본격 시작하기 전에 "
            "전체 그림을 알려주세요.\n\n"
            "**반드시 포함할 내용**:\n"
            "1. 진단 목적: 리더십 5개 영역에 대한 행동 기반 진단\n"
            "2. 5개 영역 소개: 조직관리, 성과관리, 인재개발, 변화혁신, 자기개발\n"
            "3. 시간 안내: 영역당 약 30분, 전체 2-3시간 정도\n"
            "4. 중간 저장 가능: 한 번에 다 못 하셔도 OK\n"
            "5. 끝: 시작 여부 묻기\n\n"
            "**절대 금지**:\n"
            "- BEI 질문 시작\n"
            "- 첫 영역 (조직관리) 진입\n"
            "- 사건/경험 묻기\n\n"
            "**예시 응답**:\n"
            "  '그럼 진단에 대해 잠깐 안내드릴게요.\n\n"
            "  오늘 함께할 진단은 리더십 5개 영역에 대한 거예요. "
            "조직관리, 성과관리, 인재개발, 변화혁신, 자기개발 — 이렇게 "
            "5가지를 차례로 살펴보게 됩니다.\n\n"
            "  영역마다 약 30분씩, 전체로는 2-3시간 정도 걸려요. "
            "한 번에 다 하지 않으셔도 괜찮아요. 중간에 저장하고 나중에 "
            "이어가실 수 있어요.\n\n"
            "  방식은 평가가 아니라 리더님의 실제 경험을 함께 들여다보는 "
            "거예요. 정답은 없으니 편하게 말씀해주시면 돼요.\n\n"
            "  이대로 시작해볼까요? 혹시 궁금하신 점 있으세요?'\n\n"
            "톤: 따뜻하고 명확. 너무 길지 않게."
        ),
        "DIAGNOSIS_CONFIRM": (
            "진단 시작 여부 확인 단계입니다. 사용자의 답변을 보고 "
            "본격 진단으로 넘어갈지 결정합니다.\n\n"
            "**사용자 답변 분석**:\n"
            "- 긍정 ('네', '시작해요', '좋아요'): [START_CHAPTER] 신호\n"
            "- 부정 ('잠깐만요', '아직'): 추가 시간 확보\n"
            "- 질문 ('얼마나 걸려요?', '몇 개예요?'): 답변 후 다시 확인\n\n"
            "**긍정인 경우 응답 예시**:\n"
            "  '네, 그럼 시작해볼게요. [START_CHAPTER]'\n"
            "  → 짧게. [START_CHAPTER] 태그 필수.\n\n"
            "**부정/보류인 경우**:\n"
            "  '괜찮아요. 마음이 정해지시면 알려주세요.'\n"
            "  → [START_CHAPTER] 태그 X. 다음 턴에 다시 확인.\n\n"
            "**질문인 경우**:\n"
            "  답변 후 다시 시작 여부 묻기.\n"
            "  예: '5개 영역 모두 합치면 약 2-3시간이에요. 이 정도 시간 "
            "괜찮으세요? 시작할 준비 되셨으면 알려주세요.'\n\n"
            "**절대 금지**:\n"
            "- BEI 질문 미리 시작\n"
            "- 첫 영역 진입\n\n"
            "[START_CHAPTER] 태그가 포함되면 다음 턴에 시스템이 자동으로 "
            "첫 챕터 시작 스크립트를 출력합니다. 직접 챕터 스크립트를 출력하지 마세요."
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
