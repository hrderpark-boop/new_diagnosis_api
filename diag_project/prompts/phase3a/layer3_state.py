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

    instruction_guide = _get_instruction_guide(instruction, state)

    return f"""[Turn State]
{state_text}

[Instruction for this turn]
{instruction}

{instruction_guide}"""


def _build_rapport_guide(state: dict | None) -> str:
    """RAPPORT_BUILDING 가이드 동적 생성.

    시스템이 강제로 정한 카테고리에서만 질문하도록 LLM 통제.
    가이드 기반 카테고리 제어가 7번 시도 모두 실패한 후 도입된 방식.
    """
    hour_text = "현재 시간"
    time_tone = "현재 시간대"
    forced_category = "일상"

    if state:
        hour_text = state.get("current_hour_text", hour_text)
        time_tone = state.get("current_time_tone", time_tone)
        forced_category = state.get("forced_rapport_category", "일상")

    # 카테고리별 가이드 — 시스템이 고른 1개만 LLM 에 보여줌
    category_guides = {
        "일상": (
            f"**이번 턴 카테고리 (시스템 강제): 일상**\n\n"
            f"현재 시간 정보:\n"
            f"- 시간: {hour_text}\n"
            f"- 시간대: {time_tone}\n\n"
            f"시간대에 맞는 일상 질문 하나만 하세요. **한 번에 한 질문**.\n\n"
            f"좋은 질문 예시 ({time_tone}):\n"
            f"- 이른 아침: '출근 전이세요?' / '오시는 길 어떠셨어요?'\n"
            f"- 상쾌한 아침: '출근하셨어요?' / '오늘 오전 일정 어떠세요?'\n"
            f"- 분주한 점심: '식사는 하셨어요?'\n"
            f"- 활기찬 오후: '점심 드셨어요?' / '오후 일정은 여유로우세요?'\n"
            f"- 차분한 저녁: '오늘 하루 어떠셨어요?'\n"
            f"- 조용한 밤/늦은 시간: '늦은 시간까지 수고 많으세요. 식사는 하셨어요?'\n\n"
            f"**절대 금지**:\n"
            f"- 추상적 질문 ('어떤 마음으로 시작하시나요?', '기대가 있으세요?')\n"
            f"- 진단 계기 질문 ('왜 진단받으시나요?')\n"
            f"- BEI 질문 (사건/경험)\n"
            f"- 한 번에 두 개 이상 질문\n\n"
            f"**중요**: 이번 턴엔 [READY_FOR_INTRO] 신호 보내지 마세요. "
            f"라포 최소 2턴 필요."
        ),
        "마음_기대": (
            "**이번 턴 카테고리 (시스템 강제): 마음/기대**\n\n"
            "리더님이 진단에 임하는 마음 또는 기대를 묻는 질문 하나.\n\n"
            "좋은 질문 예시:\n"
            "- '오늘 어떤 마음으로 진단에 참여하시게 됐어요?'\n"
            "- '이번 진단에서 특별히 기대하시는 게 있으세요?'\n"
            "- '어떤 마음으로 오늘 시간 내주신 거예요?'\n\n"
            "**절대 금지**:\n"
            "- 일상 질문 ('출근하셨어요?', '식사 하셨어요?', '일정 어떠세요?')\n"
            "  ← 이전 턴에서 이미 일상 질문 했음. 반복 절대 X.\n"
            "- BEI 질문 (사건/경험)\n"
            "- 한 번에 두 개 이상 질문\n\n"
            "이번 턴엔 [READY_FOR_INTRO] 가능 (사용자 답변 보고 판단)."
        ),
        "계기": (
            "**이번 턴 카테고리 (시스템 강제): 계기**\n\n"
            "리더십 진단을 받게 된 계기를 묻는 질문 하나.\n\n"
            "좋은 질문 예시:\n"
            "- '리더십 진단을 받으시게 된 계기가 있으셨어요?'\n"
            "- '스스로 신청하신 거예요, 회사 권유로 하시는 거예요?'\n"
            "- '회사 차원에서 진행하시는 거예요?'\n\n"
            "**절대 금지**:\n"
            "- 일상 질문 ← 이전에 이미 물어봄\n"
            "- 마음/기대 질문 ← 이전에 이미 물어봄\n"
            "- BEI 질문 (사건/경험)\n"
            "- 한 번에 두 개 이상 질문\n\n"
            "이번 턴엔 [READY_FOR_INTRO] 가능."
        ),
        "진단_대화": (
            "**이번 턴 카테고리 (시스템 강제): 진단/대화 관련**\n\n"
            "진단에 대한 사용자의 사전 경험 또는 궁금증을 묻는 질문 하나.\n\n"
            "좋은 질문 예시:\n"
            "- '이런 진단 받으시는 거 처음이세요?'\n"
            "- '혹시 진단 전에 궁금하신 점 있으세요?'\n"
            "- '이런 종류의 자기 진단은 처음이세요?'\n\n"
            "**절대 금지**:\n"
            "- 이미 물어본 카테고리 (일상/마음/계기) 질문 ← 반복 절대 X\n"
            "- BEI 질문\n"
            "- 한 번에 두 개 이상 질문\n\n"
            "이번 턴엔 [READY_FOR_INTRO] 가능. 라포가 너무 길어지지 않게."
        ),
    }

    selected_guide = category_guides.get(forced_category, category_guides["일상"])

    return (
        f"라포 형성 단계입니다. 사용자와 가벼운 대화를 주고받으며 "
        f"진단에 대한 마음의 준비를 돕습니다.\n\n"
        f"=========================================\n"
        f"{selected_guide}\n"
        f"=========================================\n\n"
        f"**공통 응답 패턴**:\n"
        f"1. 사용자 답변을 그대로 echo 하지 마세요.\n"
        f"   X '별일 없으시군요. 다행이네요.'\n"
        f"   O '그러시군요.' (짧게 받아넘김)\n"
        f"2. '다행이네요' / '괜찮으시군요' 한 대화에서 한 번만.\n"
        f"3. '혹시' 자제. 너무 자주 쓰면 소심한 느낌.\n\n"
        f"**라포 시스템 동작 안내** (참고용):\n"
        f"- 이번 턴 카테고리는 시스템이 정했습니다. 다른 카테고리로 질문 X.\n"
        f"- 라포 최대 6턴까지 (그 후 시스템이 자동 진단 안내로 진행).\n"
        f"- 첫 인사는 시스템이 이미 보냈습니다. 두 번째 턴부터 담당합니다."
    )


def _build_competency_intro_guide(state: dict | None) -> str:
    """COMPETENCY_INTRO 가이드: 리더님의 역량 정의를 묻는다."""
    chapter = (state or {}).get("chapter", "")
    chapter_name_map = {
        "organization_management": "조직관리",
        "performance_management": "성과관리",
        "people_management": "사람관리",
        "work_management": "일관리",
        "self_management": "자기관리",
    }
    chapter_name = chapter_name_map.get(chapter, "이 역량")

    return (
        f"역량 정의 소개 단계입니다. 챕터를 소개하고 리더님이 "
        f"'{chapter_name}'를 어떻게 생각하는지 먼저 여쭤봅니다.\n\n"
        f"**목적**: 리더님의 언어로 역량을 정의하도록 유도 → "
        f"다음 턴에 시스템이 프레임워크 정의와 비교해 합의 도출\n\n"
        f"**응답 예시**:\n"
        f"  '그럼 '{chapter_name}' 영역부터 시작하겠습니다. "
        f"본격적으로 들어가기 전에 한 가지 여쭤보고 싶어요. "
        f"리더님은 '{chapter_name}'가 무엇이라고 생각하세요?'\n\n"
        f"  또는 더 짧게:\n"
        f"  '먼저 '{chapter_name}' 영역에 대해 이야기 나눠볼게요. "
        f"시작 전에, 리더님은 '{chapter_name}'를 어떻게 정의하세요?'\n\n"
        f"**규칙**:\n"
        f"- 한 번에 한 질문만. 역량 정의 하나만 물어볼 것.\n"
        f"- BEI 사건 질문 절대 금지. '경험이 있으신가요?' 금지.\n"
        f"- 세부 지표를 미리 설명하지 마세요 (다음 턴 시스템이 제시).\n"
        f"- 역량 정의 자체를 먼저 제시하지 마세요 (리더님 답변 먼저).\n"
        f"- 짧고 자연스럽게. 딱딱한 설문식 금지.\n"
        f"- 톤: 격식 있되 따뜻한 호기심"
    )


def _build_chapter_opening_guide(state: dict | None) -> str:
    """CHAPTER_OPENING 가이드: 역량 합의 후 첫 BEI 질문."""
    first_sub = (state or {}).get("first_subcompetency_name", "")
    sub_hint = f" (첫 번째 세부 역량: '{first_sub}')" if first_sub else ""

    return (
        f"본격 진단 시작 단계입니다. 직전에 리더님이 역량 정의에 동의했고, "
        f"이제 첫 BEI 질문을 시작합니다{sub_hint}.\n\n"
        f"**현재 챕터의 첫 세부역량**: state 의 first_subcompetency_name 필드\n"
        f"  - 조직관리 → '비전 제시 및 공유'\n"
        f"  - 성과관리 → '목표설정 및 공유'\n"
        f"  - 사람관리 → '갈등관리'\n"
        f"  - 일관리 → '업무계획 및 조직력'\n"
        f"  - 자기관리 → '자기인식'\n\n"
        f"**필수 응답 형식**:\n"
        f"  '감사합니다. 그럼 첫 번째 세부 역량인 "
        f"'{{first_subcompetency_name}}' 부터 시작하겠습니다.\n\n"
        f"  {{그 세부역량 관련 최근 경험을 떠올리도록 BEI 질문}}'\n\n"
        f"**예시 (조직관리, 비전 제시 및 공유)**:\n"
        f"  '감사합니다. 그럼 첫 번째 세부 역량인 '비전 제시 및 공유' "
        f"부터 시작하겠습니다.\n"
        f"  최근에 조직이나 팀의 비전을 새로 세우거나 공유하셨던 "
        f"경험이 있으세요?'\n\n"
        f"**예시 (사람관리, 갈등관리)**:\n"
        f"  '감사합니다. 그럼 첫 번째 세부 역량인 '갈등관리' 부터 "
        f"시작하겠습니다.\n"
        f"  최근에 팀 내에서 갈등 상황을 다루셨던 경험이 있으세요?'\n\n"
        f"**톤**: 격식 있고 정중하게. '감사합니다' 로 시작.\n"
        f"**절대 금지**:\n"
        f"- 역량 정의를 다시 설명하는 것 (방금 합의 완료)\n"
        f"- 한 번에 두 가지 이상 질문\n"
        f"- 이미 합의된 역량 프레임워크 재소개"
    )


def _get_instruction_guide(
    instruction: str,
    state: dict | None = None,
) -> str:
    """각 instruction 에 따른 LLM 행동 가이드."""

    if instruction == "RAPPORT_BUILDING":
        return _build_rapport_guide(state)

    guides = {
        "COMPETENCY_INTRO": _build_competency_intro_guide(state),
        "COMPETENCY_ALIGN": (
            "이 응답은 시스템이 직접 출력합니다. LLM 개입 없음. "
            "이 가이드가 표시되면 코드 오류입니다."
        ),
        "CHAPTER_OPENING": _build_chapter_opening_guide(state),
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
            "  오늘 함께할 진단은 5개 영역의 리더십 진단이에요. "
            "조직관리, 성과관리, 인재개발, 변화혁신, 자기개발 — 이렇게 "
            "5가지 영역을 차례로 살펴보게 됩니다.\n\n"
            "  영역마다 약 30분씩, 전체로는 2-3시간 정도 걸려요. "
            "한 번에 다 하지 않으셔도 괜찮아요. 중간에 저장하고 나중에 "
            "이어가실 수 있어요.\n\n"
            "  저와 리더님의 실제 경험을 바탕으로 편안하게 대화 "
            "나누시면 돼요. 정답은 없으니 편하게 말씀해주시면 돼요.\n\n"
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
            "**긍정인 경우 응답 예시 (매우 짧게)**:\n"
            "  '알겠습니다. [START_CHAPTER]'\n"
            "  '네. [START_CHAPTER]'\n"
            "  → 절대 금지: '시작해볼게요', '조직관리 시작', '이야기 나눠볼게요'\n"
            "    이유: 다음 턴의 챕터 시작 스크립트가 본격 안내를 하므로 중복.\n"
            "  → [START_CHAPTER] 태그 필수.\n\n"
            "**부정 응대 — 사용자가 '아니요' / '아직' / '잠깐만요'**:\n"
            "  망설이는 이유가 다양할 수 있으니 추가 설명 + 재확인.\n\n"
            "  시나리오 1 (시간 걱정):\n"
            "    '네, 시간이 걱정되실 수 있어요. 아까 말씀드렸듯이 한 번에 다 "
            "하지 않으셔도 됩니다. 첫 영역만 30분 정도 진행해보시고 이어서 "
            "할지 결정하셔도 됩니다. 어떠세요?'\n\n"
            "  시나리오 2 (모호한 거부):\n"
            "    '네, 천천히 결정하셔도 됩니다. 혹시 진단 진행 방식에 대해 "
            "더 궁금하신 점이 있으세요? 또는 시작 시점이 부담스러우시면 "
            "다음에 진행하셔도 괜찮습니다.'\n\n"
            "  시나리오 3 (질문 — '얼마나 걸려요?', '어떻게 진행돼요?'):\n"
            "    질문에 직접 답변 후 다시 시작 여부 확인.\n"
            "    '5개 영역 모두 합치면 2-3시간 정도 걸립니다. 영역마다 "
            "30분 정도 예상하시면 됩니다. 시작할 준비 되셨으면 알려주세요.'\n\n"
            "  → 모든 부정 응대에서 [START_CHAPTER] 태그 X.\n"
            "  → 다음 턴에 사용자 답변 보고 다시 분기.\n\n"
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
