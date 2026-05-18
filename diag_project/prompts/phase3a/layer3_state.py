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

    # COMPETENCY_ALIGN: 정의 + 세부역량 노출 (LLM 이 정확히 인용해야 함)
    if instruction == "COMPETENCY_ALIGN" and state.get("chapter_framework"):
        core_state["chapter_framework"] = state["chapter_framework"]

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
    force_ready = False

    if state:
        hour_text = state.get("current_hour_text", hour_text)
        time_tone = state.get("current_time_tone", time_tone)
        forced_category = state.get("forced_rapport_category", "일상")
        force_ready = state.get("force_ready_for_intro", False)

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
            f"- 상쾌한 아침: '출근하셨어요?' / '오시는 길 어떠셨어요?'\n"
            f"- 분주한 점심: '식사는 하셨어요?'\n"
            f"- 활기찬 오후: '점심 식사는 하셨어요?' / '오후 시간 어떠세요?'\n"
            f"- 차분한 저녁: '오늘 하루 어떠셨어요?'\n"
            f"- 조용한 밤: '늦은 시간까지 수고 많으세요.'\n"
            f"- 늦은 시간: '늦은 시간까지 시간 내주셨네요.'\n\n"
            f"**절대 금지**:\n"
            f"- 추상적 질문 ('어떤 마음으로 시작하시나요?')\n"
            f"- 메타 질문 ('어떤 기대를 가지고...?')\n"
            f"- BEI 질문 (사건/경험)\n"
            f"- 한 번에 두 개 이상 질문\n\n"
            f"**중요**: 이번 턴엔 [READY_FOR_INTRO] 신호 보내지 마세요. "
            f"라포 최소 2턴 필요."
        ),
        "기대": (
            "**이번 턴 카테고리 (시스템 강제): 기대**\n\n"
            "참여 감사 + 의미 부여 + 기대 질문을 한 메시지에.\n\n"
            "**필수 응답 형식 (이 톤 그대로)**:\n"
            "  '[호칭] 리더님, 오늘 진단에 참여해주셔서 고맙습니다.\n"
            "  이번 진단이 리더님의 역량 향상에 도움이 되길 희망합니다.\n"
            "  혹시 이번 진단에서 기대하시는 것이 있나요?'\n\n"
            "이 구조가 자연스러운 이유:\n"
            "1. 감사 표현 (참여에 대한 인사)\n"
            "2. 의미 부여 (역량 향상에 도움)\n"
            "3. 답하기 쉬운 질문 (기대하시는 것)\n\n"
            "**절대 금지**:\n"
            "- '어떤 마음으로 진단에 참여하시게 됐어요?' "
            "(추상적, 답하기 어려움)\n"
            "- 일상 질문 ('출근하셨어요?', '식사 하셨어요?') "
            "← 이전 턴에서 이미 물음\n"
            "- 참여 이유 캐묻기 ('회사 차원? 직접 신청?') ← 사용자가 답할 동기 없음\n"
            "- BEI 질문 (사건/경험)\n"
            "- 한 번에 두 개 이상 질문\n\n"
            "이번 턴엔 [READY_FOR_INTRO] 가능 (사용자 답변 보고 판단)."
        ),
        "진단_대화": (
            "**이번 턴 카테고리 (시스템 강제): 진단_대화**\n\n"
            "이전 사용자 답변을 분석해서 아래 4가지 중 하나로 응답.\n\n"
            "**분기 1 — 명확한 동의** ('네', '응', '좋아요', '시작해요', 짧은 긍정):\n"
            "  → [READY_FOR_INTRO] 즉시 포함. 추가 질문 금지.\n"
            "  예: '그럼 진단 안내드릴게요. [READY_FOR_INTRO]'\n\n"
            "**분기 2 — 시작 의지** ('해볼게요', '시작해주세요', '준비됐어요', 적극적 의지):\n"
            "  → [READY_FOR_INTRO] 즉시 포함.\n"
            "  예: '네, 바로 안내드릴게요. [READY_FOR_INTRO]'\n\n"
            "**분기 3 — 망설임** ('글쎄요', '잘 모르겠어요', '아무 생각 없어요'):\n"
            "  → 가벼운 공감 + 시작 의지 확인. [READY_FOR_INTRO] 금지.\n"
            "  예: '천천히 하셔도 됩니다. 진단 안내로 넘어가도 될까요?'\n\n"
            "**분기 4 — 부정/지침** ('그냥 그래요', '별로', '힘들어요', 피곤함/부정 신호):\n"
            "  → 감정 공감. 강요 금지. [READY_FOR_INTRO] 절대 금지.\n"
            "  예: '오늘 컨디션이 좋지 않으신가요? 부담 없이 천천히 하셔도 됩니다.'\n\n"
            "**⚠️ 핵심 규칙**:\n"
            "- '네' 한 글자 = 동의. 즉시 [READY_FOR_INTRO]. 추가 질문 금지.\n"
            "- '그냥 그래요' = 부정 신호. 공감. [READY_FOR_INTRO] 절대 금지.\n"
            "- 같은 질문 두 번 반복 금지 (무한 루프 위반).\n\n"
            "**절대 금지**:\n"
            "- 이미 물어본 카테고리 (일상/기대) 질문 반복\n"
            "- 참여 이유 캐묻기 ('회사 차원? 직접 신청?')\n"
            "- 사용자 동의 없이 [READY_FOR_INTRO] 보내기\n"
            "- BEI 질문\n"
            "- 한 번에 두 개 이상 질문"
        ),
    }

    selected_guide = category_guides.get(
        forced_category, category_guides["일상"]
    )

    force_directive = ""
    if force_ready:
        force_directive = (
            "🚨 **시스템 강제 명령** 🚨\n"
            "이전 사용자 답변이 동의 신호입니다. "
            "이번 응답에 [READY_FOR_INTRO] 를 반드시 포함하세요.\n"
            "예: '네, 그럼 진단 안내드릴게요. [READY_FOR_INTRO]'\n"
            "다른 질문 추가 금지. 이 명령이 최우선입니다.\n\n"
        )

    return (
        f"라포 형성 단계입니다. 사용자와 가벼운 대화를 주고받으며 "
        f"진단에 대한 마음의 준비를 돕습니다.\n\n"
        f"=========================================\n"
        f"{force_directive}"
        f"{selected_guide}\n"
        f"=========================================\n\n"
        f"**공감 표현 — 매우 중요 (Gemini 모범 톤)**:\n\n"
        f"사용자 답변에 따라 따뜻한 공감 표현을 응답 앞에 한 번 사용.\n\n"
        f"긍정적 답변 시 (예: '기분 좋아요', '괜찮아요'):\n"
        f"  '와, 그 긍정적인 에너지가 여기까지 전해지는 것 같아요!'\n"
        f"  '그 편안한 마음이 정말 좋네요.'\n"
        f"  '기분 좋은 분위기 속에서 함께 시간을 보낼 수 있어 저도 반갑습니다.'\n\n"
        f"중립/모호한 답변 시 (예: '그냥 그래요', '보통이에요'):\n"
        f"  '그러시군요. 차분하게 하루를 보내고 계시는 거네요.'\n"
        f"  '편안한 마음으로 함께 시간 가져봐요.'\n\n"
        f"부정/지친 답변 시 (예: '피곤해요', '별로예요'):\n"
        f"  '오늘 좀 힘드신 것 같으세요. 그런 날도 있죠.'\n"
        f"  '수고하시는 시간 속에서 잠깐이라도 편하게 함께해요.'\n\n"
        f"원칙: 공감 표현 다양화 (같은 표현 반복 X). "
        f"매 응답에 공감 한 문장 + 자연스러운 다음 질문/안내.\n\n"
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
            "역량 정의 합의 단계입니다. 직전에 사용자가 자기 정의를 답변했고, "
            "이제 그 답변에 공감 + 우리 정의 제시 + 세부역량 안내 + 합의 질문 "
            "을 한 메시지에.\n\n"
            "**현재 챕터 정보**: state 의 chapter_framework 필드\n"
            "  - chapter_framework['name']: 한글 챕터명\n"
            "  - chapter_framework['description']: 공식 정의 (정확히 인용 필수)\n"
            "  - chapter_framework['indicator_names']: 세부역량 이름 목록 "
            "(정확히 인용 필수)\n\n"
            "**필수 응답 형식 — 4단 구조**:\n"
            "1. 사용자 답변 구체적 paraphrase + 칭찬 "
            "('정말 핵심을 잘 짚어주셨습니다' 등)\n"
            "2. 우리 정의 정확 인용 (★★★ 단어 하나도 변경 금지)\n"
            "3. 세부역량 리스트 정확 인용 (bullet 형식)\n"
            "4. 합의 질문 ('이 N가지를 중심으로 이야기 나눠봐도 괜찮으시겠어요?')\n\n"
            "**예시 (조직관리, 사용자 답변: '조직을 관리하는 리더의 역량이요')**:\n"
            "  '리더님께서는 조직관리를 조직을 관리하는 리더의 역량으로 보시는 "
            "거군요. 정말 핵심을 잘 짚어주셨습니다.\n\n"
            "  저희 진단에서는 조직관리를 [chapter_framework.description] 으로 "
            "정의하고 있습니다. 리더님의 생각과도 일맥상통하는 부분이 많죠?\n\n"
            "  이 역량은 [indicator 수]가지 세부 역량으로 구성됩니다:\n"
            "  [chapter_framework.indicator_names 목록 bullet]\n\n"
            "  이 [indicator 수]가지를 중심으로 이야기 나눠봐도 괜찮으시겠어요?'\n\n"
            "**⛔ 절대 금지**:\n"
            "- 정의 단어 변경 (예: 일부 키워드 생략·재조합) 절대 X\n"
            "- 세부역량 이름 변경 (예: '비전 제시 및 공유' → '비전 공유') X\n"
            "- '행동 기반' 같은 자기 학습 단어 임의 추가 X\n"
            "- BEI 질문 (사건/경험)\n"
            "- 사용자 답변 무시\n\n"
            "**톤**: 페르소나에 맞게. 정의·세부역량 인용은 페르소나 무관 그대로."
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
            "**긍정인 경우 응답 — 매우 짧게:**\n"
            "사용자가 '네' 같은 동의를 표현하면 응답은 다음 단계 자연스럽게 연결.\n\n"
            "  좋은 예시:\n"
            "    '준비되셨다니 좋습니다. [START_CHAPTER]'\n"
            "    '편하게 진행해보겠습니다. [START_CHAPTER]'\n"
            "    '알겠습니다. [START_CHAPTER]'\n\n"
            "  ⛔ 절대 금지 (다음 턴 COMPETENCY_INTRO 와 중복되는 표현):\n"
            "    X '그럼 첫 번째 영역인 조직관리에 대해 이야기 나눠볼게요.'\n"
            "    X '조직관리 영역부터 시작해볼게요.'\n"
            "    X '이야기 나눠볼게요'\n"
            "    X 챕터 이름 (조직관리/성과관리/사람관리/일관리/자기관리) 언급\n\n"
            "  이유: 다음 턴의 COMPETENCY_INTRO 가 이미 챕터 안내를 함.\n"
            "  여기서 미리 말하면 사용자가 같은 말 두 번 듣게 됨.\n"
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
            "특이사항 없음. 현재 사건의 STAR를 보강하는 탐침을 던지세요.\n\n"
            "**공감 + 호기심 표현 — 매우 중요**:\n\n"
            "BEI 탐침 질문 전에 반드시 사용자 답변에 공감/호기심 표현 한 문장.\n"
            "취조성 질문 ('그때 어떤 회의였는지, 누구와 함께였는지 편하게...') "
            "절대 금지.\n\n"
            "좋은 예시:\n"
            "- '팀에 정말 좋은 문화네요!'\n"
            "- '매년 그렇게 챙기시는 게 쉽지 않으셨을 텐데, 정말 인상적이에요.'\n"
            "- '구체적인 이야기가 정말 흥미로워요.'\n"
            "- '그 부분이 진짜 중요한 포인트네요.'\n"
            "- '그렇게 느끼셨던 게 충분히 이해돼요.'\n\n"
            "그 다음에 자연스러운 BEI 탐침 질문 (한 번에 한 질문).\n\n"
            "⛔ 절대 금지:\n"
            "- '그 부분이 참 중요하죠. 가장 최근에...' (싱겁고 paraphrase 만)\n"
            "- 한 번에 여러 질문 ('그때 어떤 회의였는지, 누구와 함께였는지, "
            "어떤 분위기였는지')\n"
            "- 취조성 ('말씀해주실 수 있을까요?' 만 반복)\n\n"
            "원칙: 공감/호기심 한 문장 + BEI 탐침 한 질문 = 한 응답."
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
