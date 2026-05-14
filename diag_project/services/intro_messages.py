"""진단 안내 등 표준 메시지 생성

LLM 이 가이드 텍스트를 학습 데이터 패턴으로 변형하는 문제를 방지하기 위해
표준 텍스트는 시스템이 직접 출력.
"""

from diag_project.data.competencies import COMPETENCY_FRAMEWORK


def build_diagnosis_intro_message(user_name: str = "리더님") -> str:
    """진단 안내 메시지 생성.

    Args:
        user_name: 사용자 호칭 (기본값 "리더님")

    Returns:
        진단 안내 메시지
    """
    return (
        f"{user_name}, 본격적으로 시작하기 전에 진단에 대해 잠깐 "
        f"안내드리겠습니다.\n\n"
        f"오늘 함께할 진단은 5개 영역의 리더십 진단입니다. "
        f"조직관리, 성과관리, 사람관리, 일관리, 자기관리 — "
        f"이 다섯 가지 영역을 차례로 살펴볼 예정입니다.\n\n"
        f"각 영역마다 약 30분 정도 소요되며, 전체적으로는 2-3시간 "
        f"정도가 걸립니다. 한 번에 모두 진행하지 않으셔도 괜찮으며, "
        f"중간에 저장하고 나중에 다시 이어가실 수 있습니다.\n\n"
        f"진단 방식은 평가가 아니라 리더님의 실제 경험을 바탕으로 "
        f"자연스럽게 대화를 나누는 형식입니다. 정답이 정해져 있지 "
        f"않으니 편하게 말씀해주시면 됩니다.\n\n"
        f"이렇게 진행될 예정입니다. 이해되셨을까요?"
    )


def build_competency_align_message(
    chapter: str,
    user_answer: str | None = None,
) -> str:
    """역량 정의 합의 메시지 생성 (시스템 표준 텍스트).

    COMPETENCY_FRAMEWORK 에서 해당 챕터의 역량 정의와 세부 역량 목록을 읽어
    리더님께 제시하고 합의 여부를 묻는다.

    Args:
        chapter: 챕터 키 (예: "organization_management")
        user_answer: 직전 사용자 답변 (있으면 공감 문장 prepend)

    Returns:
        역량 정의 합의 메시지
    """
    competency = COMPETENCY_FRAMEWORK.get(chapter, {})
    name = competency.get("name", "해당 역량")
    description = competency.get("description", "")
    indicators = competency.get("indicators", {})
    indicator_names = [v["name"] for v in indicators.values()]
    n = len(indicator_names)
    bullets = "\n".join(f"- {ind}" for ind in indicator_names)

    if user_answer and user_answer.strip():
        opener = (
            "네, 리더님 말씀 잘 들었습니다. "
            "리더님이 보시는 관점도 충분히 이해됩니다.\n\n"
        )
    else:
        opener = "네, 리더님 말씀 감사합니다.\n\n"

    return (
        f"{opener}"
        f"저희가 보는 {name}는 '{description}' 으로 정의하고 있습니다.\n\n"
        f"이 역량은 {n}가지 세부 역량으로 구성됩니다:\n"
        f"{bullets}\n\n"
        f"이 {n}가지를 중심으로 이야기 나눠봐도 괜찮으시겠어요?"
    )
