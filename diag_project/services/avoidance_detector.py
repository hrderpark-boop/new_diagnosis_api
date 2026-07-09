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

# 사용자 종료/일시정지 요청 키워드
PAUSE_KEYWORDS = [
    "그만", "오늘은 여기까지", "다음에", "쉴게", "쉬고싶",
    "나중에", "내일", "그만하고", "일단 멈", "여기까지만",
    "더는 못", "오늘은 그만",
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


def detect_pause_request(text: str | None) -> bool:
    """사용자 종료/일시정지 요청 감지."""
    if not text:
        return False
    return any(kw in text for kw in PAUSE_KEYWORDS)


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
