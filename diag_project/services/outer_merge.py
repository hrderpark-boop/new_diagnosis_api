"""S-1/I-1: E-2a×3 + 교집합 병합 — outer run 3회의 원장을 교차 분류.

E-2b(inner union, 측정 인플레)를 기각하고, '완결된 분석 파이프라인 3회(outer)'의
교집합으로 안정성을 판정한다.

  stable : 3회 전부 탐지(measured) + 레벨 일치 → 카드 자격, 배지 없음
  semi   : 2회 탐지, 또는 3회 탐지지만 레벨 갈림 → 카드 충원 + '근거 제한적' 배지
  weak   : 1회만 탐지 → 재현되지 않음 → measured 로 세지 않음(gate_status=failed)

레벨은 탐지된 표본의 다수결(3개 전부 다르면 중앙값). qualifying/measured 는
stable+semi(재현 측정)만 센다 — weak(1/3)은 노이즈로 취급해 발행을 부풀리지 않는다.

전부 순수 함수. 동일 입력 → 동일 출력(결정론). API 호출 없음.
"""
import statistics
from typing import Any, Dict, List

from diag_project.services.scoring import (
    competency_behavior_score, competency_final_score, competency_is_reference,
)


def _majority_level(levels: List[int]) -> int:
    """탐지된 표본 레벨의 다수결. 최빈값 유일하면 그것, 3개 전부 다르면 중앙값,
    2개 갈림 등 동률은 보수적 최소(레벨은 판정 축)."""
    from collections import Counter
    c = Counter(levels)
    top = max(c.values())
    modes = [v for v, n in c.items() if n == top]
    if len(modes) == 1:
        return modes[0]
    if len(levels) == 3 and len(set(levels)) == 3:
        return int(statistics.median(levels))
    return min(levels)


def classify_sub(run_rows: List[Dict[str, Any]], n_runs: int) -> Dict[str, Any]:
    """한 하위역량의 3(=n_runs) outer run 판정을 교차 분류.

    run_rows: 각 run 의 sub_ledger 행(없으면 {}). 사용 필드: measured, level,
              evidence.
    반환: {class, measured, level, evidence(union), borderline, detection_count}.
    """
    present = [r for r in run_rows if r and r.get("measured")]
    detect = len(present)
    levels = [int(r["level"]) for r in present
              if r.get("level") is not None]
    # 근거 합집합(표시용) — 중복 제거, 순서 보존
    ev_union: List[str] = []
    seen = set()
    for r in run_rows:
        for e in (r.get("evidence") or []) if r else []:
            k = (e or "").strip()
            if k and k not in seen:
                seen.add(k)
                ev_union.append(e)

    same_level = len(set(levels)) <= 1
    if detect >= n_runs and same_level and levels:
        cls = "stable"
    elif detect >= 2:
        cls = "semi"
    elif detect == 1:
        cls = "weak"
    else:
        cls = "none"

    merged_level = _majority_level(levels) if levels else None
    lvl_range = [min(levels), max(levels)] if levels and not same_level else None

    borderline = None
    if cls == "semi":
        flags = []
        if detect < n_runs:
            flags.append("detection")
        if lvl_range is not None:
            flags.append("level")
        borderline = {"flags": flags or ["detection"],
                      "detection_count": detect, "of": n_runs,
                      "level_range": lvl_range}

    return {"class": cls, "measured": cls in ("stable", "semi"),
            "level": merged_level if cls in ("stable", "semi") else None,
            "evidence": ev_union, "borderline": borderline,
            "detection_count": detect, "of": n_runs}


def merge_competency(run_results: List[Dict[str, Any]], competency_key: str,
                     n_runs: int) -> Dict[str, Any]:
    """한 대역량의 outer run 결과들을 교집합 병합 → 단일 competency result.

    서술(S/A/R·comment·score_breakdown)은 run0(기준 표본)에서 가져오고,
    sub_ledger·점수는 교차 분류로 결정론적으로 재계산한다.
    """
    base = dict(run_results[0]) if run_results else {}
    # 하위역량 목록은 run0 의 sub_ledger 순서 유지
    subs = list((run_results[0].get("sub_ledger") or {}).keys())

    sub_ledger: Dict[str, Any] = {}
    gate_counts = {"passed": 0, "failed": 0, "pending": 0, "n_a": 0}
    measured_count = 0
    class_counts = {"stable": 0, "semi": 0, "weak": 0}
    for sub in subs:
        rows = [(r.get("sub_ledger") or {}).get(sub) or {} for r in run_results]
        asked = any((r.get("sub_ledger") or {}).get(sub, {}).get("asked")
                    for r in run_results)
        m = classify_sub(rows, n_runs)
        cls = m["class"]
        if cls in class_counts:
            class_counts[cls] += 1

        if m["measured"]:
            gate_status, status = "passed", "measured"
            level = int(m["level"]); score = float(level)
            measured_count += 1
            disp_ev = m["evidence"]
        elif cls == "weak":
            # 1회만 탐지 → 재현 실패. measured 아님(근거 미확보로 표기).
            gate_status, status = "failed", "evidence_missing"
            level = score = None; disp_ev = []
        else:  # none
            gate_status = "n_a"
            status = "evidence_missing" if asked else "unexplored"
            level = score = None; disp_ev = []
        gate_counts[gate_status] += 1
        sub_ledger[sub] = {
            "asked": asked, "measured": m["measured"], "level": level,
            "score": score, "evidence": disp_ev, "status": status,
            "gate_status": gate_status, "borderline": m["borderline"],
            "stability": cls,
        }

    base["sub_ledger"] = sub_ledger
    base["sub_scores"] = {s: v["score"] for s, v in sub_ledger.items()}
    base["measured_count"] = measured_count
    base["asked_count"] = sum(1 for v in sub_ledger.values() if v["asked"])
    base["sub_total"] = len(sub_ledger)
    base["gate_status_counts"] = gate_counts
    base["gate_pending"] = gate_counts.get("pending", 0) > 0
    base["stability_counts"] = class_counts
    base["is_reference"] = competency_is_reference(measured_count,
                                                   len(sub_ledger))
    _behavior = competency_behavior_score(list(base["sub_scores"].values()))
    _sb = base.get("score_breakdown") or {}
    _final = competency_final_score(
        _behavior, star_bonus=_sb.get("star_depth_bonus", 0.0),
        confidence_adj=_sb.get("confidence_adj", 0.0))
    base["behavior_score"] = _behavior
    base["score"] = _final
    base["score_breakdown"] = {
        "rubric_base": _behavior,
        "star_depth_bonus": _sb.get("star_depth_bonus", 0.0),
        "confidence_adj": _sb.get("confidence_adj", 0.0),
        "final": _final,
    }
    # I-4: 3회 중 1회라도 error-fallback 이면 이 대역량은 오염 → 표기 전파.
    if any(r.get("_error_fallback") for r in run_results):
        base["_error_fallback"] = True
        base["_error_reason"] = next(
            (r.get("_error_reason") for r in run_results
             if r.get("_error_fallback")), "불명")
    return base


def merge_outer_runs(run_results_list: List[Dict[str, Dict]],
                     n_runs: int) -> Dict[str, Dict]:
    """outer run 3개의 competency_results 를 대역량별로 교집합 병합."""
    merged: Dict[str, Dict] = {}
    keys = list(run_results_list[0].keys())
    for ck in keys:
        per_run = [rr.get(ck) or {} for rr in run_results_list]
        merged[ck] = merge_competency(per_run, ck, n_runs)
    return merged
