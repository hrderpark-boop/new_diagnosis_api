"""Module 4: 사건 중복 검출

새 사건 시작 시 이전 사건들과 비교해 중복 여부 판단.
1차 필터(메타데이터)만 수행. 의심 시 2차 LLM 판정은 별도 단계 (Step 6+).

설계 출처: docs/phase3a/01_design.md (Section 6.4)
"""


def check_potential_duplicate(
    new_event_text: str,
    existing_events: list[dict],
) -> dict:
    """새 사건이 기존 사건과 중복인지 1차 검사.

    Args:
        new_event_text: 사용자가 방금 말한 새 사건 텍스트
        existing_events: 이전 챕터 사건 메타데이터 dict 리스트
            (event_id, chapter, summary, key_person, time_context,
             core_action, tags 포함)

    Returns:
        {
            "is_duplicate": bool,
            "matched_event": dict | None,
            "reason": str,  # "key_person_match" 등
        }
    """
    if not existing_events:
        return {
            "is_duplicate": False,
            "matched_event": None,
            "reason": "no_existing",
        }

    if not new_event_text:
        return {
            "is_duplicate": False,
            "matched_event": None,
            "reason": "empty_text",
        }

    new_text_lower = new_event_text.lower()

    for existing in existing_events:
        # 1. 인물 일치 (이름/직책 키워드 포함)
        if existing.get("key_person"):
            person_keywords = _extract_person_keywords(existing["key_person"])
            if person_keywords and any(
                kw.lower() in new_text_lower for kw in person_keywords
            ):
                return {
                    "is_duplicate": True,
                    "matched_event": existing,
                    "reason": "key_person_match",
                }

        # 2. 태그 중첩 (50% 이상)
        if existing.get("tags"):
            overlap = _calculate_tag_overlap(
                existing["tags"], new_text_lower
            )
            if overlap >= 0.5:
                return {
                    "is_duplicate": True,
                    "matched_event": existing,
                    "reason": "tag_overlap",
                }

        # 3. 핵심 행동 텍스트 유사도 (자카드 기반)
        if existing.get("core_action"):
            similarity = _text_similarity(
                existing["core_action"], new_text_lower
            )
            if similarity > 0.6:
                return {
                    "is_duplicate": True,
                    "matched_event": existing,
                    "reason": "action_similar",
                }

    return {
        "is_duplicate": False,
        "matched_event": None,
        "reason": "no_match",
    }


def _extract_person_keywords(person_text: str) -> list[str]:
    """인물 설명에서 검색 가능한 키워드 추출.

    예: "교육 설계 희망 팀원" → ["교육", "설계", "희망", "팀원"]
    """
    if not person_text:
        return []

    skip_words = {"님", "분", "씨", "그", "저", "이"}
    keywords = []
    for word in person_text.split():
        clean = word.strip()
        if len(clean) >= 2 and clean not in skip_words:
            keywords.append(clean)

    return list(set(keywords))


def _calculate_tag_overlap(tags: list[str], text: str) -> float:
    """태그가 텍스트에 얼마나 포함되는지 비율 (0.0 ~ 1.0)."""
    if not tags:
        return 0.0
    matches = sum(1 for tag in tags if tag and tag.lower() in text)
    return matches / len(tags)


def _text_similarity(text1: str, text2: str) -> float:
    """단순 자카드 유사도 (단어 집합 기반)."""
    if not text1 or not text2:
        return 0.0

    set1 = set(text1.split())
    set2 = set(text2.split())

    if not set1 or not set2:
        return 0.0

    intersection = set1 & set2
    union = set1 | set2

    return len(intersection) / len(union)
