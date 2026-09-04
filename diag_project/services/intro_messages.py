"""진단 안내 등 표준 메시지 생성

LLM 이 가이드 텍스트를 학습 데이터 패턴으로 변형하는 문제를 방지하기 위해
표준 텍스트는 시스템이 직접 출력.
"""

import random

from diag_project.data.competencies import (
    COMPETENCY_FRAMEWORK,
    SUBCOMPETENCY_ANCHORS,  # noqa: F401  (situation 서술 — 분석·게이트용, 호환 유지)
    get_anchor_questions,
)

# 5개 챕터의 진단 정의 (LLM 이 아닌 시스템이 직접 사용)
CHAPTER_DEFINITIONS = {
    "organization_management": (
        "조직의 비전과 전략을 구성원과 정렬하고, 자원을 효과적으로 배분하여 "
        "조직 전체가 한 방향으로 움직이도록 만드는 역량"
    ),
    "performance_management": (
        "명확한 목표를 설정하고 진척을 관리하며, 객관적인 피드백을 통해 "
        "구성원의 성과 창출을 견인하는 역량"
    ),
    "people_management": (
        "구성원과 신뢰 관계를 구축하고, 동기를 부여하며, "
        "잠재력을 발휘할 수 있도록 코칭하고 육성하는 역량"
    ),
    "work_management": (
        "업무의 우선순위를 정하고 효율적으로 실행하며, "
        "협업과 자원 활용을 최적화하는 역량"
    ),
    "self_management": (
        "자신의 감정과 시간, 학습을 객관적으로 인식하고 관리하여 "
        "지속 가능한 리더십을 발휘하는 역량"
    ),
}

_ACKNOWLEDGMENT_PATTERNS = {
    "short": [
        "네, 그렇게 보실 수 있어요. 큰 틀에서 그게 맞죠.",
        "네, 맞아요. 기본적으로 그 의미가 핵심이죠.",
        "그렇죠. 가장 단순하게 표현하면 그게 맞아요.",
    ],
    "long": [
        "네, 리더님 말씀 잘 들었습니다. 리더님이 보시는 관점도 충분히 이해됩니다.",
        "네, 깊이 있게 보고 계시네요. 리더님 관점 잘 들었습니다.",
        "리더님의 시각이 잘 느껴집니다. 말씀해주신 부분 잘 들었어요.",
    ],
    "default": [
        "네, 리더님 말씀 감사합니다.",
    ],
}


def _select_acknowledgment(user_answer: str | None) -> str:
    """사용자 답변 길이에 따라 호응 패턴 선택."""
    if not user_answer or len(user_answer.strip()) == 0:
        return _ACKNOWLEDGMENT_PATTERNS["default"][0]
    length = len(user_answer.strip())
    if length <= 15:
        return random.choice(_ACKNOWLEDGMENT_PATTERNS["short"])
    return random.choice(_ACKNOWLEDGMENT_PATTERNS["long"])


def build_diagnosis_intro_message(user_name: str = "리더님") -> str:
    """[DEPRECATED] 작업 24 이후 build_intro_anchor_section + LLM 호응 사용.

    하이브리드 INTRO 패턴으로 전환됨. 이 함수는 legacy 호환용으로 보존.
    """
    return f"{user_name}, " + build_intro_anchor_section()


def build_intro_anchor_section() -> str:
    """진단 안내 본문 (5개 영역 + 총 시간 150분 + 형식).

    하이브리드 INTRO 흐름에서 시스템이 직접 출력하는 부분.
    LLM 이 생성하는 호응 2-3문장 뒤에 이어 붙음.
    """
    return (
        "그럼 오늘 진단이 어떻게 진행되는지 간단히 안내드릴게요.\n\n"
        "진단은 5개 영역으로 이루어져 있어요 — 조직관리, 성과관리, "
        "사람관리, 일관리, 자기관리.\n\n"
        "각 역량마다 약 30분 정도 소요되고 전체 150분 이상 예상됩니다. "
        "다만, 한 번에 다 진행하면 긴 시간이 소요되니 중간에 저장하고 "
        "시간되실 때마다 이어 참여하셔도 괜찮습니다.\n\n"
        "본 과정은 평가가 아니라 리더십의 경험을 함께 공유하는 시간이라 "
        "생각해주시고, 정답 걱정 없이 편하게 말씀해 주시기 바랍니다.\n\n"
        "그럼 시작해볼까요?"
    )


def build_align_framework_section(chapter: str) -> str:
    """ALIGN 메시지의 framework 부분만 생성 (호응 제외).

    하이브리드 ALIGN 흐름에서 시스템이 직접 출력하는 부분:
    정의 + 세부역량 목록 + 합의 질문.
    LLM 이 생성하는 호응 부분(paraphrase + 칭찬)은 별도로 앞에 붙음.

    Args:
        chapter: 영문 챕터 키 (예: "organization_management")

    Returns:
        framework 부분 텍스트 (호응 없음)
    """
    framework = COMPETENCY_FRAMEWORK.get(chapter)
    if not framework:
        return "역량 정보를 찾을 수 없습니다."

    name = framework["name"]
    description = framework["description"].rstrip(".")
    indicators = framework["indicators"]
    indicator_names = [ind["name"] for ind in indicators.values()]
    indicator_count = len(indicator_names)
    indicator_list = "\n".join(f"- {n}" for n in indicator_names)

    # Step 6 쿠션어: LLM 호응부('…리더님의 그 철학과 같은 맥락으로,')에서
    # 이어받아 한 호흡으로 묶어줌. 사용자 답변 반영(공감/유연 분기)은 LLM 담당.
    return (
        f"저희 진단에서는 이를 포괄하여 {name}를 '{description}'이라고 "
        f"정의하고 있습니다. 말씀하신 결이 이 맥락에 아주 자연스럽게 "
        f"녹아들죠?\n\n"
        f"이 역량의 하위 역량은 다음 {indicator_count}가지입니다:\n"
        f"{indicator_list}\n\n"
        f"앞으로 이 하위 역량들을 중심으로 리더님의 실제 경험을 "
        f"여쭤보려고 해요. 우리가 함께 진행할 역량에 대한 정의가 "
        f"충분히 이해되셨나요?"
    )


def build_chapter_opening_script(
    chapter: str, first_subcompetency: str
) -> str:
    """CHAPTER_OPENING 하이브리드에서 시스템이 직접 출력하는 세션 오프닝 스크립트.

    LLM 은 BEI 질문만 생성. 이 스크립트는 시스템이 앞에 붙임.

    Args:
        chapter: 영문 챕터 키 (예: "organization_management")
        first_subcompetency: 첫 번째 세부역량 이름 (예: "비전 제시 및 공유")
    """
    framework = COMPETENCY_FRAMEWORK.get(chapter)
    chapter_name = framework["name"] if framework else "이번 영역"

    return (
        f"리더님, 첫 번째 세션 시작해볼게요. 앞으로 약 30분 정도 "
        f"'{chapter_name}' 영역에 대해 이야기 나눌 거예요.\n\n"
        f"편하게 답하시면 되고, 생각이 필요한 질문은 천천히 떠올리셔도 "
        f"돼요. 답변이 애매하면 제가 다시 여쭤볼 수 있고요.\n\n"
        f"시작하기 전에 한 가지 약속드릴게요 — 제가 대화 중에 긍정적 "
        f"피드백이나 상황에 대한 판단을 덜 하는 편이에요. 칭찬보다는 "
        f"경험 자체에 집중하기 위해서예요. 저는 리더님의 경험을 함께 "
        f"보는 파트너로 있겠습니다.\n\n"
        f"그럼 첫 번째 세부 역량인 '{first_subcompetency}'부터 시작하겠습니다."
    )


# Deprecated: 호응 포함 구버전. 하이브리드 전환 후 호출 안 함.
# build_align_framework_section + LLM 호응 방식으로 대체됨.
def build_competency_align_message(
    chapter: str,
    user_answer: str | None = None,
) -> str:
    """역량 정의 합의 메시지 생성 (호응 다양화).

    Args:
        chapter: 챕터 키 (예: "organization_management")
        user_answer: 직전 사용자 답변 (길이에 따라 호응 패턴 선택)

    Returns:
        역량 정의 합의 메시지
    """
    framework = COMPETENCY_FRAMEWORK.get(chapter)
    if not framework:
        return "역량 정보를 찾을 수 없습니다."

    name = framework["name"]
    description = framework["description"].rstrip(".")
    indicators = framework["indicators"]
    indicator_names = [ind["name"] for ind in indicators.values()]
    indicator_count = len(indicator_names)
    indicator_list = "\n".join(f"- {n}" for n in indicator_names)

    acknowledgment = _select_acknowledgment(user_answer)

    return (
        f"{acknowledgment}\n\n"
        f"저희가 정의하는 {name}는 '{description}' 으로 보고 있습니다.\n\n"
        f"이 역량은 {indicator_count}가지 세부 역량으로 구성됩니다:\n"
        f"{indicator_list}\n\n"
        f"이 {indicator_count}가지를 중심으로 이야기 나눠봐도 "
        f"괜찮으시겠어요?"
    )


_ONBOARDING_CHAPTER_ORDER = [
    "organization_management",
    "performance_management",
    "people_management",
    "work_management",
    "self_management",
]


def build_onboarding_launch(user_name: str) -> str:
    """온보딩 3-Step의 마지막 — 이름 수용 + 로드맵 + 첫 영역 첫 질문.

    코치 인사(시스템 첫 메시지)에서 이미 자기소개·진단 취지를 전했으므로
    이 턴에서는 자기소개·안부 반복 금지. 이름을 딱 한 문장으로 수용한 뒤
    바로 5개 영역 로드맵을 안내하고 첫 영역(조직관리)의 첫 질문으로 브릿지.

    LLM 호출 없이 시스템이 직접 출력 → 앵무새(반복) 현상 원천 차단.
    """
    names = [
        COMPETENCY_FRAMEWORK[k]["name"]
        for k in _ONBOARDING_CHAPTER_ORDER
        if k in COMPETENCY_FRAMEWORK
    ]
    roadmap = " · ".join(names) if names else "다섯 가지 리더십 영역"
    first_name = COMPETENCY_FRAMEWORK.get(
        "organization_management", {}
    ).get("name", "조직관리")

    return (
        f"반갑습니다, {user_name} 리더님!\n\n"
        f"그럼 바로 시작해볼게요. 오늘은 {roadmap}, 이렇게 다섯 영역을 "
        f"차례로 함께 살펴볼 텐데요. 평가가 아니라 리더님의 실제 경험을 "
        f"같이 들여다보는 자리이니, 정답 걱정 없이 떠오르는 대로 편하게 "
        f"말씀해 주시면 됩니다. 중간에 저장하고 이어서 하셔도 괜찮아요.\n\n"
        f"첫 영역인 '{first_name}'부터 가볍게 열어볼게요. 리더님께 "
        f"'{first_name}' 하면 가장 먼저 떠오르는 장면이나 생각이 "
        f"있으세요? [START_CHAPTER]"
    )


# (제거됨) build_chapter_thought_question — 전환 예고 뒤에 시스템이 덧붙이던
#   '다음 역량 생각 질문' 풀. "'성과관리'을 챙긴다는 건…" 조사 오류의 출처였고,
#   정의 질문(COMPETENCY_ASK)이 두 번 나가는 순서 어긋남을 만들었다.
#   전환 턴은 예고에서 끝내고, 정의 질문은 다음 턴 COMPETENCY_ASK 가 던진다.


# item4: 첫 BEI 앵커 질문 '문장 틀' 풀 — LLM 대신 백엔드 결정론 변주.
#   챕터 순서로 프레임을 골라 5개 챕터가 모두 다른 틀을 쓴다(무반복). 모든 틀은
#   'BEI 앵커 제약'을 구조적으로 보장한다: 시점(최근/근래) + 리더가 '직접 한 행동'
#   + 구체 경험/사례/장면 요구, 은유·비유 없음. {sub}=첫 하위역량(백엔드 주입).
# #2(2026-09-04): 앵커 질문에서 하위역량 '이름'을 노출하지 않는다. 본문은
#   SUBCOMPETENCY_ANCHOR_QUESTIONS 의 대화체 질문({question})이 맡고, 프레임은
#   도입 한 마디 또는 부담을 낮추는 평서문 한 줄만 담는다(이중 질문 금지).
#   (로그 근거: "'전략적 사고'와 관련해서 경험이…" → "그게 뭔지 너무 어려워요",
#    상황 묘사 앵커 → 바로 사례. AI 는 무엇을 재는지 알되 대상자에겐 안 보인다.)
_ANCHOR_FRAMES = [
    "먼저 하나 여쭤볼게요. {question}",
    "가볍게 시작해 볼게요. {question}",
    "{question} 떠오르는 장면 하나면 충분합니다.",
    "실제 있었던 일로 시작해 볼게요. {question}",
    "{question} 잘한 일이 아니어도 괜찮아요.",
    "바로 여쭤볼게요. {question}",
    "{question} 언제, 누구와 있었던 일인지부터 편하게요.",
    "이 영역은 이 질문부터요. {question}",
]
# 브릿지(직전 답변 이어받기) 리드도 챕터 순서로 순환.
_BRIDGE_LEADS = [
    "방금 '{ctx}' 이야기를 들으면서, 리더님이 그런 순간들을 어떻게 "
    "마주해오셨는지가 더 궁금해졌어요.",
    "'{ctx}' 하시던 그 결이 마음에 남네요. 그 이야기에서 한 걸음 더 들어가 볼게요.",
    "조금 전 '{ctx}' 말씀이 계속 맴도네요. 그 흐름을 그대로 이어서 여쭤볼게요.",
    "'{ctx}' 이야기, 잘 들었어요. 자연스럽게 다음 이야기로 이어가 볼게요.",
    "방금 들려주신 '{ctx}' 경험이 인상적이었어요. 이어서 하나 더 여쭤볼게요.",
]

_OPEN_CHAPTER_ORDER = [
    k for k in COMPETENCY_FRAMEWORK.keys() if k != "supplementary"
]


def build_chapter_opening_with_user_def(
    chapter: str,
    user_definition: str,
    first_subcompetency_name: str,
    bridge_context: str | None = None,
) -> str:
    """CHAPTER_OPENING (Step 7) — 하위역량 타겟팅 기반 첫 BEI 질문.

    대주제로 뭉뚱그린 질문('이 역량 관련 경험 있으세요?')은 답하기 어렵다.
    Step 6 에서 소개한 하위 역량의 SUBCOMPETENCY_ANCHORS(현업 딜레마/갈등
    상황)를 앵커로 녹여 시작한다.

    bridge_context (직전 챕터에서 리더가 들려준 사건의 핵심 키워드/요약)가
    있으면 '목차 노출형'(역량명/하위역량명 직접 호명)을 폐기하고, 그 키워드에서
    파생되는 '대화형 브릿지 질문'으로 시작한다 → 대화가 이전 답변에서
    자연스럽게 이어지는 느낌을 준다. (첫 챕터 등 브릿지가 없으면 기존 방식)

    user_definition 은 호환을 위해 유지하나 본문에서는 사용하지 않음.
    """
    framework = COMPETENCY_FRAMEWORK.get(chapter, {})
    chapter_name = framework.get("name", "이 역량")
    indicators = framework.get("indicators", {})

    # 첫 하위역량을 결정론적으로 타겟 (하위역량 릴레이 추적과 순서 일치).
    # 첫 사건은 항상 sub[0] 을 다룬 것으로 간주됨.
    keys = list(indicators.keys())
    first_key = keys[0] if keys else None
    first_name = (
        indicators[first_key].get("name", "") if first_key else ""
    ) or first_subcompetency_name or chapter_name

    # item4: 문장 틀·질문을 챕터 순서로 결정론 선택 → 5개 챕터 모두 다르게
    #   (무반복). 타겟(first_key)은 백엔드가 정하고 문장만 변주 = 제어 역전 유지.
    _pos = (_OPEN_CHAPTER_ORDER.index(chapter)
            if chapter in _OPEN_CHAPTER_ORDER else 0)
    # #2: 첫 하위역량의 대화체 앵커 질문(이름 미노출) — 결정론(챕터 순서 기반).
    questions = get_anchor_questions(first_key) if first_key else []
    if questions:
        question = questions[_pos % len(questions)]
    else:
        # 질문 사전에 없는 키(방어) — 이름 대신 일반 상황 질문.
        question = "최근에 리더님이 직접 나서서 풀어야 했던 일이 하나 있으셨어요?"
    _frame = _ANCHOR_FRAMES[_pos % len(_ANCHOR_FRAMES)].format(question=question)
    del first_name  # 이름은 질문에 쓰지 않는다(호환 인자만 유지)

    # 🌉 브릿지 모드: 직전 답변 키워드에서 파생되는 대화형 리드 + 앵커 질문.
    #   리드가 이미 도입 역할을 하므로 프레임 도입은 빼고 질문 본문만 잇는다
    #   ("…들어가 볼게요. 가볍게 시작해 볼게요." 이중 도입 방지).
    if bridge_context:
        _ctx = bridge_context.strip().rstrip(".!?~ ")
        _lead = _BRIDGE_LEADS[_pos % len(_BRIDGE_LEADS)].format(ctx=_ctx)
        return f"{_lead} {question}"

    # (브릿지 없음 — 첫 챕터 등) 하위역량 타겟 앵커 질문.
    return _frame


def build_chapter_transition_question(chapter: str) -> str:
    """종결+전환 하이브리드의 '안전장치' — LLM 이 계속/휴식 질문을 빠뜨렸을 때만 사용.

    CHAPTER_READY_TO_END 에서 LLM 은 wrap-up(요약+공감) + '계속/휴식 의사 질문'을
    직접 생성한다(layer3_state 프롬프트). 만약 LLM 이 질문을 누락하면, 요약·공감만
    으로 대화가 어색하게 끝나므로 이 함수의 다변화된 계속/휴식 질문을 시스템이
    덧붙인다. (다음 역량의 '내용 질문'이 아니라 '지금 이어갈지/쉴지' 의사 확인)
    """
    framework = COMPETENCY_FRAMEWORK.get(chapter, {})
    name = framework.get("name", "다음 영역")
    variations = [
        f"한숨 돌리고 다음 '{name}' 진단으로 넘어갈까요, 아니면 잠시 "
        f"쉬었다가 이어갈까요?",
        f"바로 이어서 '{name}' 이야기를 살펴봐도 괜찮으실까요? 잠깐 "
        f"쉬어가고 싶으시면 편하게 말씀해 주세요.",
        f"이대로 '{name}'까지 계속 이어가 볼까요, 아니면 여기서 잠깐 "
        f"숨을 돌리고 갈까요?",
        f"괜찮으시면 다음 '{name}' 영역으로 이어가 볼게요 — 혹시 잠시 "
        f"쉬고 싶으시면 그렇게 하셔도 좋아요.",
    ]
    return random.choice(variations)
