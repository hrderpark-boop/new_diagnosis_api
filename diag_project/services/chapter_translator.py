"""챕터 키 번역 헬퍼 (Phase 3-A)

DiagnosisSession.current_topic 은 한국어 ("조직관리") 로 저장되지만,
Phase 3-A 의 chapter context 는 영문 key ("organization_management") 사용.
이 모듈이 두 표현 간의 변환을 담당.

설계 결정: 점진적 전환을 위해 번역 레이어 사용.
DB 데이터 영문화 마이그레이션은 향후 Phase 에서 별도 진행.
"""

# 챕터 진행 순서 — 단일 소스(Single Source of Truth).
# ⚠️ 이 리스트를 복제하지 말 것: 순서 리스트가 여러 곳에 흩어지면
#    next_chapter 계산이 어긋나 챕터 전환 표지판이 꼬인다.
CHAPTER_ORDER: list[str] = [
    "organization_management",
    "performance_management",
    "people_management",
    "work_management",
    "self_management",
]


def get_next_chapter(current_chapter: str) -> str | None:
    """현재 챕터의 '진짜 다음' 챕터. 마지막이거나 미지의 값이면 None.

    반환값은 절대 current_chapter 와 같을 수 없다 (큐 전진 보장).
    """
    try:
        idx = CHAPTER_ORDER.index(current_chapter)
    except ValueError:
        return None
    return CHAPTER_ORDER[idx + 1] if idx + 1 < len(CHAPTER_ORDER) else None


# 한국어 → 영문 key
TOPIC_TO_CHAPTER: dict[str, str] = {
    "조직관리": "organization_management",
    "성과관리": "performance_management",
    "사람관리": "people_management",
    "일관리": "work_management",
    "자기관리": "self_management",
    "General": "organization_management",  # 시작 전 → 첫 챕터 기본값
}

# 영문 key → 한국어
CHAPTER_TO_TOPIC: dict[str, str] = {v: k for k, v in TOPIC_TO_CHAPTER.items()}


def topic_to_chapter(topic: str | None) -> str:
    """current_topic (한국어) → chapter (영문 key) 변환.

    None 또는 알 수 없는 값은 첫 챕터로 기본 처리.
    """
    if not topic:
        return "organization_management"
    return TOPIC_TO_CHAPTER.get(topic, "organization_management")


def chapter_to_topic(chapter: str) -> str:
    """chapter (영문 key) → topic (한국어) 변환.

    DB 저장 시 사용 (current_topic 갱신).
    """
    return CHAPTER_TO_TOPIC.get(chapter, "조직관리")
