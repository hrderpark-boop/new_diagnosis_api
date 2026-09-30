"""'스스로 보는 나'(자가진단)와 '대화에 드러난 나'(측정) 비교 + 그룹 평균 — 표시·비교 전용 (2026-09-30).

무결성: 자가 점수는 여기서만 쓰인다. measured·레벨·total_score·추천 카드 계산에 절대 들어가지 않는다
(분석 파이프라인은 self_assessment_data["scores"] 를 읽지 않는다 — tests/test_self_view.py 가 고정).
해석 문구는 규칙 기반(LLM 없음).
"""
from __future__ import annotations

from typing import Any

DIFF_THRESHOLD = 1.0
GROUP_MIN_N = 3

MSG_HIGH = "스스로 높게 보는 영역 — 대화에서는 그만큼 드러나지 않았습니다"
MSG_LOW = "스스로 낮게 보는 영역 — 대화에서는 더 분명하게 드러났습니다"
MSG_MATCH = "인식과 드러남이 일치하는 영역"
MSG_UNMEASURED = "이번 세션에서 확인되지 않아 비교할 수 없습니다"
MSG_SKIPPED = "자가진단을 건너뛰어 비교할 수 없습니다"


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if 0 < f <= 5 else None


def chapter_measured_score(detail: dict | None) -> float | None:
    """대역량 측정 점수(1~5). 측정 0(measured_count==0)이면 None."""
    d = detail or {}
    if int(d.get("measured_count") or 0) <= 0:
        return None
    return _num(d.get("score"))


def _josa(word: str, a: str, b: str) -> str:
    ch = (word or "")[-1:]
    return a if (ch and "가" <= ch <= "힣" and (ord(ch) - 0xAC00) % 28) else b


def build_self_view(self_scores: dict | None, details: dict | None, names: dict[str, str], order: list[str]) -> dict:
    """02 섹션 데이터. self_scores 가 없으면 submitted=False + 안내 문구만."""
    scores = {k: _num(v) for k, v in (self_scores or {}).items()}
    scores = {k: v for k, v in scores.items() if v is not None}
    if not scores:
        return {"submitted": False, "message": MSG_SKIPPED, "rows": [], "summary": None, "self_average": None}
    rows = []
    for k in order:
        s = scores.get(k)
        m = chapter_measured_score((details or {}).get(k))
        if s is None:
            continue
        if m is None:
            rows.append({"key": k, "name": names.get(k, k), "self": round(s, 1), "measured": None, "diff": None,
                         "kind": "unmeasured", "interpretation": MSG_UNMEASURED})
            continue
        diff = round(s - m, 1)
        kind = "self_higher" if diff >= DIFF_THRESHOLD else "self_lower" if diff <= -DIFF_THRESHOLD else "match"
        rows.append({"key": k, "name": names.get(k, k), "self": round(s, 1), "measured": round(m, 1), "diff": diff,
                     "kind": kind,
                     "interpretation": MSG_HIGH if kind == "self_higher" else MSG_LOW if kind == "self_lower" else MSG_MATCH})
    comparable = [r for r in rows if r["diff"] is not None]
    top = sorted([r for r in comparable if abs(r["diff"]) >= DIFF_THRESHOLD], key=lambda r: -abs(r["diff"]))[:2]
    if top:
        parts = [f"{r['name']}{_josa(r['name'], '을', '를')} 스스로는 {r['self']:.1f}점으로 보셨지만 대화에서는 {r['measured']:.1f}점이 확인되었습니다"
                 for r in top]
        summary = ". ".join(parts) + "."
    elif comparable:
        summary = "비교할 수 있었던 영역에서는 스스로 보는 수준과 대화에 드러난 수준이 1점 이내로 가깝습니다."
    else:
        summary = "이번 세션에서 확인된 영역이 없어 자가진단과 비교할 수 없습니다."
    vals = [r["self"] for r in rows]
    return {"submitted": True, "message": None, "rows": rows, "summary": summary,
            "self_average": round(sum(vals) / len(vals), 1) if vals else None}


def group_average(reports_details: list[dict], order: list[str]) -> dict:
    """같은 그룹의 리포트 details 목록 → 대역량별 평균(측정된 것만, 미측정은 분모 제외). n<3 이면 averages=None."""
    n = len(reports_details)
    if n < GROUP_MIN_N:
        return {"available": False, "n": n, "min_n": GROUP_MIN_N, "averages": None,
                "label": f"비교 대상이 {GROUP_MIN_N}명 이상 모이면 그룹 평균과 비교해 드립니다 (현재 {n}명)"}
    avgs: dict[str, float | None] = {}
    for k in order:
        xs = [x for x in (chapter_measured_score((d or {}).get(k)) for d in reports_details) if x is not None]
        avgs[k] = round(sum(xs) / len(xs), 1) if xs else None
    return {"available": True, "n": n, "min_n": GROUP_MIN_N, "averages": avgs, "label": f"같은 그룹 {n}명 평균과 비교"}
