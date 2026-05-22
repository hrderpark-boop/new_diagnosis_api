"""진단 안내 등 표준 메시지 생성

LLM 이 가이드 텍스트를 학습 데이터 패턴으로 변형하는 문제를 방지하기 위해
표준 텍스트는 시스템이 직접 출력.
"""

import random

from diag_project.data.competencies import COMPETENCY_FRAMEWORK

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
    """진단 안내 본문 (호응 제외) — 간결 버전.

    하이브리드 INTRO 흐름에서 시스템이 직접 출력하는 부분.
    LLM 이 생성하는 호응 부분은 별도로 앞에 붙음.

    5개 영역·소요 시간은 사용자가 묻거나 꼭 필요할 때만 안내.
    여기서는 "평가 아닌 대화" 핵심만 짧게 전달.
    """
    return (
        "진단은 평가가 아니라, 리더님의 실제 경험을 바탕으로 "
        "대화하듯 이야기 나누는 형식이에요. 정답은 없으니 "
        "편하게 말씀해 주시면 됩니다.\n\n"
        "중간에 저장하고 나중에 이어가실 수 있으니 "
        "부담 없이 참여하시면 됩니다. 그럼 시작해볼까요?"
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

    return (
        f"저희 진단에서는 {name}를 '{description}' 으로 정의하고 "
        f"있습니다. 리더님의 생각과도 일맥상통하는 부분이 많죠?\n\n"
        f"이 역량은 {indicator_count}가지 세부 역량으로 구성됩니다:\n"
        f"{indicator_list}\n\n"
        f"이 {indicator_count}가지를 중심으로 이야기 나눠봐도 "
        f"괜찮으시겠어요?"
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
