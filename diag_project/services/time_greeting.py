"""시간대 기반 인사말 생성 헬퍼

Phase 3-A 라포 인사에서 동적으로 사용.
서버 시간 기준 (Asia/Seoul).
"""

from datetime import datetime
from zoneinfo import ZoneInfo


# (2026-10-28 P0-6) 시간대 경계 — KST 기준. 05~11 오전 / 11~14 점심 / 14~18 오후 / 18~ 저녁(23시 이후는 '늦은 시간').
#   10/28 Lucas 세션: 13:49 에 "점심 시간" 이 나갔다(구 경계 12~14). 경계를 한 곳(이 표)에서만 정한다.
# (2026-10-29 P1, P0-6 경계 수정) 점심 11~13, 오후 13~18 — 13:49 는 오후.
# (2026-11-04 P3-5) 운영 Michael 11/4: 11:30 에 "점심 시간은 어떻게 보내고 계세요"가 나갔다 → 11~12 는 '오전 마무리', 점심은 12:00~13:30.
#   경계가 분 단위라 (시작 분, 끝 분, 이름). daypart(hour, minute) 로 판정.
DAYPART_BOUNDS = ((5 * 60, 11 * 60, "오전"), (11 * 60, 12 * 60, "오전 마무리"), (12 * 60, 13 * 60 + 30, "점심"),
                  (13 * 60 + 30, 18 * 60, "오후"), (18 * 60, 23 * 60, "저녁"))


def daypart(hour: int, minute: int = 0) -> str:
    m = int(hour) * 60 + int(minute)
    for lo, hi, name in DAYPART_BOUNDS:
        if lo <= m < hi:
            return name
    return "늦은 시간"


def current_daypart(now: datetime | None = None) -> str:
    """(2026-11-10 P9-2) 지금 시간대 이름(KST) — 스몰톡 되물음이 아직 오지 않은 시간대를 말하지 않게 가이드·가드에 넘긴다."""
    n = _now_seoul(now)
    return daypart(n.hour, n.minute)


def _now_seoul(now: datetime | None = None) -> datetime:
    seoul = ZoneInfo("Asia/Seoul")
    if now is None:
        return datetime.now(seoul)
    return now.astimezone(seoul) if now.tzinfo else now.replace(tzinfo=seoul)


def get_time_greeting(now: datetime | None = None) -> dict[str, str]:
    """현재 시간 기반 인사 정보 생성(now 는 테스트 주입용).

    Returns:
        {
            "hour_text": "오후 3시" 등,
            "tone": "활기찬 오후" 등 시간대 톤,
            "ampm_phrase": "오후" 등,
            "reflective_phrase": 시간대에 맞는 두 번째 문장,
        }
    """
    now = _now_seoul(now)
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

    # 시간대 톤 분류는 원래 hour 사용 (사용자 활동 시간대 기준) — 경계는 DAYPART_BOUNDS 하나로.
    part = daypart(hour, minute)
    if part == "오전":
        tone = "상쾌한 오전"
        ampm_phrase = "오전"
        reflective_phrase = (
            "하루를 새롭게 열어가는 시간이네요. "
            "잠시 마음을 정돈하며 시작해볼까요?"
        )
    elif part == "오전 마무리":
        tone = "오전 마무리"
        ampm_phrase = "오전 마무리"
        reflective_phrase = (
            "오전을 마무리하는 시간에 함께해주셔서 고맙습니다. "
            "잠깐 호흡 가다듬는 시간이 됐으면 좋겠어요."
        )
    elif part == "점심":
        tone = "분주한 점심"
        ampm_phrase = "점심"
        reflective_phrase = (
            "한창 분주하실 시간에 함께해주셔서 고맙습니다. "
            "잠깐 호흡 가다듬는 시간이 됐으면 좋겠어요."
        )
    elif part == "오후":
        tone = "활기찬 오후"
        ampm_phrase = "오후"
        reflective_phrase = (
            "오후의 흐름 속에서 잠깐 한 호흡 쉬어가는 "
            "시간이 됐으면 좋겠어요."
        )
    elif part == "저녁":
        tone = "차분한 저녁"
        ampm_phrase = "저녁"
        reflective_phrase = (
            "하루를 마무리해가는 시간이네요. "
            "잠시 돌아보는 시간이 될 것 같아요."
        )
    else:
        tone = "늦은 시간"
        ampm_phrase = "늦은 시간"
        reflective_phrase = (
            "늦은 시간까지 시간 내주셔서 고맙습니다. "
            "무리 없이 진행할게요."
        )

    # (2026-11-04 P3-5) 라포 첫 턴 안부 질문 — '오전 마무리'는 "오전 마무리는 어떠세요?", 그 밖은 "[시간대] 시간은 어떻게 보내고 계세요?"
    greeting_question = ("오전 마무리는 어떠세요?" if part == "오전 마무리"
                         else "오늘 하루는 어떻게 보내셨어요?" if part == "늦은 시간"      # (2026-11-10 p9c) '오늘 늦은 시간 시간은 …' 낱말 중복
                         else f"오늘 {ampm_phrase} 시간은 어떻게 보내고 계세요?")
    return {
        "hour_text": hour_text,
        "tone": tone,
        "ampm_phrase": ampm_phrase,
        "reflective_phrase": reflective_phrase,
        "greeting_question": greeting_question,
    }


def get_time_phrase(now: datetime | None = None) -> str:
    """첫 인사 템플릿용 간결한 시간대 문구(now 는 테스트 주입용).

    Returns: 예) "오전", "점심 무렵", "오후 3시 무렵", "저녁", "늦은 시간"
    """
    now = _now_seoul(now)
    hour = now.hour
    part = daypart(hour, now.minute)
    if part in ("오전", "오전 마무리"):
        return "오전"
    if part == "점심":
        return "점심 무렵"
    if part == "오후":
        return f"오후 {hour - 12}시 무렵"
    if part == "저녁":
        return "저녁"
    return "늦은 시간"


def build_rapport_first_turn_response(
    user_name: str | None,
    current_ampm_phrase: str,
    is_hostile: bool = False,
    greeting_question: str | None = None,
) -> str:
    """라포 1턴 (이름 받은 직후) — Step 1 이름 수용 + Step 2 아이스브레이킹.

    [중요] 인사말(build_rapport_greeting)에서 이미 자기소개를 마쳤으므로
    여기서 코치 자기소개를 절대 반복하지 않는다 (앵무새 방지).

    맥락 분기:
    - is_hostile(사용자가 비아냥·불만·거부): 해맑게 "반갑습니다!" 하지 않고,
      차분하고 객관적인 톤으로 부담을 낮추며 응답한다. (요구사항 4)
    - 이름이 없거나(None) 기본값('리더')이면: 이름을 억지로 부르지 않고
      기본 호칭 '리더님'만 사용한다. (요구사항 3)
    """
    # user_name 이 실명인지 판정 (None/'리더'/'리더님' 은 이름 없음으로 취급)
    has_name = bool(user_name) and user_name not in ("리더", "리더님")
    # (2026-11-04 P3-5) 시간대별 안부 질문은 get_time_greeting()["greeting_question"] 하나로 — 11~12시는 '오전 마무리는 어떠세요?'
    _q = greeting_question or f"오늘 {current_ampm_phrase} 시간은 어떻게 보내고 계세요?"

    if is_hostile:
        # 공격성/불만 인식 — 반갑다며 해맑게 넘기지 않고 차분히 받아준다.
        return (
            "네, 리더님. 마음이 편치 않으실 수 있는데, 부담 갖지 않으셔도 "
            "됩니다. 이 자리는 평가가 아니라 편하게 이야기 나누는 시간이에요. "
            f"{_q}"
        )

    greeting = (
        f"반갑습니다, {user_name} 리더님! " if has_name
        else "네, 리더님. "
    )
    return (
        f"{greeting}"
        "본격적으로 시작하기 전에 잠깐 편하게 이야기 나눠볼게요. "
        f"{_q}"
    )


def build_rapport_greeting(coach_name: str) -> str:
    """라포 첫 인사 고정 템플릿.

    LLM 호출 없이 서버에서 직접 생성. 톤 고정 + Gemini 호출 1회 절약.
    """
    # Step 1: 자기소개 + 환영 쿠션어 + 이름 요청. (안부 질문은 라포 단계에서)
    return (
        f"반갑습니다, 리더님. 오늘 진단을 함께할 코치 {coach_name}입니다. "
        f"리더십 진단 세션에 오신 것을 진심으로 환영합니다.\n\n"
        f"이 과정은 평가가 아니라, 리더님만의 고유한 강점을 발견하고 "
        f"빛내는 여정이에요. 편안하게 이야기를 나누며 함께 찾아가 봐요.\n\n"
        f"시작에 앞서, 제가 리더님의 성함을 어떻게 부르면 좋을지 "
        f"먼저 알려주시겠어요?"
    )
