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

    if hour == 0:
        hour_text = "자정 무렵"
    elif hour < 12:
        hour_text = f"오전 {hour}시"
    elif hour == 12:
        hour_text = "정오"
    else:
        hour_text = f"오후 {hour - 12}시"

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

    Args:
        coach_name: 코치 이름 (예: "Ella (엘라)" 또는 "Ella")

    Returns:
        완성된 라포 인사 메시지
    """
    time_info = get_time_greeting()

    return (
        f"안녕하세요, 리더님! AI 리더십 코치 {coach_name}입니다.\n\n"
        f"{time_info['hour_text']} 무렵, {time_info['tone']} 시간을 "
        f"보내고 계신가요? {time_info['reflective_phrase']}\n\n"
        f"혹시 제가 리더님의 성함을 어떻게 부르면 좋을지 "
        f"알려주실 수 있을까요?"
    )
