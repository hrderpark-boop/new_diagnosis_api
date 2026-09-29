"""B/F/G: 리포트 원장 후처리·종합 점수 표기 모드 단위 테스트. 실행: pytest.

  B. 종합 점수는 항상 표시 — composite_mode 는 정식/참고치 구분만(임계 18).
  F. 측정 0 대역량 → 코멘트는 정확히 "이번 세션에서 확인되지 않았습니다.",
     강점·개선·Gap·S/A/R 해설은 비운다(멱등). 검증 미완료(pending)는 제외.
  G. asked 이지만 앵커 미전달 + 근거 후보 0 → not_explored(미탐색),
     앵커가 전달됐거나 후보가 있었으면 근거 미확보 유지.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.data.competencies import (  # noqa: E402
    find_sub_key_by_name, get_anchor_questions,
)
from diag_project.services.report_ledger import (  # noqa: E402
    UNMEASURED_COMMENT, mark_not_explored, neutralize_unmeasured,
)
from diag_project.services.scoring import (  # noqa: E402
    composite_mode, composite_shown,
)

CH = "organization_management"
SUB = "혁신적 사고"


def _row(asked=True, measured=False, status="evidence_missing",
         gate_status="n_a", candidate_runs=0):
    return {"asked": asked, "measured": measured, "status": status,
            "gate_status": gate_status, "candidate_runs": candidate_runs,
            "level": 2 if measured else None, "evidence": ["q"] if measured else []}


def _comp(rows, **extra):
    base = {"sub_ledger": rows, "comment": "명확한 실행 원칙을 보유한 리더입니다.",
            "strength_point": "핵심 인재에게 역할을 집중시키는 명확한 실행 원칙",
            "growth_point": "표준화 필요", "gap_analysis": "다음 단계로…",
            "situational_pattern": "위기 상황에서 발현",
            "reasoning_process": {"1_situation": {"description": "상황 해설",
                                                  "evidence": ["원문"]}},
            "measured_count": sum(1 for r in rows.values() if r.get("measured")),
            "asked_count": sum(1 for r in rows.values() if r.get("asked"))}
    base.update(extra)
    return base


# ── B ────────────────────────────────────────────────────────────────
def test_composite_mode_official_vs_reference():
    assert composite_mode(17) == "reference"
    assert composite_mode(18) == "official"
    assert composite_mode(0) == "reference"
    assert composite_mode(None) == "reference"
    assert composite_shown(18) is True and composite_shown(17) is False


# ── F ────────────────────────────────────────────────────────────────
def test_unmeasured_chapter_is_neutralized_exactly():
    res = {"work_management": _comp({"업무계획 및 조직력": _row(),
                                      "자원 및 시간관리": _row()})}
    assert neutralize_unmeasured(res) == ["work_management"]
    c = res["work_management"]
    assert c["comment"] == UNMEASURED_COMMENT == "이번 세션에서 확인되지 않았습니다."
    for f in ("strength_point", "growth_point", "gap_analysis", "situational_pattern"):
        assert c[f] == ""
    assert c["reasoning_process"]["1_situation"]["description"] == ""
    assert c["reasoning_process"]["1_situation"]["evidence"] == ["원문"]  # 원문 보존
    assert c["unmeasured"] is True
    # 멱등
    assert neutralize_unmeasured(res) == ["work_management"]
    assert res["work_management"]["comment"] == UNMEASURED_COMMENT


def test_measured_or_pending_chapter_untouched():
    measured = _comp({"자기인식": _row(measured=True, status="measured",
                                     gate_status="passed", candidate_runs=3),
                      "중심성": _row()})
    pending = _comp({"자기인식": _row(status="measured", gate_status="pending",
                                    candidate_runs=1)})
    res = {"self_management": measured, "people_management": pending}
    assert neutralize_unmeasured(res) == []
    assert res["self_management"]["comment"].startswith("명확한")
    assert res["people_management"]["strength_point"]


def test_error_fallback_not_neutralized():
    res = {"work_management": _comp({"a": _row()}, _error_fallback=True)}
    assert neutralize_unmeasured(res) == []


# ── G ────────────────────────────────────────────────────────────────
def _anchor():
    return get_anchor_questions(find_sub_key_by_name(CH, SUB))[0]


def _hist(coach_texts, chapter=CH):
    h = [{"role": "user", "parts": "안녕하세요", "chapter": None}]
    for t in coach_texts:
        h.append({"role": "model", "parts": t, "chapter": chapter})
        h.append({"role": "user", "parts": "네", "chapter": chapter})
    return h


def test_anchor_not_delivered_becomes_not_explored():
    res = {CH: _comp({SUB: _row(), "전략적 사고": _row(asked=False,
                                                     status="unexplored")})}
    changed = mark_not_explored(res, _hist(["조직관리를 어떻게 생각하세요?"]))
    assert changed == {CH: [SUB]}
    row = res[CH]["sub_ledger"][SUB]
    assert row["status"] == "not_explored" and row["anchor_delivered"] is False
    assert res[CH]["asked_count"] == 0            # 탐색률에서 제외
    assert res[CH]["not_explored_count"] == 1


def test_anchor_delivered_keeps_evidence_missing():
    res = {CH: _comp({SUB: _row()})}
    assert mark_not_explored(res, _hist([_anchor()])) == {}
    assert res[CH]["sub_ledger"][SUB]["status"] == "evidence_missing"
    assert res[CH]["sub_ledger"][SUB]["anchor_delivered"] is True


def test_align_message_counts_as_delivery():
    h = _hist(["다른 질문입니다?"])
    h.insert(1, {"role": "model", "parts": "정의 설명입니다. " + _anchor(),
                 "chapter": None, "instruction": "COMPETENCY_ALIGN"})
    res = {CH: _comp({SUB: _row()})}
    assert mark_not_explored(res, h) == {}


def test_candidate_existed_stays_evidence_missing():
    # 근거 후보가 있었는데 게이트에서 탈락 → 대상자 응답 문제(근거 미확보)
    res = {CH: _comp({SUB: _row(gate_status="failed", candidate_runs=2)})}
    assert mark_not_explored(res, _hist(["조직관리를 어떻게 생각하세요?"])) == {}
    assert res[CH]["sub_ledger"][SUB]["status"] == "evidence_missing"


def test_anchor_in_other_chapter_does_not_count():
    res = {CH: _comp({SUB: _row()})}
    changed = mark_not_explored(res, _hist([_anchor()], chapter="work_management"))
    assert changed == {CH: [SUB]}


def test_history_without_chapter_is_noop():
    res = {CH: _comp({SUB: _row()})}
    legacy = [{"role": "model", "parts": "질문?"}]
    assert mark_not_explored(res, legacy) == {}
    assert res[CH]["sub_ledger"][SUB]["status"] == "evidence_missing"
