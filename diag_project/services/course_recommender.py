"""맞춤형 교육과정 추천 엔진 (Level-Up Recommendation Engine).

진단 리포트의 26개 하위 역량 점수를 분석해, 각 역량을 '다음 레벨(Lv.N+1)'로
도약시키는 교육 트랙을 추천한다.

핵심 산식:
    추천점수 = (4 - 진단레벨) × 직무가중치(기본 1.0) × BEI 언급빈도
  · 진단레벨      : 하위 역량 점수(1.0~5.0)를 Lv.1~4 로 매핑
  · 직무가중치    : 기본 1.0 (향후 직무별 조정 여지)
  · BEI 언급빈도  : 해당 대역량 classification_keywords 의 BEI 등장 빈도를
                    5대 대역량 기준으로 '정규화'(1.0~2.0) — 대역량 편중 방지

최종 추천 4개:
  · 성장 과제 3개 : 진단레벨 < 4 인 하위역량 중 추천점수 상위, 레벨별 트랙
                    (Lv1→A, Lv2→B, Lv3→C). 동일 대역량 2개 초과 금지.
  · 강점 활용 1개 : 최고 점수 하위역량 → D트랙(전수·확산/멘토·스폰서 역할).
"""

import logging
import random

from diag_project.data.course_matrix import (
    CATEGORY_LABELS,
    TRACK_META,
    get_track_course,
)
from diag_project.data.competencies import (
    COMPETENCY_FRAMEWORK,
    SUBCOMPETENCY_ANCHORS,
)

logger = logging.getLogger(__name__)

DEFAULT_JOB_WEIGHT = 1.0

SECTION_INTRO = (
    "리더님의 진단 데이터를 심층 분석하여, 지금보다 한 단계 더 도약할 수 있는 "
    "성장 과제와, 이미 강점인 역량을 조직 전체로 확산할 기회를 도출하였습니다. "
    "아래 과정을 통해 다음 레벨의 리더십으로 나아가시기 바랍니다."
)

# 레벨 → 트랙 (성장 과제용). Lv4 는 성장이 아닌 강점(D) 으로 별도 처리.
_LEVEL_TO_TRACK = {1: "A", 2: "B", 3: "C"}

# 하위역량명 → indicator 키 역인덱스 (앵커 조회용)
_NAME_TO_KEY: dict[tuple[str, str], str] = {}
for _ck, _cv in COMPETENCY_FRAMEWORK.items():
    for _ik, _iv in _cv["indicators"].items():
        _NAME_TO_KEY[(_ck, _iv["name"])] = _ik


def score_to_level(score: float) -> int:
    """하위 역량 점수(1.0~5.0) → 진단 레벨(1~4) 매핑."""
    if score < 2.0:
        return 1
    if score < 3.0:
        return 2
    if score < 4.0:
        return 3
    return 4


def _flatten_sub_scores(details: dict) -> list[tuple[str, str, float]]:
    """details 에서 (역량키, 하위역량명, 점수) 26개를 평탄화."""
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


def _bei_frequency(transcript: str) -> dict[str, float]:
    """대역량별 BEI 언급빈도를 '정규화'(1.0~2.0)해 반환.

    classification_keywords 의 대화 등장 횟수를 5대 대역량 기준으로 정규화한다.
    가장 많이 언급된 대역량이 2.0, 언급 없으면 1.0(기본). → 사람관리(9개) 처럼
    하위역량 수가 많은 대역량이 무조건 편중되는 것을 완화한다.
    """
    text = transcript or ""
    raw: dict[str, int] = {}
    for ck, cv in COMPETENCY_FRAMEWORK.items():
        raw[ck] = sum(text.count(kw) for kw in cv.get("classification_keywords", []))
    peak = max(raw.values()) if raw else 0
    if peak <= 0:
        return {ck: 1.0 for ck in raw}
    return {ck: 1.0 + (cnt / peak) for ck, cnt in raw.items()}


def _bei_citation(comp_key: str, sub_name: str, details: dict) -> str | None:
    """BEI 에서 분석된 리더의 딜레마/키워드 한 줄 인용.

    우선순위: 해당 역량 reasoning_process 의 실제 대화 발췌 → 하위역량 딜레마
    앵커. (리포트에 '왜 이 과정인가'의 근거로 한 줄 인용)
    """
    comp = (details or {}).get(comp_key) or {}
    rp = comp.get("reasoning_process") or {}
    for step in ("2_action", "1_situation", "3_result"):
        quotes = (rp.get(step) or {}).get("quotes") or []
        for q in quotes:
            if q and isinstance(q, str) and len(q.strip()) >= 10:
                return q.strip()
    anchors = SUBCOMPETENCY_ANCHORS.get(_NAME_TO_KEY.get((comp_key, sub_name), ""))
    return random.choice(anchors) if anchors else None


def _build_entry(
    comp_key: str, sub_name: str, score: float, level: int, track: str,
    details: dict, *, is_strength: bool,
) -> dict:
    """(역량, 하위역량, 트랙) → UI 렌더용 추천 dict 조립."""
    course = get_track_course(comp_key, sub_name, track) or {}
    category = CATEGORY_LABELS.get(comp_key, comp_key)
    meta = TRACK_META.get(track, {})
    citation = _bei_citation(comp_key, sub_name, details)

    if is_strength:
        overview = (
            f"'{sub_name}'은(는) 이미 리더님의 대표 강점입니다. 이제 학습을 넘어, "
            "조직의 멘토이자 스폰서로서 이 강점을 후배 리더에게 전수할 때입니다."
        )
        bullets = [
            f"멘토·스폰서 역할: {course.get('subtitle', '')}",
            f"제안 형식: {meta.get('format', '')} — {meta.get('format_desc', '')}",
        ]
    else:
        target = meta.get("target_level", level + 1)
        overview = (
            f"현재 Lv.{level} 수준에서 Lv.{target}(으)로 한 단계 도약하면, "
            f"'{sub_name}'의 리더십 임팩트가 크게 확장됩니다."
        )
        bullets = [
            f"도달 목표(Lv.{target}): {course.get('subtitle', '')}",
            f"학습 형식: {meta.get('format', '')} — {meta.get('format_desc', '')}",
        ]

    return {
        "type": "강점 활용" if is_strength else "성장 과제",
        "track": track,
        "track_format": meta.get("format", ""),
        "category": category,
        "sub_competency": sub_name,
        "score": round(score, 1),
        "level": level,
        "target_level": meta.get("target_level"),
        "course": course.get("course", f"{sub_name} 과정"),
        "subtitle": course.get("subtitle", ""),
        "vod_url": course.get("vod_url", ""),
        "reason_overview": overview,
        "reason_bullets": bullets,
        "bei_citation": citation,
        "is_strength": is_strength,
    }


def build_course_recommendation(
    details: dict, transcript: str = "", job_weights: dict | None = None,
) -> dict | None:
    """26개 하위 점수 → 성장 3(A~C) + 강점 1(D) = 총 4개 추천 생성.

    - 추천점수 = (4 - 레벨) × 직무가중치 × BEI빈도(정규화)
    - 동일 대역량 2개 초과 추천 금지(강점 포함 전체 기준).
    """
    flat = _flatten_sub_scores(details)
    if not flat:
        logger.warning("교육과정 추천: 하위 점수 데이터 없음 → 추천 생략")
        return None

    bei = _bei_frequency(transcript)
    weights = job_weights or {}

    # 각 하위역량의 레벨·추천점수 산출
    scored = []
    for comp_key, sub_name, score in flat:
        level = score_to_level(score)
        jw = float(weights.get(comp_key, DEFAULT_JOB_WEIGHT))
        rec_score = (4 - level) * jw * bei.get(comp_key, 1.0)
        scored.append({
            "comp_key": comp_key, "sub_name": sub_name, "score": score,
            "level": level, "rec_score": rec_score,
        })

    per_competency: dict[str, int] = {}
    MAX_PER_COMPETENCY = 2

    # ── 강점 활용(D) 1개: 최고 점수 하위역량 ──
    strength_src = max(scored, key=lambda x: x["score"])
    per_competency[strength_src["comp_key"]] = 1
    strength = _build_entry(
        strength_src["comp_key"], strength_src["sub_name"],
        strength_src["score"], score_to_level(strength_src["score"]),
        "D", details, is_strength=True,
    )

    # ── 성장 과제(A~C) 3개: 레벨<4, 추천점수 상위, 대역량 max 2 ──
    growth_pool = [
        s for s in scored
        if s["level"] < 4
        and (s["comp_key"], s["sub_name"])
        != (strength_src["comp_key"], strength_src["sub_name"])
    ]
    growth_pool.sort(key=lambda x: (-x["rec_score"], x["score"]))

    growth: list[dict] = []
    for s in growth_pool:
        if len(growth) >= 3:
            break
        if per_competency.get(s["comp_key"], 0) >= MAX_PER_COMPETENCY:
            continue
        track = _LEVEL_TO_TRACK.get(s["level"], "A")
        growth.append(_build_entry(
            s["comp_key"], s["sub_name"], s["score"], s["level"],
            track, details, is_strength=False,
        ))
        per_competency[s["comp_key"]] = per_competency.get(s["comp_key"], 0) + 1

    logger.info(
        "🎯 교육 추천: 성장 %d개(%s) + 강점 '%s'(D)",
        len(growth), [g["sub_competency"] for g in growth],
        strength["sub_competency"],
    )

    return {
        "intro": SECTION_INTRO,
        "growth": growth,
        "strength": strength,
    }
