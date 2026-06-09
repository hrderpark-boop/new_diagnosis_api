"""진단 안내 등 표준 메시지 생성

LLM 이 가이드 텍스트를 학습 데이터 패턴으로 변형하는 문제를 방지하기 위해
표준 텍스트는 시스템이 직접 출력.
"""

import random

from diag_project.data.competencies import COMPETENCY_FRAMEWORK

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

    # 중립적 정의 제시 (Step 6). '맞닿아 있다'는 식의 평가는 하지 않음 —
    # 그 판단(공감/유연 분기)은 LLM 호응 부분이 담당 (무성의 답변 환각 방지).
    return (
        f"저희 진단에서는 {name}를 '{description}'으로 봅니다.\n\n"
        f"이 역량은 현업에서 보통 이런 {indicator_count}가지 모습으로 "
        f"드러나곤 하는데요:\n"
        f"{indicator_list}\n\n"
        f"이제 이 결을 따라, 리더님의 실제 경험을 하나씩 들여다볼게요."
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


def build_chapter_opening_with_user_def(
    chapter: str,
    user_definition: str,
    first_subcompetency_name: str,
) -> str:
    """CHAPTER_OPENING (Step 7) — 첫 BEI(경험) 질문.

    공식 정의·하위역량 소개는 직전 Step 6(COMPETENCY_ALIGN)에서 이미 했으므로
    여기서는 반복하지 않고, 첫 세부역량에 관한 구체적 경험만 부드럽게 묻는다.

    user_definition 은 호환을 위해 유지하나 본문에서는 사용하지 않음
    (정의 반복 방지).
    """
    framework = COMPETENCY_FRAMEWORK.get(chapter, {})
    chapter_name = framework.get("name", "이 역량")
    first_sub = first_subcompetency_name or f"{chapter_name} 관련 역량"

    return (
        f"그럼 이제 리더님의 실제 경험을 들어볼게요.\n\n"
        f"가장 최근 6개월 안에 '{first_sub}'와 관련해서 리더십을 "
        f"발휘하셨던 구체적인 경험이 있으실까요? 어떤 상황이었고 어떻게 "
        f"대응하셨는지, 떠오르시는 장면 하나면 충분합니다."
    )
