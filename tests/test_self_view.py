"""자가진단 비교(02 섹션)·그룹 평균 — 규칙 기반, 점수 계산과 무관 (2026-09-30)."""
import inspect

from diag_project.services.self_view import (
    MSG_HIGH, MSG_LOW, MSG_MATCH, MSG_SKIPPED, MSG_UNMEASURED, build_self_view, group_average,
)

ORDER = ["organization_management", "performance_management", "people_management", "work_management", "self_management"]
NAMES = dict(zip(ORDER, ["조직관리", "성과관리", "사람관리", "일관리", "자기관리"]))


def _details(**scores):
    return {k: {"score": v, "measured_count": (0 if v is None else 2)} for k, v in scores.items()}


def test_rows_interpretation_and_summary():
    d = _details(organization_management=3.0, performance_management=4.0, people_management=3.5, work_management=None, self_management=1.0)
    sv = build_self_view({k: 3.0 for k in ORDER} | {"self_management": 4.0, "performance_management": 2.5}, d, NAMES, ORDER)
    by = {r["key"]: r for r in sv["rows"]}
    assert sv["submitted"] and len(sv["rows"]) == 5
    assert by["organization_management"]["interpretation"] == MSG_MATCH and by["organization_management"]["diff"] == 0.0
    assert by["self_management"]["diff"] == 3.0 and by["self_management"]["interpretation"] == MSG_HIGH
    assert by["performance_management"]["diff"] == -1.5 and by["performance_management"]["interpretation"] == MSG_LOW
    assert by["work_management"]["measured"] is None and by["work_management"]["interpretation"] == MSG_UNMEASURED
    assert "자기관리를 스스로는 4.0점으로 보셨지만 대화에서는 1.0점이 확인되었습니다" in sv["summary"]
    assert "성과관리를 스스로는 2.5점" in sv["summary"]


def test_skipped_self_assessment():
    sv = build_self_view(None, _details(organization_management=3.0), NAMES, ORDER)
    assert sv["submitted"] is False and sv["message"] == MSG_SKIPPED and sv["rows"] == []


def test_group_average_needs_three_and_excludes_unmeasured():
    a = _details(organization_management=4.0, work_management=None)
    b = _details(organization_management=2.0, work_management=3.0)
    g2 = group_average([a, b], ORDER)
    assert g2["available"] is False and g2["averages"] is None and "현재 2명" in g2["label"]
    g3 = group_average([a, b, _details(organization_management=3.0, work_management=None)], ORDER)
    assert g3["available"] and g3["averages"]["organization_management"] == 3.0
    assert g3["averages"]["work_management"] == 3.0          # 측정된 1건만 분모
    assert g3["averages"]["self_management"] is None and "3명" in g3["label"]


def test_self_scores_never_enter_analysis_pipeline():
    """무결성: 분석·게이트·추천·점수 코드가 자가 점수(self_assessment_data['scores'])를 읽지 않는다."""
    import diag_project.llm_service as L
    import diag_project.services.course_recommender as C
    import diag_project.services.level_gate as G
    import diag_project.services.scoring as S
    import diag_project.services.outer_merge as O
    for mod in (L, C, G, S, O):
        src = inspect.getsource(mod)
        assert 'get("scores")' not in src.replace("saved_scores", "") or "self_assessment" not in src, mod.__name__
        assert "self_average" not in src and "self_view" not in src, mod.__name__
    from diag_project.routes import reports as R
    rsrc = inspect.getsource(R.load_analysis_inputs)
    assert '"scores"' not in rsrc and "self_average" not in rsrc   # 분석 입력에 자가 점수 없음


def test_self_view_does_not_mutate_details():
    import copy
    d = _details(organization_management=3.0, self_management=None)
    before = copy.deepcopy(d)
    build_self_view({"organization_management": 5, "self_management": 1}, d, NAMES, ORDER)
    build_self_view({"organization_management": 1, "self_management": 5}, d, NAMES, ORDER)
    assert d == before
