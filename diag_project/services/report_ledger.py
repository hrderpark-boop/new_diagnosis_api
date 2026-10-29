"""리포트 원장 후처리(결정론) — 분석(LLM) 뒤, 종합 요약 앞에서 적용.

F. 측정 0 대역량의 평가 문장 금지
   측정된 하위역량이 하나도 없는 대역량에 LLM 이 쓴 코멘트·강점·개선·Gap 은 근거
   없는 평가다(예: 일관리 0/5 인데 "명확한 실행 원칙을 보유"). 코멘트를 정확히
   UNMEASURED_COMMENT 로 바꾸고 나머지 평가 서술은 비운다. 종합 요약 프롬프트도
   이 값을 보게 되어 미측정 대역량을 칭찬하지 않는다.

G. '미탐색'과 '근거 미확보' 구분
   원장에 asked 로 기록됐지만(대화 제어가 타깃으로 잡음) 그 하위역량의 앵커 질문이
   실제로 코치 메시지로 전달된 적이 없고 근거 후보도 0 이면, 대상자가 답을 못 한
   '근거 미확보'가 아니라 묻지 않은 '미탐색'(status=not_explored)이다.
   전달 판정: 그 챕터 코치 메시지(COMPETENCY_ALIGN 포함) 중 하나라도 앵커 질문과
   내용 어절 2개 이상 겹침(output_guard.anchor_overlap).

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
                      history: Iterable[Dict[str, Any]]) -> Dict[str, List[str]]:
    """G: asked 이지만 앵커 미전달 + 근거 후보 0 → status=not_explored.

    대역량 asked_count 에서도 뺀다(탐색률 = 실제로 물은 것). 반환: {대역량: [sub]}.
    history 에 chapter 정보가 없으면 판정하지 않는다(과거 입력 호환).
    """
    history = list(history or [])
    if not any(m.get("chapter") for m in history):
        return {}
    changed: Dict[str, List[str]] = {}
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
            row["status"] = "not_explored"
            changed.setdefault(ck, []).append(sub)
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


# ── (2026-10-29 P2-3) 근거 미확보 → 1.0 정책 ─────────────────────────────────────────────────
UNCONFIRMED_TEXT_GENERALIZED = "평소 방식은 말씀하셨으나 특정 장면이 확인되지 않아 최저 수준으로 기록했습니다"
UNCONFIRMED_TEXT_NO_ANSWER = "이 항목은 대화에서 사례가 확인되지 않아 최저 수준으로 기록했습니다"
UNCONFIRMED_BANNER_MIN = 6


def apply_unconfirmed_policy(competency_results: Dict[str, Dict[str, Any]],
                             store_meta: Dict[str, Any] | None) -> Dict[str, Any]:
    """측정되지 않은 하위역량 칸을 1.0('사례 미확인')으로 채운다 — 빈칸 없음. 게이트 검증 미완료(pending)는 도구 상태라 건드리지 않는다.

    행에 남기는 것: score 1.0 · measured True(정책상 측정에 포함) · evidence_measured False · unconfirmed True ·
    unconfirmed_kind generalized|no_answer · unconfirmed_text(라벨 뒤 서술, generalized 면 그 답변 한 줄 인용) ·
    probe_count(이 하위역량에 나간 코치 턴 수, 앵커 포함) · generalize_probed · probe_deficit(일반화 탐침 1회 + 구체화 요청 1회가
    모두 나가지 않았는데 미확인이 된 칸 — 린트 '탐침 2회 미만 미확인'). 측정된 행에는 level_label 만 붙인다.
    대역량: sub_scores·behavior_score·score 재계산(1.0 포함), measured_count(미확인 포함)·evidence_measured_count·
    unconfirmed_count·level_label. 반환: 합계.
    """
    from diag_project.services.scoring import (
        UNCONFIRMED_LABEL, UNCONFIRMED_SCORE, competency_behavior_score, competency_final_score,
        competency_is_reference, competency_level_label, level_label,
    )
    meta = store_meta or {}
    gen_map = meta.get("generalized") or {}
    gen_text = meta.get("generalized_text") or {}
    gen_probed = meta.get("generalize_probed") or {}
    probes = meta.get("probes_on_sub") or {}
    totals = {"unconfirmed_total": 0, "probe_deficit_unconfirmed": 0, "evidence_measured_total": 0, "pending_total": 0}
    for ck, comp in (competency_results or {}).items():
        if not isinstance(comp, dict) or comp.get("_error_fallback"):
            continue
        ledger = comp.get("sub_ledger") or {}
        n_unc = n_ev = n_def = 0
        for sub, row in ledger.items():
            if not isinstance(row, dict):
                continue
            p_cnt = int(((probes.get(ck) or {}).get(sub)) or 0)
            g_probed = sub in (gen_probed.get(ck) or [])
            row["probe_count"] = p_cnt
            row["generalize_probed"] = g_probed
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
            kind = "generalized" if sub in (gen_map.get(ck) or []) else "no_answer"
            quote = ((gen_text.get(ck) or {}).get(sub) or "").strip()
            text = UNCONFIRMED_TEXT_GENERALIZED if kind == "generalized" else UNCONFIRMED_TEXT_NO_ANSWER
            if kind == "generalized" and quote:
                text = f"{text} — \"{quote[:120]}\""
            row.update({
                "score": UNCONFIRMED_SCORE, "measured": True, "evidence_measured": False, "level": None,
                "level_label": UNCONFIRMED_LABEL, "unconfirmed": True, "unconfirmed_kind": kind,
                "unconfirmed_text": text,
                # 미확인 자격: 일반화 탐침 1회 + 구체화 요청(그 외 탐침) 1회가 모두 나갔을 때만. 아니면 탐침 부족(린트 0 목표)
                "probe_deficit": not (g_probed and p_cnt >= 3),
            })
            n_unc += 1
            n_def += int(row["probe_deficit"])
        comp["sub_scores"] = {s: (r.get("score") if isinstance(r, dict) else None) for s, r in ledger.items()}
        comp["measured_count"] = sum(1 for r in ledger.values() if isinstance(r, dict) and r.get("measured"))
        comp["evidence_measured_count"] = n_ev
        comp["unconfirmed_count"] = n_unc
        comp["probe_deficit_count"] = n_def
        comp["is_reference"] = competency_is_reference(n_ev, len(ledger))
        _behavior = competency_behavior_score(list(comp["sub_scores"].values()))
        _sb = comp.get("score_breakdown") or {}
        _final = competency_final_score(_behavior, star_bonus=_sb.get("star_depth_bonus", 0.0),
                                        confidence_adj=_sb.get("confidence_adj", 0.0))
        comp["behavior_score"] = _behavior
        comp["score"] = _final
        comp["score_breakdown"] = {**_sb, "rubric_base": _behavior, "final": _final}
        comp["level_label"] = competency_level_label(_behavior)
        totals["unconfirmed_total"] += n_unc
        totals["probe_deficit_unconfirmed"] += n_def
        totals["evidence_measured_total"] += n_ev
    totals["unconfirmed_banner"] = totals["unconfirmed_total"] >= UNCONFIRMED_BANNER_MIN
    return totals
