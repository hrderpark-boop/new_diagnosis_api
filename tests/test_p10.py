"""P10 — 관리자 리포트 상세의 확신도 가점 제거(고객 화면과 같은 값).

- 관리자 상세 GET 은 저장 리포트를 확신도 가점 없이 다시 계산해 보여 준다(표시 전용, 원본·DB 불변).
- 관리자 교정본은 저장값 그대로.
- 점수 정책은 그대로다 — 리포트에 미탐색 없음, 26칸 전부 점수(평균에서 빼는 칸 없음).
"""
import asyncio
import copy
import uuid
from types import SimpleNamespace as NS

from diag_project.routes import admin as A
from diag_project.services import report_ledger as RL


def _saved_details():
    return {
        "performance_management": {
            "score": 2.5, "measured_count": 5,
            "sub_scores": {"goal_setting": 3.0, "feedback": 1.0},
            "score_breakdown": {"rubric_base": 2.0, "star_depth_bonus": 0.3, "confidence_adj": 0.2, "final": 2.5},
        },
        "work_management": {
            "score": 3.1, "measured_count": 5,
            "sub_scores": {"planning": 3.0},
            "score_breakdown": {"rubric_base": 2.6, "star_depth_bonus": 0.3, "confidence_adj": 0.2, "final": 3.1},
        },
    }


def test_confidence_free_view_matches_customer_rescore_and_keeps_original():
    saved = _saved_details()
    before = copy.deepcopy(saved)
    details, total, radar = RL.confidence_free_view(saved, 2.8, {"performance_management": 2.5, "work_management": 3.1})
    # 고객 화면이 쓰는 계산(rescore_without_confidence)과 같은 값
    ref = copy.deepcopy(before)
    rs = RL.rescore_without_confidence(ref)
    assert rs["changed"] and radar == rs["radar"] == {"performance_management": 2.3, "work_management": 2.9}
    assert total == rs["total_score"] == 2.6
    assert details["work_management"]["score"] == 2.9 and details["work_management"]["score_breakdown"]["final"] == 2.9
    # 원본(저장값)은 그대로
    assert saved == before


def test_confidence_free_view_leaves_human_edited_and_empty_as_saved():
    saved = _saved_details()
    radar = {"performance_management": 2.5, "work_management": 3.1}
    details, total, out_radar = RL.confidence_free_view(saved, 2.8, radar, is_human_edited=True)
    assert details is saved and total == 2.8 and out_radar is radar
    assert RL.confidence_free_view({}, 2.8, radar) == ({}, 2.8, radar)
    assert RL.confidence_free_view(None, None, {}) == (None, None, {})


def test_all_cells_keep_scores_no_exclusion_from_average():
    """정책 고정: 1.0 칸도 점수로 남고, 평균에서 빼는 읽기 보정은 없다."""
    details, _, _ = RL.confidence_free_view(_saved_details(), 2.8, {})
    assert details["performance_management"]["sub_scores"] == {"goal_setting": 3.0, "feedback": 1.0}
    assert not hasattr(RL, "exclude_unasked") and not hasattr(RL, "corrected_report_view")


class _FakeResult:
    def __init__(self, obj):
        self._obj = obj

    def scalars(self):
        return self

    def first(self):
        return self._obj


class _FakeDB:
    def __init__(self, report, by_id):
        self._report, self._by_id = report, by_id

    async def execute(self, _stmt):
        return _FakeResult(self._report)

    async def get(self, _model, key):
        return self._by_id.get(key)


def _report(is_human_edited):
    return NS(
        id=uuid.uuid4(), session_id=uuid.uuid4(), user_id=uuid.uuid4(), total_score=2.8, summary="요약",
        scores={"details": _saved_details(), "radar_chart": {"performance_management": 2.5, "work_management": 3.1}},
        created_at=None, is_human_edited=is_human_edited, edited_at=None, edited_by=None, ai_original=None,
    )


def _call_detail(report):
    participant = NS(name="리더", email=None, company_id=None)
    session = NS(self_assessment_data={"asked_subs": {"performance_management": ["goal_setting"]}})
    db = _FakeDB(report, {report.user_id: participant, report.session_id: session})
    ctx = NS(assert_can_access_company=lambda _cid: None)
    return asyncio.run(A.get_report_detail(report.id, ctx=ctx, db=db))


def test_admin_report_detail_shows_confidence_free_scores():
    report = _report(is_human_edited=False)
    out = _call_detail(report)
    assert out["total_score"] == 2.6
    assert out["radar_chart"] == {"performance_management": 2.3, "work_management": 2.9}
    assert out["details"]["performance_management"]["score"] == 2.3
    assert out["details"]["performance_management"]["sub_scores"]["feedback"] == 1.0   # 26칸 정책: 1.0 칸 그대로
    # 저장값(DB 객체)은 바뀌지 않는다
    assert report.total_score == 2.8 and report.scores["details"]["performance_management"]["score"] == 2.5


def test_admin_report_detail_keeps_human_edited_values():
    report = _report(is_human_edited=True)
    out = _call_detail(report)
    assert out["total_score"] == 2.8
    assert out["radar_chart"] == {"performance_management": 2.5, "work_management": 3.1}
    assert out["details"]["work_management"]["score"] == 3.1
