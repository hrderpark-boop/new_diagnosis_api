"""맞춤형 교육과정 추천 엔진 (Recommendation Engine).

진단 리포트의 27개 하위 역량 점수를 분석해 '가장 낮은 하위 역량'(약점 개선
타겟)과 '가장 높은 하위 역량'(강점 강화 타겟)을 추출하고, course_matrix DB
에서 부합하는 추천 교육과정·VOD 링크·AI 스파링 과제를 불러온다.

반환 구조(리포트 JSON 의 course_recommendation 필드로 저장):
{
  "intro": "...",                # 섹션 도입 문구
  "weakness": { ...course... },  # 약점 개선 1건 (없으면 None)
  "strength": { ...course... },  # 강점 강화 1건 (없으면 None)
}
각 course:
  {type, icon, category, sub_competency, score, course, vod_url, reason, sparring}
"""

import logging

from diag_project.data.course_matrix import (
    CATEGORY_LABELS,
    VOD_BASE,
    get_course,
)

logger = logging.getLogger(__name__)

SECTION_INTRO = (
    "리더님의 진단 데이터를 분석하여, 현재 가장 시급하게 돌파해야 할 "
    "'개선 포인트'와 조직의 시너지를 극대화할 '가장 날카로운 무기'를 "
    "선정했습니다. 아래 과정명을 클릭하여 즉시 성장을 시작해 보세요."
)


def _flatten_sub_scores(details: dict) -> list[tuple[str, str, float]]:
    """details 에서 27개 (역량키, 하위역량명, 점수) 를 평탄화."""
    flat: list[tuple[str, str, float]] = []
    for comp_key, comp in (details or {}).items():
        if not isinstance(comp, dict):
            continue
        for sub_name, score in (comp.get("sub_scores") or {}).items():
            try:
                flat.append((comp_key, str(sub_name), float(score)))
            except (TypeError, ValueError):
                continue
    return flat


def _build_course_entry(
    comp_key: str, sub_name: str, score: float, *, is_weakness: bool
) -> dict:
    """(역량, 하위역량) → UI 렌더용 course dict 조립."""
    info = get_course(comp_key, sub_name)
    category = CATEGORY_LABELS.get(comp_key, comp_key)

    if info:
        reason = (
            info["reason_weakness"] if is_weakness else info["reason_strength"]
        )
        entry = {
            "course": info["course"],
            "vod_url": f"{VOD_BASE}/{info['vod_slug']}",
            "reason": reason,
            "sparring": info["sparring"],
        }
    else:
        # 매트릭스 누락 방어 — 최소 폴백(과정 자체는 항상 제공).
        entry = {
            "course": f"{sub_name} 집중 성장 과정",
            "vod_url": VOD_BASE,
            "reason": (
                f"진단 결과 '{sub_name}' 영역이 개선 우선순위로 도출되었습니다."
                if is_weakness
                else f"진단 결과 '{sub_name}' 영역이 리더님의 대표 강점으로 "
                     "확인되었습니다."
            ),
            "sparring": f"'{sub_name}' 역량을 실전 상황에서 단련하는 AI 스파링 "
                        "과제가 준비되어 있습니다.",
        }

    entry.update({
        "type": "약점 개선" if is_weakness else "강점 강화",
        "icon": "🚨" if is_weakness else "🚀",
        "category": category,
        "sub_competency": sub_name,
        "score": round(score, 1),
    })
    return entry


def build_course_recommendation(details: dict) -> dict | None:
    """리포트 details(5역량) → 약점/강점 타겟 추천 2건 생성.

    - 27개 하위 점수 중 최저 1개 → 약점 개선, 최고 1개 → 강점 강화.
    - 최저·최고가 같은 하위 역량이면(전 점수 동일 등) 강점은 '최저를 제외한
      나머지 중 최고'로 골라 서로 다른 과정을 보장한다.
    - 점수 데이터가 없으면 None(섹션 미표시).
    """
    flat = _flatten_sub_scores(details)
    if not flat:
        logger.warning("교육과정 추천: 하위 점수 데이터 없음 → 추천 생략")
        return None

    # 최저(약점) — 동점이면 먼저 나온 것.
    weakness = min(flat, key=lambda x: x[2])
    # 최고(강점) — 약점과 다른 하위 역량이 되도록 약점을 제외하고 재탐색.
    others = [x for x in flat if (x[0], x[1]) != (weakness[0], weakness[1])]
    strength = max(others or flat, key=lambda x: x[2])

    return {
        "intro": SECTION_INTRO,
        "weakness": _build_course_entry(
            weakness[0], weakness[1], weakness[2], is_weakness=True
        ),
        "strength": _build_course_entry(
            strength[0], strength[1], strength[2], is_weakness=False
        ),
    }
