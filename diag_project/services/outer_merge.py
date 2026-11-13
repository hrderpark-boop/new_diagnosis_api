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


def run_evaluated(run_result: Dict[str, Any] | None, sub: str) -> bool:
    """(2026-11-02 P3) 이 run 이 그 하위역량을 판정했는가 — 생략된 run(None)은 아니오, 한정 판정(_eval_subs)이면 그 칸만."""
    if not run_result:
        return False
    ev = run_result.get("_eval_subs")
    return ev is None or sub in ev


def _sub_state(row: Dict[str, Any]) -> tuple:
    return (bool(row.get("measured")), row.get("level"), row.get("gate_status"))


def disagreeing_subs(run_results: List[Dict[str, Any] | None]) -> List[str]:
    """(2026-11-02 P3) 앞 run 들의 원장이 갈린 하위역량(측정 여부·레벨·게이트 상태 중 하나라도). 비면 전부 일치 → 마지막 run 생략.
    오류 폴백 run 이 있으면 전부 갈린 것으로 본다(마지막 run 을 전체 판정으로)."""
    runs = [r for r in run_results if r]
    if not runs:
        return []
    subs: List[str] = []
    for r in runs:
        for s in (r.get("sub_ledger") or {}):
            if s not in subs:
                subs.append(s)
    if any(r.get("_error_fallback") for r in runs):
        return subs
    out = []
    for s in subs:
        states = {_sub_state((r.get("sub_ledger") or {}).get(s) or {}) for r in runs}
        if len(states) > 1:
            out.append(s)
    return out


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
        "evaluated": run_evaluated(run_result, sub),   # (P3) 생략·한정 판정 run 은 False
    }


# ── (2026-11-14 P12d) 최종 레벨을 낸 run 고르기 ───────────────────────────────
#   병합 결과의 level_gate·근거 인용 맨 앞·영역 서술이 run0 고정이라, 판정이 2·3·3 이면 최종 3.0 인데
#   사유는 "…Lv.2" 로 끝나는 run0 것이 남았다. 게이트 투표(level_gate.merge_votes)가 '채택 레벨을 낸 표의 사유'를
#   쓰는 것과 같은 방식으로, 칸마다 최종 레벨을 낸 첫 run 의 것을 쓴다.

# 영역 서술 필드 — 판정 전용 run(outer≥1, DEEP_JUDGE_ONLY)은 이 필드들을 빈 문자열로 낸다(llm_service.judge_only_tail).
_NARRATIVE_FIELDS = ("comment", "strength_point", "growth_point", "gap_analysis", "situational_pattern")
_SAR_STEPS = ("1_situation", "2_action", "3_result")


def _narrative_slots(run_result: Dict[str, Any] | None) -> set:
    """이 run 이 실제로 채운 서술 칸(서술 필드 + S/A/R description). 빈 문자열·공백은 채운 것으로 치지 않는다."""
    r = run_result or {}
    out = {f for f in _NARRATIVE_FIELDS if isinstance(r.get(f), str) and r[f].strip()}
    rp = r.get("reasoning_process")
    if isinstance(rp, dict):
        for st in _SAR_STEPS:
            step = rp.get(st)
            if isinstance(step, dict) and isinstance(step.get("description"), str) and step["description"].strip():
                out.add(f"reasoning_process.{st}")
    return out


def _run_level(run_result: Dict[str, Any] | None, sub: str):
    """그 run 이 낸 칸 레벨 — 측정(게이트 통과)된 칸만. 미측정·탈락·검증 미완료(pending 은 level 이 표시용)·칸 없음은 None."""
    row = ((run_result or {}).get("sub_ledger") or {}).get(sub) or {}
    if not row.get("measured") or row.get("level") is None:
        return None
    return int(row["level"])


def pick_level_run(run_results: List[Dict[str, Any] | None], sub: str, level) -> int | None:
    """그 칸을 실제로 판정한 run 가운데 최종 레벨과 같은 레벨을 낸 첫 run 의 순번. 없으면 None(최종이 미측정이어도 None)."""
    if level is None:
        return None
    for i, r in enumerate(run_results):
        if run_evaluated(r, sub) and _run_level(r, sub) == int(level):
            return i
    return None


def pick_base_run(run_results: List[Dict[str, Any] | None], final_levels: Dict[str, Any]) -> int:
    """영역 서술의 바탕 run — 칸별 레벨이 최종값과 가장 많이 일치하는 run. 동률이면 앞 run. 후보가 없으면 0(종전).

    일치 세는 법: 칸마다 (그 run 의 레벨, 미측정이면 None) == (최종 레벨, 미측정이면 None). 둘 다 미측정인 칸도 일치로 센다 —
      최종이 '근거 미확보'인 칸을 측정됐다고 서술한 run 보다, 그 칸을 똑같이 미측정으로 본 run 의 서술이 최종 원장과 덜 어긋난다.
      (모든 run 이 미측정인 칸은 후보 전부에 똑같이 더해져 순위를 바꾸지 않는다.)
    후보에서 빼는 run:
      · 생략된 run(None)·한정 판정 run(_eval_subs 가 있음 — 적응형 3회째는 갈린 칸만 판정하고 나머지는 미측정으로 둔다)
      · 오류 폴백 run
      · run0 이 채운 서술 칸을 하나라도 비운 run — 판정 전용 run 은 서술이 빈 문자열이라 바탕으로 삼으면 리포트 서술이 빈다.
    run0 이 없거나 오류 폴백이면 종전대로 0.
    """
    r0 = run_results[0] if run_results else None
    if not r0 or r0.get("_error_fallback"):
        return 0
    need = _narrative_slots(r0)
    best, best_n = 0, -1
    for i, r in enumerate(run_results):
        if not r or r.get("_eval_subs") is not None or r.get("_error_fallback"):
            continue
        if i and not need <= _narrative_slots(r):
            continue
        n = sum(1 for s, lv in final_levels.items() if _run_level(r, s) == lv)
        if n > best_n:                       # 같으면 앞 run 유지
            best, best_n = i, n
    return best


def _lead_evidence(lead: List[str] | None, union: List[str]) -> List[str]:
    """근거 합집합의 순서만 바꾼다 — lead(최종 레벨을 낸 run 의 인용)를 앞에, 나머지는 종전 순서대로. 중복 제거 규칙은 classify_sub 와 같다."""
    out: List[str] = []
    seen = set()
    for e in list(lead or []) + list(union or []):
        k = (e or "").strip()
        if k and k not in seen:
            seen.add(k)
            out.append(e)
    return out


def merge_competency(run_results: List[Dict[str, Any]], competency_key: str,
                     n_runs: int) -> Dict[str, Any]:
    """한 대역량의 outer run 결과들을 교집합 병합 → 단일 competency result.

    sub_ledger·점수는 교차 분류로 결정론적으로 재계산한다.
    (2026-11-14 P12d) 서술(S/A/R·comment·score_breakdown 등 바탕 필드)은 run0 고정이 아니라 칸별 레벨이 최종값과
    가장 많이 일치하는 run(pick_base_run, 동률이면 앞 run)에서 가져오고, 칸별 level_gate·근거 인용 맨 앞은
    최종 레벨을 낸 첫 run(pick_level_run)의 것을 쓴다. 고른 run 은 base_run·sub_ledger[칸].level_run 에 남긴다.
    """
    # 하위역량 목록은 run0 의 sub_ledger 순서 유지(바탕 run 이 바뀌어도 순서는 run0 기준)
    subs = list((((run_results[0] if run_results else None) or {}).get("sub_ledger") or {}).keys())

    sub_ledger: Dict[str, Any] = {}
    gate_counts = {"passed": 0, "failed": 0, "pending": 0, "n_a": 0}
    measured_count = 0
    class_counts = {"stable": 0, "semi": 0, "weak": 0, "dropped": 0}
    for sub in subs:
        # (2026-11-02 P3) 이 칸을 실제로 판정한 run 만 센다 — 생략된 마지막 run(None)·한정 판정에서 빠진 칸은 표가 아니다.
        #   앞 두 run 이 일치해 생략됐으면 2/2 일치 → stable. 갈려서 3회째를 돌렸으면 그 칸은 3표.
        _eval_runs = [r for r in run_results if run_evaluated(r, sub)]
        rows = [(r.get("sub_ledger") or {}).get(sub) or {} for r in _eval_runs]
        asked = any((r.get("sub_ledger") or {}).get(sub, {}).get("asked")
                    for r in _eval_runs)
        m = classify_sub(rows, len(rows) or n_runs)
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
            # (P12d) 최종 레벨을 낸 첫 run 의 인용을 맨 앞에 — 합집합·중복 제거는 그대로, 순서만 바뀐다.
            level_run = pick_level_run(run_results, sub, level)
            if level_run is not None:
                disp_ev = _lead_evidence(
                    ((run_results[level_run].get("sub_ledger") or {}).get(sub) or {}).get("evidence"), disp_ev)
        elif cls == "dropped":
            # 게이트가 2회 이상 적극 거절 → 근거 미확보.
            gate_status, status = "failed", "evidence_missing"
            level = score = None; disp_ev = []; level_run = None
        else:  # none
            gate_status = "n_a"
            status = "evidence_missing" if asked else "unexplored"
            level = score = None; disp_ev = []; level_run = None
        gate_counts[gate_status] += 1
        sub_ledger[sub] = {
            "asked": asked, "measured": m["measured"], "level": level,
            "score": score, "evidence": disp_ev, "status": status,
            "gate_status": gate_status, "borderline": m["borderline"],
            "stability": cls, "candidate_runs": cand_runs,
            # (2026-10-23) run 별 게이트 판정 — 리포트의 level_gate 는 run0 만 남아 weak(1/3)·탈락 사유를
            #   되짚을 수 없었다(cbd5210b '전략적 사고'). 어느 run 이 왜 떨어뜨렸는지 그대로 싣는다.
            "gate_runs": [gate_run_summary(r, sub) for r in run_results],
            # (P12d) 이 칸의 level_gate·근거 맨 앞을 가져온 run 순번(gate_runs 의 자리). 미측정 칸은 None.
            "level_run": level_run,
        }

    # (P12d) 바탕 run — 칸별 최종 레벨이 정해진 뒤에 고른다. 얕은 복사라 아래에서 바꾸는 키는 새 객체로 갈아 끼운다(run 원본 불변).
    base_run = pick_base_run(run_results, {s: v["level"] for s, v in sub_ledger.items()})
    base = dict(run_results[base_run] or {}) if run_results else {}
    base["base_run"] = base_run
    # (P12d) 칸별 level_gate — 측정 칸은 최종 레벨을 낸 run 의 판정·사유로 덮는다. 그 run 에 판정이 없으면 바탕 run 것 그대로.
    #   미측정 칸은 바탕 run 것 그대로(run 별 판정은 gate_runs 에 전부 있다). 어느 run 에도 level_gate 가 없으면 키를 만들지 않는다.
    _lg_src = base.get("level_gate")
    _lg = dict(_lg_src) if isinstance(_lg_src, dict) else {}
    _lg_set = False
    for _s, _v in sub_ledger.items():
        if _v["level_run"] is None:
            continue
        _g = ((run_results[_v["level_run"]] or {}).get("level_gate") or {}).get(_s)
        if _g:
            _lg[_s] = dict(_g)
            _lg_set = True
    if _lg_set or isinstance(_lg_src, dict):
        base["level_gate"] = _lg

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
    from diag_project.services.scoring import confidence_display as _cdisp
    base["score_breakdown"] = {
        "rubric_base": _behavior,
        "star_depth_bonus": _sb.get("star_depth_bonus", 0.0),
        "confidence_adj": _sb.get("confidence_adj", 0.0),   # (P4-7) 표시(★)용 — 점수 미반영
        "final": _final,
        **_cdisp(_sb.get("confidence_adj", 0.0)),
    }
    base.pop("_eval_subs", None)
    # I-4: 3회 중 1회라도 error-fallback 이면 이 대역량은 오염 → 표기 전파.
    if any((r or {}).get("_error_fallback") for r in run_results):
        base["_error_fallback"] = True
        base["_error_reason"] = next(
            ((r or {}).get("_error_reason") for r in run_results
             if (r or {}).get("_error_fallback")), "불명")
    return base


def merge_outer_runs(run_results_list: List[Dict[str, Dict]],
                     n_runs: int) -> Dict[str, Dict]:
    """outer run 3개의 competency_results 를 대역량별로 교집합 병합."""
    merged: Dict[str, Dict] = {}
    keys = list(run_results_list[0].keys())
    for ck in keys:
        per_run = [(rr or {}).get(ck) or None for rr in run_results_list]   # (P3) 생략된 run 은 None
        merged[ck] = merge_competency(per_run, ck, n_runs)
    return merged
