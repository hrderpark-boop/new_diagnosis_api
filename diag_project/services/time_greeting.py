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
    #   (2026-11-15 P13-A) 문장은 GREETING_QUESTIONS 사전에 둔다. 이 키는 종전대로 해요체 판(코치 말투 판은 greeting_question_for).
    greeting_question = greeting_question_for(part)
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


# (2026-11-15 P13-A) 세션 첫 두 턴(첫 인사 · 이름을 받은 뒤 첫 스몰톡 질문)의 고정 문장 — 코치 말투별 사전.
#   11/14 운영 Lucas: 두 턴이 해요체로 나갔다('…여정이에요', '…나눠볼게요', '…보내고 계세요?'). 틀이 해요체 한 벌뿐이었고, 뒤에서 거는
#   말투 교정(persona_register.apply_register)은 Lucas(mixed)를 건너뛴다. Jessica·Daniel 은 그 교정의 어미표가 바꿔 줬지만
#   '찾아가 봐요' → '찾아가 봅니다' 처럼 어색한 꼴이 나왔다. 어미표에 기대지 않고 말투별 문장을 여기에 둔다.
#   묶음: polite(Ella·Olivia·Michael, 종전 문장 그대로) · formal(Jessica·Daniel) · Lucas(합쇼체, 그의 다른 고정 문장처럼 짧게).
GREETING_QUESTIONS: dict[str, dict[str, str]] = {
    "polite": {
        "오전 마무리": "오전 마무리는 어떠세요?",
        "늦은 시간": "오늘 하루는 어떻게 보내셨어요?",      # (2026-11-10 p9c) '오늘 늦은 시간 시간은 …' 낱말 중복
        "시간대": "오늘 {part} 시간은 어떻게 보내고 계세요?",
        "하루": "오늘 하루는 어떻게 보내고 계세요?",          # 시간대 이름을 모를 때
    },
    "formal": {
        "오전 마무리": "오전 마무리는 어떠십니까?",
        "늦은 시간": "오늘 하루는 어떻게 보내셨습니까?",
        "시간대": "오늘 {part} 시간은 어떻게 보내고 계십니까?",
        "하루": "오늘 하루는 어떻게 보내고 계십니까?",
    },
}
_QUESTION_PARTS = ("오전", "점심", "오후", "저녁")      # "오늘 [시간대] 시간은 …" 틀에 들어가는 시간대 이름

RAPPORT_FIRST_LINES: dict[str, dict[str, str]] = {
    "polite": {
        "greeting": (
            "반갑습니다, 리더님. 오늘 진단을 함께할 코치 {coach_name}입니다. "
            "리더십 진단 세션에 오신 것을 진심으로 환영합니다.\n\n"
            "이 과정은 평가가 아니라, 리더님만의 고유한 강점을 발견하고 "
            "빛내는 여정이에요. 편안하게 이야기를 나누며 함께 찾아가 봐요.\n\n"
            "시작에 앞서, 제가 리더님의 성함을 어떻게 부르면 좋을지 "
            "먼저 알려주시겠어요?"
        ),
        "named": "반갑습니다, {user_name} 리더님! ",
        "unnamed": "네, 리더님. ",
        "icebreak": "본격적으로 시작하기 전에 잠깐 편하게 이야기 나눠볼게요. ",
        "hostile": (
            "네, 리더님. 마음이 편치 않으실 수 있는데, 부담 갖지 않으셔도 "
            "됩니다. 이 자리는 평가가 아니라 편하게 이야기 나누는 시간이에요. "
        ),
    },
    "formal": {
        "greeting": (
            "반갑습니다, 리더님. 오늘 진단을 함께할 코치 {coach_name}입니다. "
            "리더십 진단 세션에 오신 것을 진심으로 환영합니다.\n\n"
            "이 과정은 평가가 아니라, 리더님만의 고유한 강점을 발견하고 "
            "빛내는 여정입니다. 편안하게 이야기를 나누며 함께 찾아가 보겠습니다.\n\n"
            "시작에 앞서, 제가 리더님의 성함을 어떻게 부르면 좋을지 "
            "먼저 알려주시겠습니까?"
        ),
        "named": "반갑습니다, {user_name} 리더님. ",
        "unnamed": "네, 리더님. ",
        "icebreak": "본격적으로 시작하기 전에 잠깐 편하게 이야기 나눠보겠습니다. ",
        "hostile": (
            "네, 리더님. 마음이 편치 않으실 수 있는데, 부담 갖지 않으셔도 "
            "됩니다. 이 자리는 평가가 아니라 편하게 이야기 나누는 시간입니다. "
        ),
    },
    "Lucas": {
        "greeting": (
            "반갑습니다, 리더님. 오늘 진단을 함께할 코치 {coach_name}입니다. "
            "리더십 진단 세션에 오신 것을 환영합니다.\n\n"
            "이 과정은 평가가 아니라 리더님의 강점을 찾는 자리입니다. "
            "편하게 말씀하시면 됩니다.\n\n"
            "시작에 앞서, 성함을 어떻게 부르면 되는지 먼저 알려주시겠습니까?"
        ),
        "named": "반갑습니다, {user_name} 리더님. ",
        "unnamed": "네, 리더님. ",
        "icebreak": "시작하기 전에 잠깐 편하게 이야기 나누겠습니다. ",
        "hostile": (
            "네, 리더님. 부담 갖지 않으셔도 됩니다. "
            "이 자리는 평가가 아니라 편하게 이야기하는 시간입니다. "
        ),
    },
}


def _voice_key(persona_name: str | None) -> str:
    """고정 문장 묶음 이름 — 그 코치 전용 묶음이 있으면 코치 이름('Lucas'), 없으면 말투('formal'/'polite'). 이름이 없거나 모르는 이름이면 'polite'."""
    if not persona_name:
        return "polite"
    from diag_project.services.intro_messages import line_register, persona_key
    key = persona_key(persona_name)          # 모르는 이름은 Ella(해요체)로 떨어진다
    return key if key in RAPPORT_FIRST_LINES else line_register(persona_name)


def _question_register(persona_name: str | None) -> str:
    """안부 질문의 말투 — 합쇼체 코치(Jessica·Daniel·Lucas)는 'formal', 그 밖과 이름 없음은 'polite'."""
    if not persona_name:
        return "polite"
    from diag_project.services.intro_messages import line_register
    return line_register(persona_name)


def _greeting_question(part: str | None, register: str) -> str:
    pool = GREETING_QUESTIONS[register]
    if part in ("오전 마무리", "늦은 시간"):
        return pool[part]
    if part in _QUESTION_PARTS:
        return pool["시간대"].format(part=part)
    return pool["하루"]


def greeting_question_for(part: str | None, persona_name: str | None = None) -> str:
    """시간대 이름(daypart)에 맞는 안부 질문 — 코치 말투 판. persona_name 이 없으면 해요체 판(종전 문장)."""
    return _greeting_question(part, _question_register(persona_name))


def _same_question_in_register(question: str, register: str) -> str:
    """해요체 판 안부 질문(get_time_greeting 이 state 에 넣는 문장)을 같은 시간대의 그 말투 문장으로 — 어미를 바꾸지 않고 사전에서 찾는다.
    사전에 없는 문장(호출자가 따로 지은 질문)은 그대로 돌려준다."""
    if register == "polite":
        return question
    for part in ("오전 마무리", "늦은 시간", *_QUESTION_PARTS, None):
        if _greeting_question(part, "polite") == question:
            return _greeting_question(part, register)
    return question


def build_rapport_first_turn_response(
    user_name: str | None,
    current_ampm_phrase: str,
    is_hostile: bool = False,
    greeting_question: str | None = None,
    persona_name: str | None = None,
) -> str:
    """라포 1턴 (이름 받은 직후) — Step 1 이름 수용 + Step 2 아이스브레이킹.

    [중요] 인사말(build_rapport_greeting)에서 이미 자기소개를 마쳤으므로
    여기서 코치 자기소개를 절대 반복하지 않는다 (앵무새 방지).

    맥락 분기:
    - is_hostile(사용자가 비아냥·불만·거부): 해맑게 "반갑습니다!" 하지 않고,
      차분하고 객관적인 톤으로 부담을 낮추며 응답한다. (요구사항 4)
    - 이름이 없거나(None) 기본값('리더')이면: 이름을 억지로 부르지 않고
      기본 호칭 '리더님'만 사용한다. (요구사항 3)

    (2026-11-15 P13-A) persona_name 을 주면 그 코치 말투의 문장(RAPPORT_FIRST_LINES)으로 낸다 — 합쇼체 코치는 합쇼체 문장과
    합쇼체 안부 질문. 주지 않으면 종전과 같다(해요체 판).
    """
    # user_name 이 실명인지 판정 (None/'리더'/'리더님' 은 이름 없음으로 취급)
    has_name = bool(user_name) and user_name not in ("리더", "리더님")
    lines = RAPPORT_FIRST_LINES[_voice_key(persona_name)]
    if persona_name is None:
        # (2026-11-04 P3-5) 시간대별 안부 질문은 get_time_greeting()["greeting_question"] 하나로 — 11~12시는 '오전 마무리는 어떠세요?'
        _q = greeting_question or GREETING_QUESTIONS["polite"]["시간대"].format(part=current_ampm_phrase)
    elif greeting_question:
        # state 에 들어 있는 안부 질문은 해요체 판이다 → 같은 시간대의 코치 말투 문장으로
        _q = _same_question_in_register(greeting_question, _question_register(persona_name))
    else:
        _q = greeting_question_for(current_ampm_phrase, persona_name)

    if is_hostile:
        # 공격성/불만 인식 — 반갑다며 해맑게 넘기지 않고 차분히 받아준다.
        return f"{lines['hostile']}{_q}"

    greeting = lines["named"].format(user_name=user_name) if has_name else lines["unnamed"]
    return f"{greeting}{lines['icebreak']}{_q}"


def build_rapport_greeting(coach_name: str, persona_name: str | None = None) -> str:
    """라포 첫 인사 고정 템플릿.

    LLM 호출 없이 서버에서 직접 생성. 톤 고정 + Gemini 호출 1회 절약.

    (2026-11-15 P13-A) 코치 말투별 문장(RAPPORT_FIRST_LINES). 말투는 persona_name 으로 고르고, 없으면 coach_name(세션 코치의
    표시 이름 'Lucas (루카스)' — 페르소나 이름과 같다)으로 고른다. 모르는 이름이면 해요체 판.
    """
    # Step 1: 자기소개 + 환영 쿠션어 + 이름 요청. (안부 질문은 라포 단계에서)
    lines = RAPPORT_FIRST_LINES[_voice_key(persona_name if persona_name is not None else coach_name)]
    return lines["greeting"].format(coach_name=coach_name)
