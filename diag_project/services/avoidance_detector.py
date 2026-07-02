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
