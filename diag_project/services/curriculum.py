"""맞춤 교육체계도 구성: 고른 범위(회사 또는 본부·실·팀)의 진단 결과로 Pool 에서 과정을 골라 체계도를 짠다.

규칙(숫자는 아래 상수, 모두 저장된 리포트 값으로만 계산 — 지어내지 않음)
  1) 범위 안 참여자별 최신 리포트의 하위역량 점수 → 레벨(1~4, 반올림·클램프; course_recommender 와 같은 규칙)
     - 신규 리포트: details[역량].sub_ledger 의 measured 항목만 / 구 리포트: details[역량].sub_scores
  2) 역량별 평균(사람별 하위역량 평균의 평균)으로 약한 순 정렬 → 하위 FOCUS_TOP 개 = '집중 역량'
     (단, 평균이 FOCUS_MAX_AVG 미만일 때만. 조직을 고르면 회사 전체가 비교 기준: 기준보다 많이 낮은 순으로 정렬하고,
      기준보다 낮으면 3.0 이상이어도 집중)
  3) 하위역량마다: 개선 대상 = Lv.1~3, 강점 = Lv.4
     - 필수: 집중 역량 & 개선 대상 비율 ≥ REQUIRED_RATIO
     - 선택: 개선 대상 비율 ≥ ELECTIVE_RATIO
     - 강점 확산(D): Lv.4 인원 ≥ max(STRENGTH_MIN_N, 측정 인원 × STRENGTH_RATIO)
     - 트랙: 개선 대상 중 가장 많은 레벨(동률이면 낮은 레벨) → Lv1=A, Lv2=B, Lv3=C
  4) 진단 완료 MIN_REPORTS 명 미만이면 체계도를 짜지 않는다(표본 부족 안내).
"""
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Optional

from diag_project.data.competencies import COMPETENCY_FRAMEWORK
from diag_project.services import course_pool

MIN_REPORTS = 3
FOCUS_TOP = 2
FOCUS_MAX_AVG = 3.0
REQUIRED_RATIO = 0.5
ELECTIVE_RATIO = 0.3
STRENGTH_MIN_N = 2
STRENGTH_RATIO = 0.2
_LEVEL_TO_TRACK = {1: "A", 2: "B", 3: "C"}

_ORDER = list(COMPETENCY_FRAMEWORK.keys())
_NAMES = {k: v.get("name", k) for k, v in COMPETENCY_FRAMEWORK.items()}


def _level(score: Any) -> Optional[int]:
    try:
        s = float(score)
    except (TypeError, ValueError):
        return None
    return int(round(max(1.0, min(4.0, s))))


def sub_levels(details: Dict[str, Any]) -> Dict[str, Dict[str, int]]:
    """한 리포트의 details → {역량키: {하위역량: 레벨}} (측정된 것만)."""
    out: Dict[str, Dict[str, int]] = {}
    for ck in _ORDER:
        d = (details or {}).get(ck) or {}
        subs: Dict[str, int] = {}
        ledger = d.get("sub_ledger")
        if isinstance(ledger, dict) and ledger:
            for name, e in ledger.items():
                if isinstance(e, dict) and e.get("measured"):
                    lv = _level(e.get("score"))
                    if lv:
                        subs[name] = lv
        else:
            for name, v in (d.get("sub_scores") or {}).items():
                lv = _level(v)
                if lv:
                    subs[name] = lv
        if subs:
            out[ck] = subs
    return out


def _comp_avgs(per_person: List[Dict[str, Dict[str, int]]]) -> Dict[str, Optional[float]]:
    acc: Dict[str, List[float]] = defaultdict(list)
    for p in per_person:
        for ck, subs in p.items():
            acc[ck].append(sum(subs.values()) / len(subs))
    return {ck: (round(sum(v) / len(v), 2) if v else None) for ck, v in ((k, acc.get(k, [])) for k in _ORDER)}


def build_curriculum(details_list: Iterable[Dict[str, Any]],
                     baseline_details: Optional[Iterable[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """범위 안 리포트 details 목록 → 맞춤 체계도. baseline 은 비교 기준(예: 조직을 골랐을 때 회사 전체)."""
    per_person = [sub_levels(d) for d in details_list]
    per_person = [p for p in per_person if p]
    n = len(per_person)
    base = {
        "n_reports": n, "min_reports": MIN_REPORTS, "tracks": course_pool.tracks(),
        "rules": {"focus_top": FOCUS_TOP, "focus_max_avg": FOCUS_MAX_AVG, "required_ratio": REQUIRED_RATIO,
                  "elective_ratio": ELECTIVE_RATIO, "strength_min_n": STRENGTH_MIN_N, "strength_ratio": STRENGTH_RATIO},
    }
    if n < MIN_REPORTS:
        return {**base, "status": "insufficient", "competencies": [], "summary": None}

    avgs = _comp_avgs(per_person)
    base_avgs: Dict[str, Optional[float]] = {}
    if baseline_details is not None:
        bp = [p for p in (sub_levels(d) for d in baseline_details) if p]
        if bp:
            base_avgs = _comp_avgs(bp)

    measured = [ck for ck in _ORDER if avgs.get(ck) is not None]
    # 비교 기준이 있으면 '기준보다 얼마나 낮은가'를 먼저, 없으면 평균이 낮은 순
    def _gap(ck: str) -> float:
        b = base_avgs.get(ck)
        return (avgs[ck] - b) if b is not None else 0.0
    ranked = sorted(measured, key=lambda ck: (_gap(ck), avgs[ck]))
    focus = set()
    for ck in ranked[:FOCUS_TOP]:
        below_base = base_avgs.get(ck) is not None and avgs[ck] < base_avgs[ck]
        if avgs[ck] < FOCUS_MAX_AVG or below_base:
            focus.add(ck)

    comps = []
    for ck in sorted(measured, key=lambda c: (c not in focus, avgs[c])):
        rows = []
        for sub in course_pool.subs_of(ck):
            levels = [p[ck][sub] for p in per_person if ck in p and sub in p[ck]]
            m = len(levels)
            if m == 0:
                continue
            dist = Counter(levels)
            need = [lv for lv in levels if lv <= 3]
            need_ratio = len(need) / m
            strong = dist.get(4, 0)
            items = []
            if need:
                common = Counter(need).most_common()
                top = max(c for _, c in common)
                lv = min(l for l, c in common if c == top)
                track = _LEVEL_TO_TRACK[lv]
                tier = None
                if ck in focus and need_ratio >= REQUIRED_RATIO:
                    tier = "required"
                elif need_ratio >= ELECTIVE_RATIO:
                    tier = "elective"
                course = course_pool.get_course(ck, sub, track) if tier else None
                if course:
                    items.append({"tier": tier, "track": track, **course, "people": len(need),
                                  "reason": f"측정 {m}명 중 {len(need)}명({round(need_ratio * 100)}%)이 Lv.1~3, 가장 많은 수준 Lv.{lv}"})
            if strong >= max(STRENGTH_MIN_N, m * STRENGTH_RATIO):
                course = course_pool.get_course(ck, sub, "D")
                if course:
                    items.append({"tier": "strength", "track": "D", **course, "people": strong,
                                  "reason": f"측정 {m}명 중 {strong}명이 Lv.4(강점) — 사내 확산·멘토 역할"})
            if items:
                rows.append({"sub": sub, "measured": m, "dist": {str(k): dist.get(k, 0) for k in (1, 2, 3, 4)},
                             "avg_level": round(sum(levels) / m, 2), "items": items})
        comps.append({
            "key": ck, "name": _NAMES[ck], "avg": avgs[ck], "baseline_avg": base_avgs.get(ck),
            "priority": "focus" if ck in focus else "develop",
            "rows": rows,
        })

    focus_names = [f"{_NAMES[ck]}({avgs[ck]:.1f})" for ck in ranked if ck in focus]
    n_req = sum(1 for c in comps for r in c["rows"] for i in r["items"] if i["tier"] == "required")
    n_ele = sum(1 for c in comps for r in c["rows"] for i in r["items"] if i["tier"] == "elective")
    n_str = sum(1 for c in comps for r in c["rows"] for i in r["items"] if i["tier"] == "strength")
    summary = (f"진단 완료 {n}명 기준. 집중 역량: {', '.join(focus_names) if focus_names else '없음(전 역량 평균 이상)'}. "
               f"필수 {n_req}개 · 선택 {n_ele}개 · 강점 확산 {n_str}개 과정으로 구성했습니다.")
    return {**base, "status": "ok", "competencies": comps, "summary": summary,
            "counts": {"required": n_req, "elective": n_ele, "strength": n_str}}
