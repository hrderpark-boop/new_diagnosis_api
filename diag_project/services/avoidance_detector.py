"""회피/메타/일시정지 감지 헬퍼 (Phase 3-A Module 5)

사용자 응답을 분석해 다음을 감지:
- 회피 (모르겠어요, 짧은 답)
- 사용자의 종료 요청
- 시스템에 대한 메타 질문
- 의미 없는 입력 (asdf, ㅁㅁ)

설계 출처: docs/phase3a/01_design.md (Section 6.5, 10.3)
"""

# 회피 키워드
AVOIDANCE_KEYWORDS = [
    "모르겠", "기억 안", "기억안", "글쎄", "잘 모르",
    "생각 안", "안 떠올라", "안떠올라", "떠오르지 않",
]

# 사용자 종료/일시정지 요청 키워드.
#  ⚠️ 극도로 엄격하게 유지한다. 과거 "그만"·"나중에"·"다음에" 같은 단독 조각이
#     정상 서술("그만두게 했어요", "나중에 처리했죠", "다음에는 이렇게")까지
#     '휴식 요청'으로 오탐해, 회의적 대상자가 pause 루프에 갇혔다(61회 반복).
#     단순 불만·회의·비아냥은 절대 pause 로 보지 않는다. '세션을 멈추거나
#     미루려는 명시적 의도'(미루기 표지 + 코치에게 제안하는 어미)만 인정한다.
PAUSE_KEYWORDS = [
    # '오늘은 여기까지 / 그만'
    "오늘은 여기까지", "오늘은 그만", "오늘은 이만", "오늘 그만하",
    "여기까지 하", "여기까지만 하", "여기서 그만", "여기서 마치",
    # 미루기: 나중에/다음에/내일 + 제안 어미(하죠/할게/하자/할까/다시/이어)
    "나중에 하", "나중에 다시", "나중에 이어", "나중에 할",
    "다음에 하", "다음에 다시", "다음에 이어", "다음에 할", "다음 기회에",
    "내일 다시", "내일 이어", "내일 할게", "내일 하죠",
    # 쉬기
    "쉬었다 하", "쉬었다가 하", "쉬고 싶", "쉴게", "쉴래", "잠깐 쉬",
    "잠시 쉬", "좀 쉬고", "쉬어야겠",
    # 그만두기(세션 중단)
    "그만할래", "그만하고 싶", "그만하죠", "그만할게", "그만하자",
    "그만하겠", "그만둘래", "그만두고 싶",
    # 멈추기
    "일단 멈추", "잠깐 멈추", "잠시 멈추", "멈추고 싶", "멈출게",
    # 이만 마치기 / 바빠서
    "이만 마치", "이만 하죠", "이만 줄이", "이만 끝", "이만 가",
    "바빠서 이만", "바빠서 그만", "시간이 없어서 이만",
    # 더는 못
    "더는 못 하", "더는 못하", "더 이상 못 하", "더 이상은 못",
]

# 메타 질문 키워드 (시스템 자체에 대한 질문)
META_KEYWORDS = [
    "AI가", "당신이", "이 시스템", "신뢰",
    "정확한가요", "맞나요", "근거가",
    "어떻게 평가", "평가 방식", "이거 믿",
    "AI는", "AI랑", "이 평가",
]

# 사용자의 '종료 수용/요청' 발화 — 상태 동기화의 핵심 신호.
#  - explicit: 명시적 종료 동사 (끝내자/마무리/종료/이만) → 확실한 종료 의사
#  - soft: 감사/작별 인사 — 마지막 챕터 후반에서만 종료 신호로 해석
#    (대화 중간의 예의상 '감사합니다'를 종료로 오판하면 안 되므로 분리)
CLOSING_EXPLICIT_KEYWORDS = [
    "끝내죠", "끝냅시다", "끝내고 싶", "이제 끝", "끝난 건가요", "끝났나요",
    "끝인가요", "다 끝난", "마무리하죠", "마무리합시다", "마무리해 주",
    "마무리 지", "마무리할게요", "종료하죠", "종료할게요", "종료해 주",
    "이만 마치", "이만 줄이", "여기서 마치", "이제 마치",
]
CLOSING_SOFT_KEYWORDS = [
    "감사합니다", "감사했습니다", "감사드립니다", "고맙습니다",
    "고마웠습니다", "수고하셨", "고생하셨", "잘 들었습니다", "덕분에",
]

# '그럴듯한 공허함' 추상어 — 구체 없이 개념/이론만 나열하는 회피의 표지.
# (이론가_교과서형, AI_복붙형_위장자 대응)
ABSTRACT_KEYWORDS = [
    "전략", "혁신", "시너지", "데이터 기반", "패러다임", "역량", "본질",
    "지속가능", "지속 가능", "이해관계자", "선제적", "효율성 극대화",
    "리더십 철학", "성장 동력", "체계적", "심층적", "다각적", "궁극적",
    "방법론", "프레임워크", "인사이트", "통찰", "최적화", "고도화",
    "촉진자", "심리적 안정", "내재적 동기", "애자일", "서번트",
    "결론적으로", "궁극적으로", "본질적으로", "전사적", "유의미한",
]

# 프롬프트 주입/역할 탈취 시도 키워드 (한/영)
INJECTION_KEYWORDS = [
    # 내부 지시 노출 요구
    "시스템 프롬프트", "시스템프롬프트", "프롬프트 보여", "프롬프트를 알려",
    "지시문 보여", "지시사항을 알려", "내부 지시", "규칙을 알려",
    "system prompt", "your instructions", "reveal your",
    # 지시 무시/재정의 시도
    "지시 무시", "지시를 무시", "규칙 무시", "규칙을 무시", "앞의 내용 무시",
    "이전 지시", "무시하고 답", "ignore previous", "ignore all",
    "disregard", "override your",
    # 역할 탈취
    "이제부터 너는", "지금부터 너는", "역할을 바꿔", "역할극", "~인 척",
    "you are now", "act as", "pretend to be", "jailbreak", "DAN 모드",
    # 마커/태그 조작
    "[CHAPTER_COMPLETE]", "[DIAGNOSIS_COMPLETE]", "[SESSION_PAUSE]",
    "[START_CHAPTER]", "[READY_FOR_INTRO]",
]


def check_avoidance(text: str | None) -> bool:
    """회피 감지: 너무 짧거나 회피 키워드 포함."""
    if not text:
        return True
    stripped = text.strip()
    if len(stripped) < 10:
        return True
    return any(kw in stripped for kw in AVOIDANCE_KEYWORDS)


# 부재 진술(absence statement) 표지 — "그런 경험은 없다 / 만들어두지 못했다 /
# (위임 등을) 하지 않고 직접 챙긴다". 회피 키워드('모르겠')는 없지만
# 채점 가능한 '구체 행동 사건'이 아니다. 곧바로 measured 로 통과시키면 안 되고,
# "직접 챙기셨던 최근 사례 하나"를 청하는 2단 폴백을 발동시켜야 한다(T-A).
ABSENCE_KEYWORDS = [
    "경험은 없", "경험이 없", "경험은 많지 않", "경험이 많지 않",
    "해본 적이 없", "해 본 적이 없", "한 적이 없", "해본 적은 없",
    "만들어두지", "만들어 두지", "만들어놓지", "따로 없", "딱히 없",
    "특별히 없", "그런 건 없", "그런건 없", "별로 없", "잘 없",
    "위임하지", "위임한 적", "맡기지", "맡긴 적",
]


# ── A-1: 참여 이탈(disengagement) 신호 판정 ──
#   중단 트리거는 '근거 부족'이 아니라 '참여 이탈'이다(A-0). 성실히 답했으나
#   사례가 없는 경우(부재 진술)는 이탈이 아니라 유효한 Lv.1 신호다.
#   이탈 = ① 실질 내용 없는 단답 반복 ② 명시적 거부·중단 ③ 무응답.

# 명시적 거부·중단 의사(1회로도 즉시 중단 절차 진입).
#   🚨 어간(그만두/그만하)만 넣으면 "그만두'면' 아쉬울까 걱정"(=중단하기 싫다)
#   같은 긴 성실한 답변까지 오탐한다. 의도-'종결형'만 등재하고, 아래
#   classify_engagement 에서 길이 게이트(짧은 응답만 refusal)를 함께 건다.
_REFUSAL_KEYWORDS = [
    "나중에 하겠", "나중에 할게", "나중에 할래", "다음에 하겠", "다음에 할게",
    "다음에요", "다음에 할래",
    "오늘은 그만", "오늘은 여기까지", "오늘은 이만", "여기까지 하겠",
    "그만하겠", "그만할래", "그만하죠", "그만할게", "그만하고 싶",
    "그만둘래", "그만두겠", "그만두고 싶", "그만둡시다",
    "지금은 어렵", "지금은 힘들", "그만두는 게",
    "이만 하겠", "이만 마치", "이만 줄이",
    # skip/넘기기 의도(짧은 응답)
    "넘어가죠", "넘어갈게", "넘어갈래", "넘어가겠", "그냥 넘어",
]
# refusal 로 볼 수 있는 응답의 최대 길이(공백 제외). 이보다 길고 실질적이면
# 단어가 우연히 포함돼도 '중단 의도'가 아니라 '성실한 서술'로 본다.
_REFUSAL_MAX_LEN = 60

# 🚨 V-5: '길이 무관' 강한 거부 패턴 — 종결 의사 + 재개/미루기 요청이 함께
#   나타나면 정중하고 길어도 명백한 거부다(길이 게이트 우회). "그만두면
#   아쉬울까"(=중단 싫다) 같은 단순 언급과 달리, 아래는 '다시/다음에 + 하면
#   안 될까/하겠다' 처럼 미루기 의도가 명시된 조합만 잡는다.
_STRONG_REFUSAL_PATTERNS = [
    "다음에 다시 하", "다음에 다시 진행", "다음에 이어서", "다음에 하면 안",
    "다시 하면 안 될", "다시 하면 안될", "나중에 다시 하", "나중에 이어서",
    "오늘은 여기까지 하", "오늘은 이만 하", "이어서 하면 안 될",
    "다음 기회에 하", "다음번에 하", "나중에 이어",
]


def _has_strong_refusal(text: str) -> bool:
    """길이와 무관하게 명백한 '미루기·재개 요청' 거부인지."""
    return any(p in text for p in _STRONG_REFUSAL_PATTERNS)

# 실질 내용이 없는 '단답/필러' 토큰 — 이것만으로 이루어진 응답은 이탈 신호.
#   부재 진술("위임 경험은 많지 않습니다")은 '경험/위임/직접' 등 유의미 토큰이
#   남으므로 이탈로 잡히지 않는다.
_FILLER_TOKENS = {
    "네", "넵", "예", "아니요", "아니오", "아뇨", "응", "음", "뭐", "그",
    "저", "글쎄", "글쎄요", "없어요", "없습니다", "없음", "없는데요", "없네요",
    "모르겠어요", "모르겠습니다", "모르겠네요", "모르겠는데요", "모르겠",
    "기억안나요", "딱히", "딱히요", "그냥", "그냥요", "잘", "안", "뭐랄까",
    "패스", "스킵", "글쎄다",
    # 무성의 종결('됐어/그만') — 단독일 때만 이탈. 긴 문장의 "~하게 됐어요"
    # 는 다른 유의미 토큰이 남아 has_substance 로 engaged 가 된다(필러는 '전부
    # 필러일 때'만 empty 이므로).
    "됐어요", "됐어", "됐습니다", "됐네요", "됐고요", "됐거든요",
}


def detect_disengagement_refusal(text: str | None) -> bool:
    """명시적 거부·중단 의사 감지(휴식 요청 포함)."""
    if not text:
        return False
    stripped = text.strip()
    return (any(kw in stripped for kw in _REFUSAL_KEYWORDS)
            or detect_pause_request(text))


def _has_substance(text: str) -> bool:
    """필러를 걷어낸 뒤 유의미한 토큰(2자 이상, 필러 아님)이 남는가."""
    import re
    toks = re.split(r"\s+", text.strip())
    for t in toks:
        w = re.sub(r"[^가-힣a-zA-Z0-9]", "", t)
        if len(w) >= 2 and w not in _FILLER_TOKENS:
            return True
    return False


def classify_engagement(text: str | None) -> tuple[str, dict]:
    """참여 상태 분류 → ('engaged' | 'empty' | 'pause' | 'refusal', 근거 dict).

    구조화 로깅용 근거(길이 / 실질 내용 유무 / 거부 매칭)를 함께 반환한다.
    - 'pause'  : 휴식·미루기 요청(오늘은 여기까지/잠시 쉴게요) → 일시중지
                 (USER_REQUESTS_PAUSE → paused, 재개 가능). 이탈이 아니다.
    - 'refusal': 건너뛰기·거부 의사(넘어가죠/지금은 어렵) → 중단 절차(A-2)
    - 'empty'  : 무응답이거나 실질 내용 없는 단답(필러만) → 이탈 신호
    - 'engaged': 그 외(부재 진술처럼 성실히 설명한 경우 포함) → 이탈 아님

    H4: 과거엔 pause 문구("오늘은 여기까지 하고 잠시 쉴게요")가 refusal 로
    분류돼 ABORT_CONFIRM → aborted_disengaged 체인을 탔다. 프론트 '잠시 쉬기'
    버튼이 그 경로에 걸렸으므로 pause 를 refusal 보다 먼저, 별도 라벨로 뗀다.
    """
    raw = (text or "").strip()
    length = len(raw.replace(" ", ""))
    substance = _has_substance(raw)
    if not raw:
        return "empty", {"length": 0, "has_substance": False,
                         "refusal": False, "reason": "무응답"}
    # H4: 명시적·직접적 휴식/미루기 요청은 pause(이탈 아님) — refusal 보다 먼저.
    if detect_pause_request(raw):
        return "pause", {"length": length, "has_substance": substance,
                         "refusal": False, "reason": "휴식·미루기 요청(pause)"}
    # V-5: 명백한 미루기·재개 요청은 길어도 refusal(길이 게이트 우회).
    if _has_strong_refusal(raw):
        return "refusal", {"length": length, "has_substance": substance,
                           "refusal": True, "reason": "명시적 거부(미루기·재개 요청)"}
    # 🚨 refusal 은 '짧은 중단 의도'일 때만. 긴 성실한 서술(≥ _REFUSAL_MAX_LEN)이
    #   우연히 키워드를 포함해도 중단으로 보지 않는다(부분 문자열 오탐 방지).
    if length < _REFUSAL_MAX_LEN and detect_disengagement_refusal(raw):
        return "refusal", {"length": length, "has_substance": substance,
                           "refusal": True, "reason": "명시적 거부·중단"}
    if not substance:
        return "empty", {"length": length, "has_substance": False,
                         "refusal": False, "reason": "실질 내용 없는 단답(필러)"}
    return "engaged", {"length": length, "has_substance": True,
                       "refusal": False, "reason": "실질 응답"}


def detect_absence_statement(text: str | None) -> bool:
    """부재 진술 감지 — 근거가 아니라 '사건을 캐물어야 할' 신호.

    회피(check_avoidance)와 별개: 문장은 유창하지만 채점 가능한 행동 사건이
    없는 '경험 부재' 서술을 잡는다. 감지되면 2단 폴백(구체 사례 요청)을
    발동시켜, 거기서 나온 실제 사건이 Lv.1 의 정당한 근거가 되게 한다.
    """
    if not text:
        return False
    stripped = text.strip()
    return any(kw in stripped for kw in ABSENCE_KEYWORDS)


# 남탓(외부 귀인) · 비아냥 · 진단 자체를 무시하는 도발 패턴.
# 유효 데이터(STAR) 없이 이런 반응만 반복되면 '유의미한 진단 불가'로 보고
# Fail-Fast 강제 전환의 근거로 쓴다. (check_avoidance 의 단순 회피어와 별개)
# 🔑 강한 도발/남탓/비아냥 표지 — '성실한 서술문에 잘 섞이지 않는' 것만 둔다.
#   과거 오탐(협조적 투머치·회의적 불신형의 강제 종료)을 낸 모호어는 제거:
#     "위에서"(→하늘 위로), "의미가 있"(→의미가 있는지), "왜 이런"(→왜 이런
#     결정), "시스템 문제"(→실제 업무 서술), "이런 거 해서"(→긍정 서술),
#     "은/는 무슨"(→"목표는 무슨 기준"), "그래서 뭐"(→"그래서 뭐가 좋았냐면").
DEFLECTION_STRONG = [
    # 남탓 / 외부 귀인
    "무능", "시스템이 엉망", "회사가 문제", "회사 탓",
    "팀원들 때문", "팀원이 문제", "쟤네가", "걔네가", "위에서 시켜",
    "제 잘못이 아", "내 잘못이 아",
    # 비아냥 / 진단 무시 / 도발 / 불만·비하
    "왜 물어", "왜 해요", "뭐가 달라", "뭐가 바뀌",
    "알기나 해", "네가 뭘", "당신이 뭘",
    # "관심 없": 거절형 어미만 (부사 "관심 없이 시켰어요"는 서술이므로 제외)
    "쓸데없", "시간 낭비", "무슨 소용",
    "관심 없어", "관심 없다", "관심 없고", "관심 없네", "관심 없음",
    "이딴", "이따위", "치워", "하기 싫", "안 할래",
    # 귀찮: 불만형 어미만 (부정문 "귀찮은 게 아니라"는 안 걸리게 "귀찮은"은 뺌)
    "귀찮아", "귀찮게", "귀찮다", "귀찮네", "귀찮으",
]

# ⚠️ "됐어/됐고/됐거든" 계열은 의도적으로 제외한다. 거절의 "됐어(그만)"와
#   보조용언 "~하게 됐어요/됐거든요(그리 되었다)"가 부분매칭으로 구분되지
#   않아, "고민 끝에 하게 됐거든요" 같은 성실한 서술까지 오탐했다. 진짜 거절의
#   "됐고/됐거든"은 늘 다른 강한 표지(관심없·이딴·무능 등)와 함께 오므로
#   제외해도 도발 감지엔 지장이 없고, 단독 "됐고"(초단문)는 check_avoidance
#   가 이미 잡는다.

# 하위호환: 과거 이 이름을 참조하던 코드/테스트를 위해 노출.
DEFLECTION_KEYWORDS = list(DEFLECTION_STRONG)

# 도발을 '퉁명하고 짧은' 발화로 인정하는 최대 길이(자). 실측상 진짜 도발은
#  모두 ≤33자로 짧았고, 오탐은 모두 200자+의 길고 열정적인 발화였다.
SHORT_DEFLECTION_LEN = 45
# 긴 발화가 그럼에도 도발로 인정되려면 필요한 강한 표지 개수(순수 남탓 나열).
LONG_DEFLECTION_MIN_HITS = 3


def _deflection_hits(text: str) -> set:
    """도발 표지 집합 반환 (강한 표지)."""
    return {kw for kw in DEFLECTION_STRONG if kw in text}


def detect_deflection(text: str | None) -> bool:
    """남탓·비아냥·도발 감지 (유효 데이터 회피의 또 다른 형태).

    핵심 판별자는 '길이'다. 진짜 도발은 퉁명하고 짧으며, 협조적·회의적
    대상자의 길고 구체적인 발화는 우연히 표지 조각이 섞여도 engagement 다.
      · 짧은 발화(≤SHORT_DEFLECTION_LEN)  → 도발 표지 1개로도 도발 확정
      · 긴 발화                            → 강한 표지 LONG_MIN_HITS 개 이상
        (순수 남탓·비아냥만 늘어놓은 경우)일 때만 도발로 인정
    완료형 서술어("완료됐어요")와 충돌하는 거절어는 어절 경계에서만 본다.
    """
    if not text:
        return False
    stripped = text.strip()
    hits = _deflection_hits(stripped)
    if not hits:
        return False
    if len(stripped) <= SHORT_DEFLECTION_LEN:
        return True
    return len(hits) >= LONG_DEFLECTION_MIN_HITS


# 진단을 회피한 채 '빨리 진행/재촉·시간 불평'만 하는 발화 표지(코치에게 향한
#  명령·불평 형태만; 서술문 오탐 방지 위해 길이 게이트 병행).
RUSH_KEYWORDS = [
    "빨리 합시다", "빨리 하죠", "빨리 하자", "빨리 좀", "빨리 진행합시다",
    "빨리 진행하죠", "빨리 진행해", "빨리 끝냅시다", "빨리 끝내죠",
    "빨리빨리", "빨리 넘어가", "빨리 다음", "그냥 빨리",
    "언제 끝나", "언제 끝", "언제까지 해", "얼마나 남았", "얼마나 더 해",
    "얼마나 걸려", "얼마나 오래", "몇 개나 남", "몇 개 남", "몇 개나 더",
    "지루하네", "지루해", "지루하다", "재미없",
    "대충 합시다", "대충 하죠", "대충 넘어", "그냥 넘어갑시다", "그냥 넘어가죠",
    "그냥 다음", "다음 거 합시다", "다음 질문", "시간 없으니", "시간 없어요",
    "바쁘니까 빨리", "그만 좀 물어", "질문 그만", "그만 물어봐",
]
RUSH_MAX_LEN = 60


def detect_rush(text: str | None) -> bool:
    """유효 답변 없이 '빨리 진행/재촉·시간 불평'만 하는 발화 감지.

    "빨리 합시다", "언제 끝나요", "그냥 넘어가죠" 처럼 진단 자체를 회피하며
    진행만 재촉하는 경우 True. 긴 서술 속 우연한 조각 매칭을 막기 위해 짧은
    발화(RUSH_MAX_LEN 이하)에서만 인정한다.
    """
    if not text:
        return False
    stripped = text.strip()
    if len(stripped) > RUSH_MAX_LEN:
        return False
    return any(kw in stripped for kw in RUSH_KEYWORDS)


def is_unproductive_response(text: str | None) -> bool:
    """이번 발화가 '유효 데이터 없는 비생산적 응답'인지 종합 판정.

    단순 회피(check_avoidance) + 남탓/비아냥/도발(detect_deflection) +
    재촉·시간불평(detect_rush)을 합쳐, Fail-Fast·경고 후 즉시 종료 판정의
    단일 기준으로 쓴다. (무의미한 단답, "빨리 합시다"류 재촉 포함.)
    """
    return (
        check_avoidance(text)
        or detect_deflection(text)
        or detect_rush(text)
    )


def detect_session_abort_signal(text: str | None) -> bool:
    """세션 강제 종료(3-Strike) 누적 카운트 대상 판정.

    적대적·비협조 신호(남탓·비아냥·도발 detect_deflection + 재촉·시간불평
    detect_rush)만 센다. '노력하는 단답형'의 단순 짧은 답변(check_avoidance)은
    제외 — 이는 챕터 Fail-Fast(강제 전환)가 따로 처리하므로, 성실한 단답형이
    세션째 강제 종료되는 오작동을 막는다.
    """
    return detect_deflection(text) or detect_rush(text)


# 진짜 pause 요청은 짧고 직접적이다(실측 <50자). 장문 속 pause 표지는 대개
#  부정("쉬고 싶어 한다고 착각")·인용·은유이므로(실측 FP 모두 1000자+) 제외한다.
PAUSE_MAX_LEN = 200


def detect_pause_request(text: str | None) -> bool:
    """사용자 종료/일시정지 요청 감지 (명시적·직접적 의도만)."""
    if not text:
        return False
    stripped = text.strip()
    if len(stripped) > PAUSE_MAX_LEN:
        return False
    return any(kw in stripped for kw in PAUSE_KEYWORDS)


def detect_meta_question(text: str | None) -> bool:
    """시스템에 대한 메타 질문 감지."""
    if not text:
        return False
    return any(kw in text for kw in META_KEYWORDS)


def detect_closing_intent(text: str | None) -> str | None:
    """사용자의 종료 수용/요청 의사 감지.

    반환:
    - "explicit": 명시적 종료 요청 ('이제 끝내죠', '마무리하죠' 등)
    - "soft":     감사/작별 인사만 ('감사합니다', '수고하셨습니다' 등)
    - None:       종료 신호 없음

    라우팅은 decider 가 챕터 맥락(마지막 챕터 여부·진행량)과 함께 판단한다.
    """
    if not text:
        return None
    if any(kw in text for kw in CLOSING_EXPLICIT_KEYWORDS):
        return "explicit"
    if any(kw in text for kw in CLOSING_SOFT_KEYWORDS):
        return "soft"
    return None


def detect_abstract_avoidance(text: str | None) -> bool:
    """'그럴듯한 공허함' 감지 — 추상적 개념/이론만 늘어놓고 구체가 없는 답변.

    구체성의 증거(고유명사·수치/기간·직접 발화)가 거의 없으면서 추상어
    밀도가 높은, 충분히 긴 답변을 True 로 판정한다.
    - 너무 짧은 답(단답 회피)은 check_avoidance 가 따로 처리하므로 제외.
    - 구체 증거가 하나라도 뚜렷하면 (사람 이름+직접 발화 등) 통과시킨다.
    """
    import re

    if not text:
        return False
    stripped = text.strip()
    # 충분히 길어야(개념 나열형은 길다) 판정 대상. 짧은 답은 단답 회피로.
    if len(stripped) < 60:
        return False

    # 1) 구체성 증거 카운트
    concrete = 0
    # 직접 발화: '~라고 말/했' , 따옴표로 감싼 발화
    if re.search(r"라고\s*(말|얘기|이야기|하|했|말씀)", stripped):
        concrete += 2
    if re.search(r"[\"'“”].{2,}[\"'“”]", stripped):
        concrete += 1
    # 수치/기간/날짜: 숫자+단위, 연·월·일, 지난주/이번달 등
    if re.search(r"\d+\s*(년|월|일|주|시간|분|명|건|%|퍼센트|억|만|천|개|차)",
                 stripped):
        concrete += 1
    if re.search(r"(지난|이번|저번|작년|올해|어제|그제|당시)\s*"
                 r"(주|달|월|해|분기|회의|프로젝트)?", stripped):
        concrete += 1
    # 고유명사 신호: 'OO 팀/부/과/파트', 'A씨/B님/○ 대리·과장·차장·부장'
    if re.search(r"[가-힣A-Za-z]{1,6}\s*(팀|부서|본부|파트|과|실|센터)",
                 stripped):
        concrete += 1
    if re.search(r"[가-힣A-Za-z]{1,4}\s*"
                 r"(씨|님|대리|과장|차장|부장|팀장|사원|주임|이사|대표)",
                 stripped):
        concrete += 1

    # 2) 추상어 밀도
    abstract_hits = sum(1 for kw in ABSTRACT_KEYWORDS if kw in stripped)

    # 구체 증거가 뚜렷하면(2점 이상) 회피 아님.
    if concrete >= 2:
        return False
    # 추상어가 3개 이상 쏟아지고 구체 증거가 빈약하면 '공허한 추상' 회피.
    return abstract_hits >= 3


def detect_prompt_injection(text: str | None) -> bool:
    """프롬프트 주입/역할 탈취 시도 감지.

    사용자가 내부 지시 노출·규칙 무시·역할 변경을 요구하거나, 시스템
    제어 마커를 직접 입력해 흐름을 조작하려는 경우 True.
    (감지 시 LLM 에 PROMPT_INJECTION_DETECTED 지시 → 정중히 거절하고
    진단 맥락으로 복귀. 백엔드 마커 게이트가 2차 방어선.)
    """
    if not text:
        return False
    lowered = text.lower()
    return any(kw.lower() in lowered for kw in INJECTION_KEYWORDS)


def is_invalid_input(text: str | None) -> bool:
    """의미 없는 입력 (asdf, ㅁㅁ 등) 감지."""
    if not text:
        return True

    stripped = text.strip()
    if not stripped:
        return True

    # 한국어 자음/모음만 (ㅁㅁ, ㅋㅋ 등)
    if all(0x3131 <= ord(c) <= 0x3163 for c in stripped if not c.isspace()):
        return True

    # 같은 문자/2개 문자 반복 (asdfasdf, aaaa 등)
    no_space = stripped.replace(" ", "")
    if len(no_space) >= 3 and len(set(no_space)) <= 2:
        return True

    # 영문 키보드 패턴
    keyboard_patterns = ("asdf", "qwer", "zxcv", "qwerty", "asdfasdf")
    if stripped.lower() in keyboard_patterns:
        return True

    return False
