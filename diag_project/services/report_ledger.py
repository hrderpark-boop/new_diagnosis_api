"""리포트 원장 후처리(결정론) — 분석(LLM) 뒤, 종합 요약 앞에서 적용.

F. 측정 0 대역량의 평가 문장 금지
   측정된 하위역량이 하나도 없는 대역량에 LLM 이 쓴 코멘트·강점·개선·Gap 은 근거
   없는 평가다(예: 일관리 0/5 인데 "명확한 실행 원칙을 보유"). 코멘트를 정확히
   UNMEASURED_COMMENT 로 바꾸고 나머지 평가 서술은 비운다. 종합 요약 프롬프트도
   이 값을 보게 되어 미측정 대역량을 칭찬하지 않는다.

G. '미탐색'과 '사례 미확인' 구분 (2026-11-04 BEI 재정의 — docs/design_bei_2026-11.md §5)
   · not_explored(미탐색)  커버리지 원장에 covered·sweep_asked·unconfirmed 어디에도 없음 = 예산 소진으로 묻지 못함.
                          라벨 "시간 내 다루지 못한 항목", 점수 공란, measured False. 세션당 2개 이상이면 분석 린트 경고.
   · no_case(사례 미확인) SWEEP(또는 여는 앵커)에서 1회 물었는데 그런 일이 없다고 답함 → 1.0.
   · gate_dropped          사례는 있었으나 게이트가 행동 근거로 인정하지 않음 → 1.0, 문구만 다름.
   구 세션(커버리지 원장 없음)은 앵커 전달 판정(output_guard.anchor_overlap)으로 미탐색을 가른다.

모두 순수 함수(입력 dict 를 제자리 수정 + 요약 반환). LLM·DB 없음.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List

UNMEASURED_COMMENT = "이번 세션에서 확인되지 않았습니다."
ANCHOR_DELIVERED_MIN_OVERLAP = 2
_NEUTRAL_EMPTY_FIELDS = ("strength_point", "growth_point", "gap_analysis",
                         "situational_pattern")


def _chapter_coach_texts(history: Iterable[Dict[str, Any]],
                         chapter: str) -> List[str]:
    out = []
    for m in history or []:
        if m.get("role") != "model":
            continue
        if m.get("chapter") == chapter or (
                m.get("instruction") == "COMPETENCY_ALIGN"
                and m.get("chapter") in (None, chapter)):
            out.append(m.get("parts") or m.get("content") or "")
    return out


def anchor_delivered(coach_texts: List[str], chapter: str, sub_name: str) -> bool:
    """이 하위역량의 앵커 질문이 챕터 코치 메시지로 전달됐는가.

    앵커를 알 수 없으면(키/질문 없음) 판단 불가 → True(보수적: 근거 미확보 유지).
    """
    from diag_project.data.competencies import (
        find_sub_key_by_name, get_anchor_questions,
    )
    from diag_project.services.output_guard import anchor_overlap
    sub_key = find_sub_key_by_name(chapter, sub_name)
    anchors = get_anchor_questions(sub_key) if sub_key else []
    if not anchors:
        return True
    return any(anchor_overlap(t, aq) >= ANCHOR_DELIVERED_MIN_OVERLAP
               for t in coach_texts for aq in anchors)


def _had_candidate(row: Dict[str, Any]) -> bool:
    """심층분석이 이 하위역량에 근거 후보를 낸 적이 있는가(게이트 탈락 포함)."""
    if "candidate_runs" in row:                     # outer 병합 경로
        return int(row.get("candidate_runs") or 0) > 0
    return row.get("gate_status") not in (None, "n_a")   # 단일 run 경로


def mark_not_explored(competency_results: Dict[str, Dict[str, Any]],
                      history: Iterable[Dict[str, Any]],
                      store_meta: Dict[str, Any] | None = None) -> Dict[str, List[str]]:
    """G: 미탐색 재분류 → status=not_explored, asked False, 점수 공란. 반환: {대역량: [sub]}.

    (2026-11-04 BEI) store_meta["coverage"][대역량]["not_explored"] 가 있으면 그것이 기준(측정된 행은 건드리지 않는다).
    없으면(구 세션) asked 이지만 앵커 미전달 + 근거 후보 0 인 행을 미탐색으로 본다(history 에 chapter 정보가 필요).
    """
    from diag_project.services.scoring import NOT_EXPLORED_LABEL
    coverage = ((store_meta or {}).get("coverage") or {})
    changed: Dict[str, List[str]] = {}

    def _mark(ck: str, comp: Dict[str, Any], sub: str, row: Dict[str, Any]) -> None:
        row["status"] = "not_explored"
        row["asked"] = False
        row["measured"] = False
        row["evidence_measured"] = False
        row["score"] = None
        row["level"] = None
        row["level_label"] = NOT_EXPLORED_LABEL
        row["unconfirmed"] = False
        changed.setdefault(ck, []).append(sub)

    if coverage:
        for ck, comp in (competency_results or {}).items():
            ledger = comp.get("sub_ledger") or {}
            ne = set((coverage.get(ck) or {}).get("not_explored") or [])
            for sub, row in ledger.items():
                if sub in ne and isinstance(row, dict) and not row.get("measured"):
                    _mark(ck, comp, sub, row)
            if ck in changed:
                comp["asked_count"] = sum(1 for r in ledger.values() if isinstance(r, dict) and r.get("asked"))
                comp["not_explored_count"] = len(changed[ck])
        return changed

    history = list(history or [])
    if not any(m.get("chapter") for m in history):
        return {}
    for ck, comp in (competency_results or {}).items():
        ledger = comp.get("sub_ledger") or {}
        texts = None
        for sub, row in ledger.items():
            if not row.get("asked") or row.get("measured") or _had_candidate(row):
                continue
            if texts is None:
                texts = _chapter_coach_texts(history, ck)
            if anchor_delivered(texts, ck, sub):
                row["anchor_delivered"] = True
                continue
            row["anchor_delivered"] = False
            _mark(ck, comp, sub, row)
        if ck in changed:
            comp["asked_count"] = sum(
                1 for r in ledger.values()
                if r.get("asked") and r.get("status") != "not_explored")
            comp["not_explored_count"] = len(changed[ck])
    return changed


def is_unmeasured(comp: Dict[str, Any]) -> bool:
    """측정된 하위역량이 0 인 대역량(분석 실패 fallback 은 제외 — 별도 처리)."""
    if comp.get("_error_fallback"):
        return False
    ledger = comp.get("sub_ledger") or {}
    if ledger:
        # 게이트 검증 미완료(pending)는 근거가 있는 '도구 상태' — 미측정 아님.
        if any(r.get("gate_status") == "pending" for r in ledger.values()):
            return False
        return not any((r.get("evidence_measured") if "evidence_measured" in r else r.get("measured")) for r in ledger.values())
    if "evidence_measured_count" in comp:
        return int(comp.get("evidence_measured_count") or 0) == 0
    return int(comp.get("measured_count") or 0) == 0


def neutralize_unmeasured(competency_results: Dict[str, Dict[str, Any]]) -> List[str]:
    """F: 측정 0 대역량의 평가 서술을 결정론적으로 덮어쓴다(멱등). 반환: 대역량 키."""
    keys = []
    for ck, comp in (competency_results or {}).items():
        if not isinstance(comp, dict) or not is_unmeasured(comp):
            continue
        comp["comment"] = UNMEASURED_COMMENT
        for f in _NEUTRAL_EMPTY_FIELDS:
            comp[f] = ""
        rp = comp.get("reasoning_process")
        if isinstance(rp, dict):
            # S/A/R 해설도 평가다 — 서술만 비운다(인용 원문은 사실이라 보존).
            for step in rp.values():
                if isinstance(step, dict):
                    step["description"] = ""
        comp["unmeasured"] = True
        keys.append(ck)
    return keys


# ── (2026-10-29 P2-3 → 2026-11-04 BEI) 사례 미확인 → 1.0 정책 ─────────────────────────────────────
UNCONFIRMED_TEXT_NO_CASE = "이 항목은 대화에서 사례가 확인되지 않아 최저 수준으로 기록했습니다"
UNCONFIRMED_TEXT_NOT_EXPLORED = "이번 진단에서 이 항목까지 다루지 못해 최저 수준(1.0)으로 기록했습니다. 이어서 진행하면 채워집니다."   # (2026-11-06 P7-2)
UNCONFIRMED_TEXT_GATE_DROPPED = "사례는 말씀하셨으나 리더님이 직접 하신 행동이 확인되지 않아 최저 수준으로 기록했습니다"
UNCONFIRMED_TEXT_NO_ANSWER = UNCONFIRMED_TEXT_NO_CASE   # 하위호환 이름
UNCONFIRMED_BANNER_MIN = 6
NOT_EXPLORED_WARN_MIN = 2   # (결정 9) 세션당 미탐색 2개 이상이면 분석 린트 경고


def apply_unconfirmed_policy(competency_results: Dict[str, Dict[str, Any]],
                             store_meta: Dict[str, Any] | None) -> Dict[str, Any]:
    """측정되지 않은 하위역량 칸을 1.0('사례 미확인')으로 채운다 — 미탐색(not_explored)·검증 미완료(pending)는 건드리지 않는다.

    행에 남기는 것: score 1.0 · measured True(정책상 측정에 포함) · evidence_measured False · unconfirmed True ·
    unconfirmed_kind no_case|gate_dropped · unconfirmed_text. 측정된 행에는 level_label 만 붙인다.
      no_case      SWEEP·여는 앵커에서 물었는데 사례가 없음(store_meta.unconfirmed/no_case_subs) 또는 근거 후보 자체가 없음
      gate_dropped 사례는 있었으나(근거 후보 있음) 게이트가 행동 근거로 인정하지 않음
    probe_deficit 은 BEI 에서 항상 False(미탐색은 별도 상태). 대역량: sub_scores·behavior_score·score 재계산(미탐색 None 제외),
    measured_count(미확인 포함)·evidence_measured_count·unconfirmed_count·not_explored_count·level_label. 반환: 합계.
    """
    from diag_project.services.scoring import (
        UNCONFIRMED_LABEL, UNCONFIRMED_SCORE, competency_behavior_score, competency_final_score,
        competency_is_reference, competency_level_label, level_label,
    )
    meta = store_meta or {}
    unc_map = meta.get("unconfirmed") or {}
    noc_map = meta.get("no_case_subs") or {}
    totals = {"unconfirmed_total": 0, "probe_deficit_unconfirmed": 0, "evidence_measured_total": 0, "pending_total": 0,
              "not_explored_total": 0, "gate_dropped_total": 0, "no_case_total": 0}
    for ck, comp in (competency_results or {}).items():
        if not isinstance(comp, dict) or comp.get("_error_fallback"):
            continue
        ledger = comp.get("sub_ledger") or {}
        n_unc = n_ev = n_ne = 0
        asked_no_case = set(unc_map.get(ck) or []) | set(noc_map.get(ck) or [])
        for sub, row in ledger.items():
            if not isinstance(row, dict):
                continue
            row["probe_deficit"] = False
            if row.get("status") == "not_explored":
                # (2026-11-06 P7-2) 묻지 못한 칸도 1.0 '사례 미확인' — 같은 라벨·같은 점수. status/unconfirmed_kind 로 관리자·린트만 구분한다.
                n_ne += 1
                row.update({
                    "score": UNCONFIRMED_SCORE, "measured": True, "evidence_measured": False, "level": None,
                    "level_label": UNCONFIRMED_LABEL, "unconfirmed": True, "unconfirmed_kind": "not_explored",
                    "unconfirmed_text": UNCONFIRMED_TEXT_NOT_EXPLORED,
                })
                n_unc += 1
                continue
            if row.get("measured"):
                row["evidence_measured"] = True
                row["unconfirmed"] = False
                row["level_label"] = level_label(row.get("level"))
                n_ev += 1
                continue
            if row.get("gate_status") == "pending":
                totals["pending_total"] += 1      # 검증 미완료 — 점수 보류 유지(도구 상태)
                row["evidence_measured"] = False
                row["unconfirmed"] = False
                continue
            kind = "gate_dropped" if (_had_candidate(row) and sub not in asked_no_case) else "no_case"
            row.update({
                "score": UNCONFIRMED_SCORE, "measured": True, "evidence_measured": False, "level": None,
                "level_label": UNCONFIRMED_LABEL, "unconfirmed": True, "unconfirmed_kind": kind,
                "unconfirmed_text": UNCONFIRMED_TEXT_GATE_DROPPED if kind == "gate_dropped" else UNCONFIRMED_TEXT_NO_CASE,
            })
            n_unc += 1
            totals["gate_dropped_total" if kind == "gate_dropped" else "no_case_total"] += 1
        comp["sub_scores"] = {s: (r.get("score") if isinstance(r, dict) else None) for s, r in ledger.items()}
        comp["measured_count"] = sum(1 for r in ledger.values() if isinstance(r, dict) and r.get("measured"))   # (P7-2) 미확인·미탐색 포함 = 26 전부
        comp["evidence_measured_count"] = n_ev
        comp["unconfirmed_count"] = n_unc
        comp["not_explored_count"] = n_ne
        comp["probe_deficit_count"] = 0
        comp["is_reference"] = competency_is_reference(n_ev, len(ledger))
        _behavior = competency_behavior_score(list(comp["sub_scores"].values()))
        _sb = comp.get("score_breakdown") or {}
        _final = competency_final_score(_behavior, star_bonus=_sb.get("star_depth_bonus", 0.0),
                                        confidence_adj=_sb.get("confidence_adj", 0.0))
        comp["behavior_score"] = _behavior
        comp["score"] = _final
        from diag_project.services.scoring import confidence_display as _cdisp
        comp["score_breakdown"] = {**_sb, "rubric_base": _behavior, "final": _final, **_cdisp(_sb.get("confidence_adj", 0.0))}
        comp["level_label"] = competency_level_label(_behavior)
        totals["unconfirmed_total"] += n_unc
        totals["evidence_measured_total"] += n_ev
        totals["not_explored_total"] += n_ne
    totals["unconfirmed_banner"] = totals["unconfirmed_total"] >= UNCONFIRMED_BANNER_MIN   # (P7-2) 미탐색 1.0 도 미확인 수에 포함
    totals["not_explored_warn"] = totals["not_explored_total"] >= NOT_EXPLORED_WARN_MIN
    return totals


def rescore_without_confidence(details: dict) -> dict:
    """(2026-11-05 P4-7) 저장된 리포트의 대역량 점수를 확신도 가점 없이 다시 계산한다(제자리 수정, 표시 전용).

    저장 원장: details[ch].score_breakdown = {rubric_base, star_depth_bonus, confidence_adj, final}. rubric_base 가 없으면 behavior_score.
    반환 {"changed": bool, "total_score": 평균(측정 대역량), "radar": {ch: score}}. 확신도 표시(★) 필드도 채운다.
    """
    from diag_project.services.scoring import competency_final_score, confidence_display, overall_score
    changed = False
    radar: dict = {}
    for ch, comp in (details or {}).items():
        if not isinstance(comp, dict):
            continue
        sb = comp.get("score_breakdown") or {}
        base = sb.get("rubric_base", comp.get("behavior_score"))
        if base is None:
            radar[ch] = comp.get("score")
            continue
        new_final = competency_final_score(float(base), star_bonus=sb.get("star_depth_bonus", 0.0))
        disp = confidence_display(sb.get("confidence_adj", 0.0))
        if comp.get("score") != new_final or "confidence_stars" not in sb:
            changed = True
        comp["score"] = new_final
        comp["score_breakdown"] = {**sb, "rubric_base": base, "final": new_final, **disp}
        radar[ch] = new_final
    return {"changed": changed, "total_score": overall_score(list(radar.values())), "radar": radar}


def confidence_free_view(details, total_score, radar, *, is_human_edited: bool = False):
    """(2026-11-11) 저장된 리포트를 확신도 가점 없이 보여 줄 값 묶음 — 관리자 리포트 상세가 고객 화면과 같은 값을 내도록 쓴다.

    반환 (details, total_score, radar). 원본은 건드리지 않는다(깊은 복사 뒤 다시 계산, DB 는 그대로).
    관리자 교정본·details 없음은 저장값 그대로. 점수 정책은 바꾸지 않는다 — 26칸 전부 점수, 평균에서 빼는 칸 없음.
    """
    if is_human_edited or not isinstance(details, dict) or not details:
        return details, total_score, radar
    import copy
    view = copy.deepcopy(details)
    rs = rescore_without_confidence(view)
    if not rs["changed"]:
        return view, total_score, radar
    return view, (rs["total_score"] if rs["total_score"] is not None else total_score), rs["radar"]

