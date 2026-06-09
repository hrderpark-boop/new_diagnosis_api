"""시간대 기반 인사말 생성 헬퍼

Phase 3-A 라포 인사에서 동적으로 사용.
서버 시간 기준 (Asia/Seoul).
"""

from datetime import datetime
from zoneinfo import ZoneInfo


def get_time_greeting() -> dict[str, str]:
    """현재 시간 기반 인사 정보 생성.

    Returns:
        {
            "hour_text": "오후 3시" 등,
            "tone": "활기찬 오후" 등 시간대 톤,
            "ampm_phrase": "오후" 등,
            "reflective_phrase": 시간대에 맞는 두 번째 문장,
        }
    """
    seoul = ZoneInfo("Asia/Seoul")
    now = datetime.now(seoul)
    hour = now.hour
    minute = now.minute

    # hour_text 용: 분 30 이상이면 다음 시로 반올림
    rounded_hour = (hour + 1) % 24 if minute >= 30 else hour

    if rounded_hour == 0:
        hour_text = "자정 무렵"
    elif rounded_hour < 12:
        hour_text = f"오전 {rounded_hour}시"
    elif rounded_hour == 12:
        hour_text = "정오"
    else:
        hour_text = f"오후 {rounded_hour - 12}시"

    # 시간대 톤 분류는 원래 hour 사용 (사용자 활동 시간대 기준)
    if 5 <= hour < 8:
        tone = "이른 아침"
        ampm_phrase = "이른 아침"
        reflective_phrase = (
            "이른 아침부터 시간 내주셨네요. "
            "차분한 마음으로 시작해보면 좋을 것 같아요."
        )
    elif 8 <= hour < 12:
        tone = "상쾌한 아침"
        ampm_phrase = "오전"
        reflective_phrase = (
            "하루를 새롭게 열어가는 시간이네요. "
            "잠시 마음을 정돈하며 시작해볼까요?"
        )
    elif 12 <= hour < 14:
        tone = "분주한 점심"
        ampm_phrase = "점심"
        reflective_phrase = (
            "한창 분주하실 시간에 함께해주셔서 고맙습니다. "
            "잠깐 호흡 가다듬는 시간이 됐으면 좋겠어요."
        )
    elif 14 <= hour < 17:
        tone = "활기찬 오후"
        ampm_phrase = "오후"
        reflective_phrase = (
            "오후의 흐름 속에서 잠깐 한 호흡 쉬어가는 "
            "시간이 됐으면 좋겠어요."
        )
    elif 17 <= hour < 20:
        tone = "차분한 저녁"
        ampm_phrase = "저녁"
        reflective_phrase = (
            "하루를 마무리해가는 시간이네요. "
            "잠시 돌아보는 시간이 될 것 같아요."
        )
    elif 20 <= hour < 23:
        tone = "조용한 밤"
        ampm_phrase = "밤"
        reflective_phrase = (
            "오늘 하루를 차분히 돌아보기 좋은 시간이네요. "
            "편안하게 함께해요."
        )
    else:
        tone = "늦은 시간"
        ampm_phrase = "늦은 시간"
        reflective_phrase = (
            "늦은 시간까지 시간 내주셔서 고맙습니다. "
            "무리 없이 진행할게요."
        )

    return {
        "hour_text": hour_text,
        "tone": tone,
        "ampm_phrase": ampm_phrase,
        "reflective_phrase": reflective_phrase,
    }


def get_time_phrase() -> str:
    """첫 인사 템플릿용 간결한 시간대 문구.

    Returns: 예) "활기찬 아침", "오전", "점심 무렵", "오후 3시 무렵", "저녁", "늦은 시간"
    """
    seoul = ZoneInfo("Asia/Seoul")
    hour = datetime.now(seoul).hour

    if 5 <= hour < 10:
        return "활기찬 아침"
    elif 10 <= hour < 12:
        return "오전"
    elif 12 <= hour < 14:
        return "점심 무렵"
    elif 14 <= hour < 18:
        return f"오후 {hour - 12}시 무렵"
    elif 18 <= hour < 21:
        return "저녁"
    else:
        return "늦은 시간"


def build_rapport_first_turn_response(
    user_name: str,
    current_ampm_phrase: str,
) -> str:
    """라포 1턴 (이름 받은 직후) — Step 1 이름 수용 + Step 2 아이스브레이킹.

    [중요] 인사말(build_rapport_greeting)에서 이미 자기소개를 마쳤으므로
    여기서 코치 자기소개를 절대 반복하지 않는다 (앵무새 방지).
    이름을 딱 한 문장으로 수용한 뒤 가벼운 아이스브레이킹 질문 하나만.
    로드맵·진단 질문은 다음 스텝(별도 턴) 담당 — 절대 섞지 않음.
    """
    return (
        f"반갑습니다, {user_name} 리더님! "
        f"본격적으로 시작하기 전에 잠깐 편하게 이야기 나눠볼게요. "
        f"오늘 {current_ampm_phrase} 시간은 어떻게 보내고 계세요?"
    )


def build_rapport_greeting(coach_name: str) -> str:
    """라포 첫 인사 고정 템플릿.

    LLM 호출 없이 서버에서 직접 생성. 톤 고정 + Gemini 호출 1회 절약.
    """
    # Step 1: 자기소개 + 이름 요청만. (안부 질문은 라포 단계에서 — 중복 방지)
    return (
        f"반갑습니다, 리더님. 오늘 진단을 함께할 코치 {coach_name}입니다.\n\n"
        f"본 진단은 평가가 아니라, 리더님만의 고유한 강점을 발견하고 "
        f"역량을 극대화하기 위한 과정이에요. 편안한 마음으로 대화하듯 "
        f"함께해 주시면 됩니다.\n\n"
        f"시작에 앞서, 제가 리더님의 성함을 어떻게 부르면 좋을지 "
        f"먼저 알려주시겠어요?"
    )
