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


def build_rapport_greeting(coach_name: str) -> str:
    """라포 첫 인사 동적 생성.

    환영 + 의미 부여 (강점 발견 여정) + 시간 + 에너지 질문 4단 구조.
    """
    time_info = get_time_greeting()
    hour_text = time_info["hour_text"]
    time_tone = time_info["tone"]

    return (
        f"반갑습니다, 리더님! 오늘 진단을 진행할 코치 {coach_name}입니다.\n\n"
        f"이 진단은 평가가 아니라, 리더님만의 고유한 강점을 발견하고 "
        f"빛내는 여정이에요. 편안하게 이야기를 나누며 함께 찾아가 봐요.\n\n"
        f"벌써 {hour_text} 무렵이네요. {time_tone} 시간 속에서 어떤 "
        f"에너지로 시간을 보내고 계신가요?\n\n"
        f"혹시 제가 리더님의 성함을 어떻게 부르면 좋을지 "
        f"알려주실 수 있을까요?"
    )
