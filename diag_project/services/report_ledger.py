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
        return not any(r.get("measured") for r in ledger.values())
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
