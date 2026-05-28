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
            f"**⚠️ 이름 소개 턴 특별 처리**:\n"
            f"사용자가 '안녕하세요 [이름]입니다' / '[이름]이에요' / "
            f"'저는 [이름]' 식으로 이름을 밝히면:\n"
            f"  → 이름을 불러서 반갑게 인사 + 시간대 질문 하나.\n"
            f"  좋은 예: '네, 안녕하세요 [이름] 리더님. "
            f"만나뵙게 되어 반갑습니다. 오시는 길은 어떠셨어요?'\n"
            f"  나쁜 예: '그러시군요. 편안한 마음으로...' "
            f"← 이름 소개를 무시한 어색한 반응\n\n"
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
            f"- 이름 소개를 받고 '그러시군요' 로만 반응하기\n"
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
            "- 한 번에 두 개 이상 질문\n"
            "- 진단 안내 예고 ('그럼 안내해 드릴게요', '시작하기 전에 "
            "안내를' 류) ← 다음 단계는 시스템이 자동 진행\n\n"
            "이번 턴엔 [READY_FOR_INTRO] 포함 권장. "
            "기대 질문 후 다음 사용자 답변에서 DIAGNOSIS_INTRO 로 "
            "자동 전환됨 (시스템이 담당). 안내 예고 문구 불필요."
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
        f"  '좋은 에너지네요. 저도 오늘 대화가 기대됩니다.'\n\n"
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
    """[DEPRECATED] 작업 24 이후 CONFIRM 단계에서 통합됨.

    DIAGNOSIS_CONFIRM 가이드가 준비 인사 + 챕터 도입 + 정의 묻기까지 수행.
    이 가이드는 fallback 용으로 보존.
    """
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


def _build_confirm_guide(state: dict | None) -> str:
    """DIAGNOSIS_CONFIRM 가이드 동적 생성 — 챕터별 이름·순서어 반영."""
    from diag_project.data.competencies import COMPETENCY_FRAMEWORK

    chapter = (state or {}).get("chapter", "organization_management")
    framework = COMPETENCY_FRAMEWORK.get(chapter, {})
    chapter_name = framework.get("name", "조직관리")
    order_phrase = (
        "첫 번째 영역인"
        if chapter == "organization_management"
        else "다음 영역인"
    )

    return (
        f"진단 시작 여부 확인 단계입니다. 사용자의 답변을 보고 "
        f"본격 진단으로 넘어갈지 결정합니다.\n\n"
        f"**사용자 답변 분석**:\n"
        f"- 긍정 ('네', '시작해요', '좋아요'): [START_CHAPTER] 신호\n"
        f"- 부정 ('잠깐만요', '아직'): 추가 시간 확보\n"
        f"- 질문 ('얼마나 걸려요?', '몇 개예요?'): 답변 후 다시 확인\n\n"
        f"**긍정인 경우 응답 — 준비 인사 + 챕터 도입 + 정의 묻기 (한 응답)**:\n\n"
        f"사용자가 '네' 같은 동의를 표현하면, 다음 세 부분을 한 응답에 통합:\n"
        f"1. 준비 인사 (짧게)\n"
        f"2. {order_phrase} '{chapter_name}' 도입 (한 문장)\n"
        f"3. '{chapter_name}'가 무엇이라고 생각하세요? (정의 묻기)\n\n"
        f"  좋은 예시 1:\n"
        f"    '준비되셨다니 좋습니다. 그럼 이제 본격적으로 "
        f"{order_phrase} '{chapter_name}'에 대해 이야기 나눠볼까요? "
        f"시작하기 전에, 리더님께서는 '{chapter_name}'가 무엇이라고 "
        f"생각하세요? 편하게 들려주세요. [START_CHAPTER]'\n\n"
        f"  좋은 예시 2:\n"
        f"    '편하게 진행해보겠습니다. {order_phrase} '{chapter_name}' 부터 "
        f"함께 살펴볼게요. 리더님은 '{chapter_name}'를 어떻게 정의하세요? "
        f"[START_CHAPTER]'\n\n"
        f"  → [START_CHAPTER] 태그 필수.\n\n"
        f"⛔ 절대 금지:\n"
        f"  X 준비 인사만 하고 끝내기 ('준비됐다니 좋습니다.' 만 X)\n"
        f"  X 정의 질문 없이 [START_CHAPTER] 보내기\n"
        f"  X BEI 질문 (사건/경험 묻기) — 정의만 묻기\n"
        f"  X 진단 안내 반복 (INTRO 에서 이미 함)\n\n"
        f"**부정 응대 — 사용자가 '아니요' / '아직' / '잠깐만요'**:\n"
        f"  망설이는 이유가 다양할 수 있으니 추가 설명 + 재확인.\n\n"
        f"  시나리오 1 (시간 걱정):\n"
        f"    '네, 시간이 걱정되실 수 있어요. 아까 말씀드렸듯이 한 번에 다 "
        f"하지 않으셔도 됩니다. 첫 영역만 30분 정도 진행해보시고 이어서 "
        f"할지 결정하셔도 됩니다. 어떠세요?'\n\n"
        f"  시나리오 2 (모호한 거부):\n"
        f"    '네, 천천히 결정하셔도 됩니다. 혹시 진단 진행 방식에 대해 "
        f"더 궁금하신 점이 있으세요? 또는 시작 시점이 부담스러우시면 "
        f"다음에 진행하셔도 괜찮습니다.'\n\n"
        f"  시나리오 3 (질문 — '얼마나 걸려요?', '어떻게 진행돼요?'):\n"
        f"    질문에 직접 답변 후 다시 시작 여부 확인.\n"
        f"    '5개 영역 모두 합치면 2-3시간 정도 걸립니다. 영역마다 "
        f"30분 정도 예상하시면 됩니다. 시작할 준비 되셨으면 알려주세요.'\n\n"
        f"  → 모든 부정 응대에서 [START_CHAPTER] 태그 X.\n"
        f"  → 다음 턴에 사용자 답변 보고 다시 분기.\n\n"
        f"**절대 금지**:\n"
        f"- BEI 질문 미리 시작\n"
        f"- 첫 영역 진입\n\n"
        f"[START_CHAPTER] 태그 포함 시 다음 턴부터 ALIGN → CHAPTER_OPENING "
        f"으로 이어집니다. 사용자가 정의를 답변하면 자동으로 진행됩니다."
    )


def _build_chapter_opening_guide(state: dict | None) -> str:
    """CHAPTER_OPENING 가이드: BEI 질문 1-2문장만 생성 (하이브리드).

    시스템이 세션 오프닝 스크립트(30분 안내, 파트너 약속, 첫 역량 소개)를
    이미 앞에 붙였습니다. 당신은 BEI 질문만 출력하세요.
    """
    first_sub = (state or {}).get("first_subcompetency_name", "")
    sub_hint = f"'{first_sub}'" if first_sub else "첫 번째 세부역량"

    return (
        f"이 응답은 하이브리드입니다:\n"
        f"- 시스템 → 세션 오프닝 스크립트 (이미 출력됨)\n"
        f"- LLM (당신) → {sub_hint} 관련 BEI 질문 1-2문장만\n\n"
        f"**당신이 출력해야 할 것**: {sub_hint}에 관한 BEI 경험 질문 하나.\n\n"
        f"**BEI 질문 예시 (세부역량별)**:\n"
        f"  비전 제시 및 공유: '최근에 조직이나 팀의 비전을 새로 세우거나 "
        f"공유하셨던 경험이 있으세요?'\n"
        f"  목표설정 및 공유: '최근에 팀의 목표를 설정하거나 구성원과 "
        f"공유하셨던 경험이 있으세요?'\n"
        f"  갈등관리: '최근에 팀 내에서 갈등 상황을 다루셨던 경험이 있으세요?'\n"
        f"  업무계획 및 조직력: '최근에 업무 계획을 세우거나 팀 업무를 "
        f"배분하셨던 경험이 있으세요?'\n"
        f"  자기인식: '최근에 자신의 리더십 방식을 되돌아보신 경험이 있으세요?'\n\n"
        f"**⛔ 절대 금지 (시스템이 이미 출력했으므로)**:\n"
        f"- '리더님, 첫 번째 세션 시작해볼게요' → 시스템 담당\n"
        f"- '30분 정도' 시간 안내 → 시스템 담당\n"
        f"- '파트너로 있겠습니다' 약속 → 시스템 담당\n"
        f"- '첫 번째 세부 역량인 ...' 소개 → 시스템 담당\n"
        f"- 역량 정의 재설명 (방금 합의 완료)\n"
        f"- 한 번에 두 가지 이상 질문\n\n"
        f"BEI 질문 1-2문장만 출력하고 끝내세요."
    )


def _get_instruction_guide(
    instruction: str,
    state: dict | None = None,
) -> str:
    """각 instruction 에 따른 LLM 행동 가이드."""

    if instruction == "RAPPORT_BUILDING":
        return _build_rapport_guide(state)

    if instruction == "DIAGNOSIS_CONFIRM":
        return _build_confirm_guide(state)

    guides = {
        "COMPETENCY_INTRO": _build_competency_intro_guide(state),
        "COMPETENCY_ALIGN": (
            "역량 정의 합의 — 호응 부분(paraphrase + 칭찬)만 생성하는 단계.\n\n"
            "이 응답은 하이브리드입니다:\n"
            "- LLM (당신) → 호응 부분만 생성 (2-3문장)\n"
            "- 시스템 → 정의 + 세부역량 + 합의 질문을 자동 추가\n"
            "따라서 당신은 호응 부분만 출력하고 끝내세요.\n\n"
            "**필수 응답 형식 (2-3문장)**:\n"
            "1. 사용자 답변을 구체적으로 paraphrase\n"
            "2. 칭찬 한 마디\n\n"
            "**예시 (조직관리, 사용자: '조직을 효율적으로 관리하는 것이요')**:\n"
            "  '리더님께서는 조직관리를 조직을 효율적으로 관리하는 것으로 "
            "보시는 거군요. 정말 핵심을 잘 짚어주셨습니다.'\n\n"
            "**예시 (사람관리, 사용자: '팀원들 잘 챙기는 거요')**:\n"
            "  '리더님께서는 사람관리를 팀원들을 잘 챙기는 것으로 보시는 "
            "거군요. 정말 중요한 부분을 잘 짚어주셨습니다.'\n\n"
            "**⛔ 절대 금지 (시스템이 자동 추가하므로 출력 X)**:\n"
            "- '저희 진단에서는 ... 으로 정의하고 있습니다' → 시스템 담당\n"
            "- 세부역량 목록 ('4가지 세부 역량은 ...') → 시스템 담당\n"
            "- '이 N가지를 중심으로 이야기 나눠봐도 괜찮으시겠어요?' "
            "→ 시스템 담당\n"
            "- BEI 질문 (사건/경험 묻기)\n"
            "- 3문장 초과 (길게 늘어쓰기 금지)\n\n"
            "톤: 페르소나 살리되 호응 부분만 출력하고 끝내기."
        ),
        "CHAPTER_OPENING": _build_chapter_opening_guide(state),
        "DIAGNOSIS_INTRO": (
            "진단 안내 — 호응 1문장만 생성하는 단계입니다.\n\n"
            "⚠️ 매우 중요: 지금은 대화 중반입니다. 이미 라포 단계에서 "
            "인사와 자기소개를 마쳤습니다. 사용자와 이미 친밀한 대화를 "
            "나누는 중입니다.\n\n"
            "이 응답은 하이브리드입니다:\n"
            "- LLM (당신) → 사용자 기대 답변에 대한 호응 (딱 1문장)\n"
            "- 시스템 → 진단 안내 본문 자동 추가\n"
            "따라서 당신은 호응 1문장만 출력하세요.\n\n"
            "**필수 응답 형식 (딱 1문장)**:\n"
            "사용자가 방금 말한 '기대하는 것'을 짧게 받아주는 1문장.\n\n"
            "**예시 (사용자: '저의 리더십 역량을 파악하고 싶어요')**:\n"
            "  '리더십 역량을 객관적으로 파악하고 싶으신 거군요, "
            "좋은 동기예요.'\n\n"
            "**예시 (사용자: '강점과 약점을 알고 싶어요')**:\n"
            "  '강점과 약점을 균형 있게 보고 싶으신 마음, 잘 알겠습니다.'\n\n"
            "**예시 (사용자: '잘 모르겠어요')**:\n"
            "  '편하게 진행하시면 자연스럽게 드러날 거예요.'\n\n"
            "**⛔ 절대 금지**:\n"
            "- 인사 ('안녕하세요', '반갑습니다') — 이미 라포에서 함, 절대 X\n"
            "- 자기소개 ('따뜻한 코치 Ella입니다', '코치 엘라예요') 절대 X\n"
            "- '만나 뵙게 되어 기뻐요/반갑습니다' 류 첫 만남 표현 절대 X\n"
            "- '오늘 이렇게' 류 처음 만나는 톤 절대 X\n"
            "- 진단 안내 본문 ('진단은 평가가 아니라', '5개 영역' 등) "
            "→ 시스템 담당, X\n"
            "- '그럼 시작해볼까요?' 마무리 질문 → 시스템 담당, X\n"
            "- 2문장 이상 — 딱 1문장\n\n"
            "핵심: 당신은 이미 사용자와 대화 중입니다. 새로 인사하지 말고, "
            "방금 들은 답변에 1문장으로 공감만 하세요. 안내 본문은 시스템이 "
            "이어서 출력합니다."
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
            "**⛔ 호응 시 추가 주의 (맥락 오류·반복 방지)**:\n\n"
            "1. 호응어 다양화: 매번 '아,'로 시작 금지. '네,', '음,', "
            "'그렇군요,' 또는 바로 내용으로. 같은 시작어 2턴 연속 금지.\n\n"
            "2. 과한 반영 금지: 사용자가 간단히 답했는데 없는 디테일로 "
            "생생하게 묘사 X.\n"
            "   나쁜 예: User '올해 운영 방향, 전략 이야기했어요' (간단)\n"
            "           LLM '당시 회의 모습이 조금씩 그려지네요'"
            " ← 없는 장면 상상\n"
            "   좋은 예: LLM '팀 방향을 함께 정리하는 자리였군요. "
            "특히 강조하신 부분이 있으세요?'\n\n"
            "3. 호응 강도 비례: 짧고 추상적 답변 → 가볍게 받고 바로 "
            "구체화 질문. 구체적 디테일이 있을 때만 생생한 반영 사용.\n\n"
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
            "사용자가 시스템에 대해 물었거나 진행 흐름에 항의하고 있습니다.\n\n"
            "**항의 유형 ('얘기한 적 없는데요', '그런 말 안 했어요'):**\n"
            "1. 먼저 사과·인정: '죄송합니다, 제가 잘못 이해했네요.'\n"
            "2. 스크립트 강행 금지. 이전 흐름으로 억지 복귀 X.\n"
            "3. 리더님 답변 다시 확인 후 올바르게 재정렬.\n"
            "   예: '제가 앞서 말씀하신 내용을 잘못 해석했습니다. "
            "다시 한번 여쭤봐도 될까요?'\n\n"
            "**메타 질문 유형 ('진단이 뭐예요?', '얼마나 걸려요?'):**\n"
            "짧게 직접 답변 후 부드럽게 흐름 복귀.\n\n"
            "원칙: 사과 먼저, 강행 금지, 리더님 주도로 재정렬."
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
