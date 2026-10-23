"""S-1/I-1 → (2026-10-23) 다수결 병합: outer run 3회의 원장을 교차 분류.

  stable  : 3회 전부 탐지(게이트 통과) + 레벨 일치 → 카드 자격, 배지 없음
  semi    : 2회 탐지, 또는 3회 탐지지만 레벨 갈림 → measured + '근거 제한적' 배지
  weak    : 1회만 탐지(나머지는 근거 후보 없음) → measured + 배지(detection 1/3)   ← 2026-10-23 변경(이전엔 미측정)
  dropped : 게이트 탈락(dropped) 2회 이상 → 미측정(근거 미확보). 1회 탈락만으로는 떨어뜨리지 않는다.
  none    : 한 번도 근거 후보가 없음 → 미측정

레벨은 통과한 run 의 verified_level 중앙값(짝수면 낮은 쪽 — 레벨은 판정 축이라 보수적).
measured = stable+semi+weak. qualifying/셧다운은 여전히 stable 만 센다(llm_service).

배경: 교집합(weak 미측정)은 cbd5210b '전략적 사고'처럼 3회 중 1회 Lv.1 통과·2회 미탐지를 '근거 미확보'로
떨어뜨렸다. 다수결로 바꿔 탐지 1회는 살리고(배지), 게이트가 2회 이상 적극 거절한 것만 떨어뜨린다.

전부 순수 함수. 동일 입력 → 동일 출력(결정론). API 호출 없음.
"""
import statistics
from typing import Any, Dict, List

from diag_project.services.scoring import (
    competency_behavior_score, competency_final_score, competency_is_reference,
)


def _median_level(levels: List[int]) -> int:
    """통과한 run 의 verified_level 중앙값. 짝수 개면 낮은 쪽(보수적)."""
    srt = sorted(int(x) for x in levels)
    return srt[(len(srt) - 1) // 2]


# 하위 호환(테스트·외부 참조): 이름만 유지, 중앙값 규칙으로 동작한다.
_majority_level = _median_level


def classify_sub(run_rows: List[Dict[str, Any]], n_runs: int) -> Dict[str, Any]:
    """한 하위역량의 3(=n_runs) outer run 판정을 교차 분류.

    run_rows: 각 run 의 sub_ledger 행(없으면 {}). 사용 필드: measured, level,
              evidence.
    반환: {class, measured, level, evidence(union), borderline, detection_count}.
    """
    present = [r for r in run_rows if r and r.get("measured")]
    detect = len(present)
    # 게이트가 '실행돼서 탈락'시킨 run 수(gate_status=failed). 근거 후보가 없어 게이트가 안 돈 run(n_a)은 세지 않는다.
    dropped_n = sum(1 for r in run_rows if r and r.get("gate_status") == "failed")
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
    if detect >= 2:
        cls = "stable" if (detect >= n_runs and same_level and levels) else "semi"
    elif dropped_n >= 2:
        cls = "dropped"            # 2회 이상 적극 거절 → 근거 미확보
    elif detect == 1:
        cls = "weak"               # 1회 통과(+탈락 1회 이하) → measured + 배지
    else:
        cls = "none"

    measured = cls in ("stable", "semi", "weak")
    merged_level = _median_level(levels) if (levels and measured) else None
    lvl_range = [min(levels), max(levels)] if levels and not same_level else None

    borderline = None
    if cls in ("semi", "weak"):
        flags = []
        if detect < n_runs:
            flags.append("detection")
        if lvl_range is not None:
            flags.append("level")
        borderline = {"flags": flags or ["detection"],
                      "detection_count": detect, "of": n_runs,
                      "level_range": lvl_range,
                      "dropped_runs": dropped_n}

    return {"class": cls, "measured": measured,
            "level": merged_level,
            "evidence": ev_union, "borderline": borderline,
            "detection_count": detect, "dropped_count": dropped_n, "of": n_runs}


def gate_run_summary(run_result: Dict[str, Any], sub: str) -> Dict[str, Any]:
    """한 outer run 의 (게이트 판정, 원장) 을 한 줄로. 게이트가 안 돌았으면(근거 후보 없음) verdict=None."""
    g = ((run_result or {}).get("level_gate") or {}).get(sub) or None
    row = ((run_result or {}).get("sub_ledger") or {}).get(sub) or {}
    claimed = row.get("claimed_level")      # _parsed 는 병합 전에 지워지므로 원장 행에서 읽는다
    return {
        "claimed_level": claimed,
        "verified_level": g.get("verified_level") if g else None,
        "category": g.get("category") if g else None,
        "dropped": bool(g.get("dropped")) if g else None,
        "pending": bool(g.get("pending")) if g else None,
        "reason": (g.get("reason") or "")[:120] if g else None,
        "reselected": bool(g.get("reselected")) if g else False,     # (2026-10-23 A) 근거 재선택을 거친 판정
        "measured": bool(row.get("measured")),
        "gate_status": row.get("gate_status"),
    }


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
    class_counts = {"stable": 0, "semi": 0, "weak": 0, "dropped": 0}
    for sub in subs:
        rows = [(r.get("sub_ledger") or {}).get(sub) or {} for r in run_results]
        asked = any((r.get("sub_ledger") or {}).get(sub, {}).get("asked")
                    for r in run_results)
        m = classify_sub(rows, n_runs)
        cls = m["class"]
        # G: 근거 후보가 나온 run 수(게이트 탈락 포함) — '미탐색' 판정용.
        cand_runs = sum(1 for r in rows
                        if r and r.get("gate_status") not in (None, "n_a"))
        if cls in class_counts:
            class_counts[cls] += 1

        if m["measured"]:
            gate_status, status = "passed", "measured"
            level = int(m["level"]); score = float(level)
            measured_count += 1
            disp_ev = m["evidence"]
        elif cls == "dropped":
            # 게이트가 2회 이상 적극 거절 → 근거 미확보.
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
            "stability": cls, "candidate_runs": cand_runs,
            # (2026-10-23) run 별 게이트 판정 — 리포트의 level_gate 는 run0 만 남아 weak(1/3)·탈락 사유를
            #   되짚을 수 없었다(cbd5210b '전략적 사고'). 어느 run 이 왜 떨어뜨렸는지 그대로 싣는다.
            "gate_runs": [gate_run_summary(r, sub) for r in run_results],
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
