"""(2026-10-22 P0) 리포트 종합 실패 — Claude 구조화 출력 grammar 초과(사람관리 9개) 수정 + 실패 3회 확정·운영자 알림 (LLM·DB 없음).

Render 로그: people_management 분석 400 "The compiled grammar is too large" → 분석 오염 → 리포트 미저장 503 → 프론트가
재시도 → 같은 400 반복(캐시된 챕터는 0콜). 로컬 재현: 9개 키 object 스키마 4,862B 거부, 배열 스키마 2,041B 통과.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project import llm_schemas as S  # noqa: E402
from diag_project.data.competencies import COMPETENCY_FRAMEWORK as F  # noqa: E402
from diag_project.llm_service import _normalize_sub_assessments  # noqa: E402
from diag_project.routes.reports import REPORT_FAIL_LIMIT, next_analysis_marker  # noqa: E402
from diag_project.services import ops_monitor as M  # noqa: E402


def _names(ch):
    return [v["name"] for v in F[ch]["indicators"].values()]


def test_deep_schema_is_array_and_small_for_every_chapter():
    for ch in F:
        if ch == "supplementary":
            continue
        sch = S.deep_analysis_schema(_names(ch))
        S.assert_claude_compatible(sch)
        sa = sch["properties"]["sub_assessments"]
        assert sa["type"] == "array" and set(sa["items"]["properties"]) == {"name", "measured", "level", "evidence", "consistency_flag"}
        assert len(json.dumps(sch, ensure_ascii=False)) < 2500, ch     # 사람관리 9개도 배열이라 크기 일정


def test_normalize_list_and_dict_forms():
    subs = ["갈등관리", "신뢰형성", "변화관리(변화지향)"]
    lst = [{"name": "갈등관리", "measured": True, "level": 3, "evidence": ["a"], "consistency_flag": True},
           {"name": "변화관리", "measured": False, "level": None, "evidence": [], "consistency_flag": False},   # 줄여 쓴 이름
           {"name": "없는역량", "measured": True, "level": 2, "evidence": [], "consistency_flag": True}]
    out = _normalize_sub_assessments(lst, subs)
    assert set(out) == {"갈등관리", "변화관리(변화지향)"} and out["갈등관리"]["level"] == 3 and "name" not in out["갈등관리"]
    d = {"신뢰형성": {"measured": True, "level": 2, "evidence": ["b"], "consistency_flag": True}}
    assert _normalize_sub_assessments(d, subs)["신뢰형성"]["evidence"] == ["b"]      # Gemini dict 형태 그대로
    assert _normalize_sub_assessments(None, subs) == {} and _normalize_sub_assessments("x", subs) == {}


def test_failure_marker_escalates_to_failed_on_third():
    m1 = next_analysis_marker(None, ["people_management"])
    assert m1["status"] == "degraded" and m1["fail_count"] == 1 and "error_id" not in m1 and m1["stage"] == "people_management"
    m2 = next_analysis_marker(m1, ["people_management"])
    assert m2["status"] == "degraded" and m2["fail_count"] == 2
    m3 = next_analysis_marker(m2, ["people_management"])
    assert m3["status"] == "failed" and m3["fail_count"] == REPORT_FAIL_LIMIT and len(m3["error_id"]) == 12
    m4 = next_analysis_marker(m3, ["people_management"])
    assert m4["status"] == "failed" and m4["error_id"] == m3["error_id"]      # 같은 error_id 유지


def test_report_failure_alert_registry():
    M.REPORT_FAILURES.clear()
    rec = M.record_report_failure("cbd5210b-9ebe-4081-ad2a-ab2611449344", "people_management", "abc123def456", 3)
    snap = M.alerts_snapshot()
    assert snap["report_failed_alert"] is True and snap["report_failed"][0]["error_id"] == rec["error_id"]
    M.clear_report_failure("cbd5210b-9ebe-4081-ad2a-ab2611449344")
    assert M.alerts_snapshot()["report_failed_alert"] is False


def test_route_source_contract():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "diag_project", "routes", "reports.py"),
               encoding="utf-8").read()
    assert '"analysis_status": "failed"' in src and "record_report_failure(" in src and "clear_report_failure(" in src
    assert "리포트 생성에 문제가 있어 운영자에게 알렸습니다" in src
