"""맞춤형 교육과정 추천 엔진 (Level-Up Recommendation Engine).

P0-5 / P1-1 준수:
  · 후보는 measured == True 하위역량으로만 한정 (미측정은 추천하지 않음)
  · 추천점수 = (4 − 하위역량점수) × 직무가중치(기본 1.0) × 근거발화수보정
  · 동일 대역량 최대 2개 · 인용문 중복 금지
  · 성장 3(A~C) + 강점 1(D). D트랙은 '근거 검증 게이트' 통과 시에만 생성,
    실패하면 성장 과제 4로 채움.

레벨→트랙: Lv1→A, Lv2→B, Lv3→C, (Lv4 & 게이트통과)→D.
"""

import logging

from diag_project.data.course_matrix import (
    CATEGORY_LABELS,
    TRACK_META,
    get_track_course,
)
from diag_project.data.competencies import COMPETENCY_FRAMEWORK

logger = logging.getLogger(__name__)

DEFAULT_JOB_WEIGHT = 1.0
_LEVEL_TO_TRACK = {1: "A", 2: "B", 3: "C"}


def _framework_order() -> dict:
    """(comp_key, sub_name) → 프레임워크 정의 순서 인덱스.

    R-1: tie-break 최종 단계의 '고정 순서'. dict 순서·해시에 의존하지 않고
    competencies.py 정의 순서를 결정론적 키로 못박는다.
    """
    order: dict = {}
    i = 0
    for ck, cv in COMPETENCY_FRAMEWORK.items():
        if ck == "supplementary":
            continue
        for ind in (cv.get("indicators") or {}).values():
            order[(ck, ind.get("name"))] = i
            i += 1
    return order


_FRAMEWORK_ORDER = _framework_order()


def _tie_break_tail(item: dict) -> tuple:
    """R-1 동점 처리 꼬리키(2~4단계). 작을수록 우선.

    ① 안정 탐지 우선(borderline detection 없는 후보 먼저)
    ② 레벨 확정 우선(borderline level 없는 후보 먼저)
    ③ 근거 수 많은 순
    ④ 프레임워크 고정 순서
    """
    bl = item.get("borderline") or {}
    flags = set(bl.get("flags") or [])
    return (
        1 if "detection" in flags else 0,
        1 if "level" in flags else 0,
        -len(item.get("evidence") or []),
        _FRAMEWORK_ORDER.get(
            (item.get("comp_key"), item.get("sub_name")), 1_000_000),
    )


def _stability_tier(item: dict) -> int:
    """I-1(4): stable(0) < semi(1). weak 는 measured 가 아니라 후보에 안 옴.

    outer 교집합 병합에서 semi 는 borderline 을 갖고, stable 은 None 이다.
    """
    return 1 if item.get("borderline") else 0


def deterministic_candidate_key(item: dict) -> tuple:
    """S-1/I-1(4): 성장 후보 완전 결정론 정렬 키 (순수 함수).

    ① 안정성 계층(stable 먼저) — '확신하는 것만 추천'. 이어서 ② rec_score
    내림차, ③ R-1 동점 꼬리키. 랜덤·해시·dict 순서 비의존(shuffle 불변).
    """
    return (_stability_tier(item),
            -float(item.get("rec_score") or 0.0)) + _tie_break_tail(item)


def _strength_candidate_key(item: dict) -> tuple:
    """강점(D) 후보 결정론 키: 점수 내림차 우선, 동점은 _tie_break_tail."""
    return (-float(item.get("score") or 0.0),) + _tie_break_tail(item)


SECTION_INTRO = (
    "리더님의 진단 데이터를 심층 분석하여, 지금보다 한 단계 더 도약할 수 있는 "
    "성장 과제와, 이미 강점인 역량을 조직 전체로 확산할 기회를 도출하였습니다. "
    "아래 과정을 통해 다음 레벨의 리더십으로 나아가시기 바랍니다."
)

# 강점(D) 후보 자격 기준
STRENGTH_MIN_SCORE = 3.5
STRENGTH_MIN_EVIDENCE = 2


def _sub_level(score: float | None) -> int | None:
    """하위역량 점수(이미 [1,4] 클램프)를 레벨(1~4)로. 미측정이면 None."""
    if score is None:
        return None
    return int(round(max(1, min(4, score))))


def _flatten_measured(details: dict) -> list[dict]:
    """details 의 sub_ledger 에서 measured==True 하위역량만 평탄화."""
    out = []
    for comp_key, comp in (details or {}).items():
        if not isinstance(comp, dict):
            continue
        ledger = comp.get("sub_ledger") or {}
        for sub_name, e in ledger.items():
            if not isinstance(e, dict) or not e.get("measured"):
                continue
            score = e.get("score")
            if score is None:
                continue
            out.append({
                "comp_key": comp_key,
                "sub_name": sub_name,
                "score": float(score),
                "level": _sub_level(score) or 1,
                "evidence": [q for q in (e.get("evidence") or []) if q],
                # E-2c/R-1: 확신도(1/N 탐지·레벨갈림) — tie-break·배지에 사용.
                "borderline": e.get("borderline"),
            })
    return out


def _pick_citation(evidence: list[str], used: set[str]) -> str | None:
    """아직 다른 카드에 쓰이지 않은 근거 발화 1건 반환 (인용문 중복 금지)."""
    for q in evidence:
        if q and q.strip() and q.strip() not in used:
            used.add(q.strip())
            return q.strip()
    return None


def _build_entry(item: dict, track: str, used_citations: set[str], *,
                 is_strength: bool) -> dict:
    comp_key, sub_name = item["comp_key"], item["sub_name"]
    course = get_track_course(comp_key, sub_name, track) or {}
    category = CATEGORY_LABELS.get(comp_key, comp_key)
    meta = TRACK_META.get(track, {})
    citation = _pick_citation(item["evidence"], used_citations)

    if is_strength:
        overview = (
            f"'{sub_name}'은(는) 이미 리더님의 대표 강점입니다. 이제 학습을 "
            "넘어, 조직의 멘토이자 스폰서로서 이 강점을 후배 리더에게 전수할 "
            "때입니다."
        )
        bullets = [
            f"멘토·스폰서 역할: {course.get('subtitle', '')}",
            f"제안 형식: {meta.get('format', '')} — {meta.get('format_desc', '')}",
        ]
    else:
        target = meta.get("target_level", item["level"] + 1)
        overview = (
            f"현재 Lv.{item['level']} 수준에서 Lv.{target}(으)로 한 단계 "
            f"도약하면, '{sub_name}'의 리더십 임팩트가 크게 확장됩니다."
        )
        bullets = [
            f"도달 목표(Lv.{target}): {course.get('subtitle', '')}",
            f"학습 형식: {meta.get('format', '')} — {meta.get('format_desc', '')}",
        ]

    # R-2: borderline(1/N 탐지·레벨갈림) 후보가 카드에 오르면 '근거 제한적'
    #   배지 데이터를 실어 보낸다(E-2c 원칙 — 확신도를 숨기지 않고 노출).
    _bl = item.get("borderline") or None
    return {
        "type": "강점 활용" if is_strength else "성장 과제",
        "track": track,
        "track_format": meta.get("format", ""),
        "category": category,
        "sub_competency": sub_name,
        "score": round(item["score"], 1),
        "level": item["level"],
        "target_level": meta.get("target_level"),
        "course": course.get("course", f"{sub_name} 과정"),
        "subtitle": course.get("subtitle", ""),
        "vod_url": course.get("vod_url", ""),
        "reason_overview": overview,
        "reason_bullets": bullets,
        "bei_citation": citation,
        "is_strength": is_strength,
        "evidence_limited": bool(_bl),  # R-2: 프론트 '근거 제한적' 배지 트리거
        "borderline": _bl,
    }


def _lv4_reference(comp_key: str, sub_name: str) -> str:
    """해당 하위역량의 Lv.4 levels + examples 서술 (게이트 판정 기준)."""
    fw = COMPETENCY_FRAMEWORK.get(comp_key, {})
    for ind in fw.get("indicators", {}).values():
        if ind.get("name") == sub_name:
            lv = ind.get("levels", {}).get(4, "")
            ex = ind.get("examples", {}).get(4, "")
            return f"{lv} / {ex}"
    return ""


async def _strength_gate_pass(item: dict, llm) -> bool:
    """P0-5 근거 검증 게이트 — 인용 발화가 해당 하위역량 Lv.4 서술과 의미적으로
    매칭되는지 LLM 으로 검증. llm 없으면 보수적으로 False(카드 생성 안 함).
    판정은 '매칭 여부 + 근거 한 줄' 로 구조화해 로깅한다."""
    if llm is None:
        return False
    ref = _lv4_reference(item["comp_key"], item["sub_name"])
    quotes = " / ".join(item["evidence"][:3])
    prompt = (
        "[역할] 리더십 평가 검증관. 아래 '리더 발화'가 해당 하위역량의 "
        "'Lv.4(최고 수준) 기준'에 실제로 부합하는지 냉정하게 판정하라.\n"
        f"[하위역량] {item['sub_name']}\n"
        f"[Lv.4 기준] {ref}\n"
        f"[리더 발화] {quotes}\n\n"
        "주의: 발화 표면의 단어가 아니라 '행동의 수준'으로 판정하라. 예: "
        "'제가 직접 나서서 처리해 마감을 맞췄다'는 실무자적 직접 개입(Lv.1~2)"
        "이며, 시스템·조직 차원의 혁신(Lv.4)이 아니다.\n"
        '출력(JSON): {"match": true|false, "reason": "판정 근거 한 줄"}'
    )
    try:
        raw = await llm._generate_with_retry(
            prompt, max_tokens=4096, json_mode=True,
            temperature=0, call_type="dtrack_gate",  # T-1: 판정 결정론
        )
    except Exception as e:  # noqa: BLE001
        # 🚨 V-1#4: '빈 응답/오류로 미검증'(fail-closed) 과 '판단에 의한 차단'을
        #   로그에서 구분한다. 이건 판단이 아니라 게이트가 못 돈 것이다.
        logger.warning(
            "🚧 D트랙 게이트 미검증(빈응답/오류 → fail-closed 미생성, '판단 아님') "
            "[%s]: %s", item["sub_name"], str(e)[:100],
        )
        return False
    try:
        import json as _json
        raw = (raw or "").replace("```json", "").replace("```", "").strip()
        if not raw:
            logger.warning(
                "🚧 D트랙 게이트 빈 응답 → fail-closed 미생성('판단 아님') [%s]",
                item["sub_name"])
            return False
        res = _json.loads(raw)
        match = bool(res.get("match"))
        logger.info(
            "🔎 D트랙 게이트 판단 [%s] match=%s · %s",
            item["sub_name"], match, str(res.get("reason"))[:80],
        )
        return match
    except Exception as e:  # noqa: BLE001
        logger.warning(
            "🚧 D트랙 게이트 파싱 실패 → fail-closed 미생성('판단 아님') [%s]: %s",
            item["sub_name"], str(e)[:80])
        return False


async def build_course_recommendation(
    details: dict, transcript: str = "", job_weights: dict | None = None,
    llm=None,
) -> dict | None:
    """measured 하위역량 → 성장 3(A~C) + 강점 1(D, 게이트 통과 시) = 4개."""
    measured = _flatten_measured(details)
    if not measured:
        logger.warning("교육 추천: measured 하위역량 없음 → 추천 생략")
        return None

    # C-3: 후보(measured)가 2개 이하면 우선순위 산정이 무의미 → 카드 미발행
    #   (정성 분석까지만). measured 3~5 이면 추천 개수를 후보 수로 상한한다.
    #   대역량 max2 로 후보가 부족해도 제약을 완화하지 않고 개수를 줄인다.
    n_measured = len(measured)
    if n_measured < 3:
        logger.info(
            "교육 추천: measured %d < 3 → 추천 카드 생략(정성 분석만)",
            n_measured)
        return None
    _total_cap = min(4, n_measured)  # 최대 measured 수(억지로 채우지 않음)

    weights = job_weights or {}
    for m in measured:
        jw = float(weights.get(m["comp_key"], DEFAULT_JOB_WEIGHT))
        ev_boost = 1.0 + 0.1 * min(len(m["evidence"]), 3)  # 근거발화수 보정
        m["rec_score"] = (4 - m["score"]) * jw * ev_boost

    used_citations: set[str] = set()
    per_comp: dict[str, int] = {}
    MAX_PER_COMP = 2
    picks: list[dict] = []

    # ── 강점(D) 후보: score≥3.5 & 근거 2건+ & 게이트 통과 ──
    strength_entry = None
    d_cands = sorted(
        [m for m in measured
         if m["score"] >= STRENGTH_MIN_SCORE
         and len(m["evidence"]) >= STRENGTH_MIN_EVIDENCE],
        key=_strength_candidate_key,  # R-1: 점수 동점도 완전 결정론
    )
    for cand in d_cands:
        if await _strength_gate_pass(cand, llm):
            strength_entry = _build_entry(
                cand, "D", used_citations, is_strength=True)
            per_comp[cand["comp_key"]] = 1
            picks.append((cand["comp_key"], cand["sub_name"]))
            break

    # ── 성장(A~C): measured & level<4, 추천점수 상위, 대역량 max2 ──
    growth: list[dict] = []
    # C-3: 총 카드 수를 measured 후보 수로 상한(_total_cap). D 슬롯을 뺀 나머지.
    growth_target = _total_cap - (1 if strength_entry else 0)
    growth_pool = sorted(
        [m for m in measured
         if m["level"] < 4 and (m["comp_key"], m["sub_name"]) not in picks],
        key=deterministic_candidate_key,  # R-1: rec_score 동점 → 완전 결정론
    )
    for m in growth_pool:
        if len(growth) >= growth_target:
            break
        if per_comp.get(m["comp_key"], 0) >= MAX_PER_COMP:
            continue
        track = _LEVEL_TO_TRACK.get(m["level"], "A")
        growth.append(_build_entry(m, track, used_citations, is_strength=False))
        per_comp[m["comp_key"]] = per_comp.get(m["comp_key"], 0) + 1

    logger.info(
        "🎯 Level-Up 추천: 성장 %d + 강점 %d (D게이트 %s)",
        len(growth), 1 if strength_entry else 0,
        "통과" if strength_entry else "미생성",
    )

    # T5 #4: 추천 카드 본문이 완전히 동일한 쌍이 있으면 경고 로깅.
    _cards = growth + ([strength_entry] if strength_entry else [])
    _bodies = [(c["course"], c["subtitle"], c["reason_overview"]) for c in _cards]
    if len(_bodies) != len(set(_bodies)):
        logger.warning("⚠️ 추천 카드 본문 중복 발견 — 콘텐츠 다양화 필요: %s",
                       [c["sub_competency"] for c in _cards])

    result = {"intro": SECTION_INTRO, "growth": growth}
    if strength_entry:
        result["strength"] = strength_entry
    return result
