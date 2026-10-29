"""(2026-10-23 파일럿 전 2건) 완주 리더 재로그인 → 리포트 화면 / 관리자 재분석(super_admin) + 리포트 미생성 목록.

- GET /diagnoses/active: 재개 세션이 없으면 completed 요약(has_report·analysis_status)을 돌려준다.
- POST /admin/sessions/{id}/reanalyze: super_admin 만, completed 만, 마커 초기화(fail_count 0) 뒤 analyze 호출.
- GET /admin/reports: 리포트 행이 없는 완주 세션이 1페이지 상단에 report_missing=True 로 나온다.
- GET /admin/participants: last_analysis_status·report_missing 필드.
라우트 테스트는 conftest 의 임시 sqlite + TestClient 로 돈다(LLM 호출은 monkeypatch).
"""
import inspect
import os
import sys
import uuid
from datetime import datetime
from types import SimpleNamespace as NS

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.routes import admin as A  # noqa: E402
from diag_project.routes import diagnoses as D  # noqa: E402
from diag_project.routes import reports as R  # noqa: E402

ELLA = uuid.UUID("00000000-0000-0000-0000-000000000011")


# ── 순수 함수 ──────────────────────────────────────────────────────────────────

def test_completed_summary_and_status():
    s = NS(id=uuid.uuid4(), coach_id=ELLA, updated_at=datetime(2026, 10, 22, 16, 0), created_at=None,
           self_assessment_data={"last_analysis": {"status": "failed", "fail_count": 3, "error_id": "abc"}})
    out = D.completed_summary(s, has_report=False)
    assert out["has_report"] is False and out["analysis_status"] == "failed" and out["coach_name"].startswith("Ella")
    assert out["completed_at"].startswith("2026-10-22T16:00")
    s2 = NS(id=uuid.uuid4(), coach_id=uuid.uuid4(), updated_at=None, created_at=None, self_assessment_data=None)
    out2 = D.completed_summary(s2, has_report=True)
    assert out2["has_report"] is True and out2["analysis_status"] is None and out2["coach_name"].startswith("Ella")   # 모르는 코치 id 는 Ella 폴백


def test_reset_marker_zeroes_fail_count_and_keeps_prev():
    prev = {"status": "failed", "fail_count": 3, "error_id": "deadbeef0001"}
    m = R.reset_analysis_marker(prev, "ops@test")
    assert m["status"] == "reset" and m["fail_count"] == 0 and m["by"] == "ops@test"
    assert m["prev_status"] == "failed" and m["prev_fail_count"] == 3 and m["prev_error_id"] == "deadbeef0001"
    # 초기화 뒤 다음 실패는 1회차부터 다시 센다(3회 상한이 다시 적용)
    nxt = R.next_analysis_marker(m, ["people_management"])
    assert nxt["status"] == "degraded" and nxt["fail_count"] == 1
    assert R.reset_analysis_marker(None, "x")["prev_fail_count"] == 0


def test_missing_report_item_shape():
    s = NS(id=uuid.uuid4(), user_id=uuid.uuid4(), updated_at=datetime(2026, 10, 22), created_at=None,
           self_assessment_data={"last_analysis": {"status": "degraded", "fail_count": 2}})
    p = NS(name="박기진", email="k@x.io", company_id=None, group_code="G-TEST")
    it = A.missing_report_item(s, p, {})
    assert it["id"] is None and it["report_missing"] is True and it["analysis_status"] == "degraded"
    assert it["fail_count"] == 2 and it["total_score"] is None and it["company_name"] == "미지정"
    assert A.missing_report_item(NS(id=1, user_id=1, updated_at=None, created_at=None, self_assessment_data=None),
                                 p, {})["analysis_status"] == "analyzing"


def test_reanalyze_route_is_super_admin_only_and_completed_only():
    assert "/admin/sessions/{session_id}/reanalyze" in {getattr(r, "path", "") for r in A.router.routes}
    src = inspect.getsource(A.admin_reanalyze_session)
    assert "Depends(require_super_admin)" in src and 'if s.status != "completed"' in src
    assert "reset_analysis_marker" in src and "clear_report_failure" in src and "analyze_session(" in src


# ── 라우트(임시 sqlite) ────────────────────────────────────────────────────────

def _make_rows(client, *, status="completed", marker=None, with_report=False):
    from diag_project.database import async_session
    from diag_project.models.diagnosis_report import DiagnosisReport
    from diag_project.models.diagnosis_session import DiagnosisSession
    from diag_project.models.participant import Participant

    async def _mk():
        async with async_session() as db:
            p = Participant(email=f"pilot-{uuid.uuid4().hex[:8]}@test.local", name="파일럿 리더", group_code="G-TEST")
            db.add(p)
            await db.flush()
            s = DiagnosisSession(user_id=p.id, coach_id=ELLA, status=status, current_topic="General",
                                 self_assessment_data={"last_analysis": marker} if marker else None)
            db.add(s)
            await db.flush()
            if with_report:
                db.add(DiagnosisReport(session_id=s.id, user_id=p.id, coach_id=ELLA, summary="s", scores={},
                                       total_score=3.0, top_competency="-", bottom_competency="-",
                                       feedback="-", recommended_action="-"))
            await db.commit()
            return str(p.id), str(s.id)
    return client.portal.call(_mk)


def _ph(pid):
    """(2026-10-29) 참여자 API 는 본인 토큰 필수."""
    from diag_project.services.participant_auth import create_participant_token
    return {"Authorization": f"Bearer {create_participant_token(pid)}"}


def test_active_returns_completed_summary_when_no_resumable(client):
    pid, sid = _make_rows(client, marker={"status": "failed", "fail_count": 3, "error_id": "e1"})
    r = client.get("/api/v1/diagnoses/active", params={"participant_id": pid}, headers=_ph(pid))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["has_active"] is False
    assert body["completed"]["session_id"] == sid and body["completed"]["has_report"] is False
    assert body["completed"]["analysis_status"] == "failed"
    # 리포트가 있으면 has_report=True
    pid2, sid2 = _make_rows(client, with_report=True)
    c2 = client.get("/api/v1/diagnoses/active", params={"participant_id": pid2}, headers=_ph(pid2)).json()["completed"]
    assert c2["session_id"] == sid2 and c2["has_report"] is True and c2["analysis_status"] is None
    # 완주 세션이 없으면 None
    pid3, _ = _make_rows(client, status="in_progress")
    b3 = client.get("/api/v1/diagnoses/active", params={"participant_id": pid3}, headers=_ph(pid3)).json()
    assert b3["has_active"] is True and "completed" not in b3


def test_admin_reanalyze_resets_marker_then_calls_analyze(client, auth_headers, monkeypatch):
    from diag_project.services import ops_monitor as M
    pid, sid = _make_rows(client, marker={"status": "failed", "fail_count": 3, "error_id": "e9"})
    M.record_report_failure(sid, "people_management", "e9", 3)
    seen = {}

    async def _fake_analyze(session_id, db, llm):
        seen["sid"] = session_id
        s = await db.get(D.DiagnosisSession, uuid.UUID(session_id))
        seen["marker_at_call"] = dict(s.self_assessment_data["last_analysis"])
        return {"status": "success", "report_id": "fake"}
    monkeypatch.setattr(R, "analyze_session", _fake_analyze)

    r = client.post(f"/api/v1/admin/sessions/{sid}/reanalyze", headers=auth_headers)
    assert r.status_code == 200, r.text
    body = r.json()
    assert seen["sid"] == sid and seen["marker_at_call"]["status"] == "reset" and seen["marker_at_call"]["fail_count"] == 0
    assert body["reset"]["prev_fail_count"] == 3 and body["reset"]["prev_error_id"] == "e9"
    assert body["analysis"]["status"] == "success"
    assert all(x["session_id"] != sid for x in M.REPORT_FAILURES)          # 알림 목록에서도 제거
    # 완주가 아닌 세션은 409, 없는 세션은 404, 인증 없음은 401
    _, sid_ip = _make_rows(client, status="in_progress")
    assert client.post(f"/api/v1/admin/sessions/{sid_ip}/reanalyze", headers=auth_headers).status_code == 409
    assert client.post(f"/api/v1/admin/sessions/{uuid.uuid4()}/reanalyze", headers=auth_headers).status_code == 404
    assert client.post(f"/api/v1/admin/sessions/{sid}/reanalyze").status_code == 401


def test_admin_reanalyze_forbidden_for_client_admin(client):
    from diag_project.database import async_session
    from diag_project.models.admin_user import AdminUser, UserRole
    from diag_project.services.auth import create_access_token, hash_password

    async def _mk():
        async with async_session() as db:
            a = AdminUser(email=f"client-{uuid.uuid4().hex[:6]}@test.local", name="client", role=UserRole.CLIENT_ADMIN.value,
                          password_hash=hash_password("pw-1"))
            db.add(a)
            await db.commit()
            await db.refresh(a)
            return a
    a = client.portal.call(_mk)
    _, sid = _make_rows(client)
    r = client.post(f"/api/v1/admin/sessions/{sid}/reanalyze", headers={"Authorization": f"Bearer {create_access_token(a)}"})
    assert r.status_code == 403


def test_admin_reports_lists_completed_without_report_and_participants_flags(client, auth_headers):
    pid, sid = _make_rows(client, marker={"status": "degraded", "fail_count": 2})
    r = client.get("/api/v1/admin/reports", headers=auth_headers, params={"search": "파일럿 리더", "page_size": 200})
    assert r.status_code == 200, r.text
    body = r.json()
    rows = [x for x in body["items"] if x["session_id"] == sid]
    assert len(rows) == 1 and rows[0]["report_missing"] is True and rows[0]["id"] is None
    assert rows[0]["analysis_status"] == "degraded" and rows[0]["fail_count"] == 2
    assert body["items"].index(rows[0]) < len([x for x in body["items"] if x.get("report_missing")])   # 미생성 행이 상단
    assert body["total"] >= len(rows)
    # 2페이지에는 미생성 행을 반복하지 않는다
    r2 = client.get("/api/v1/admin/reports", headers=auth_headers, params={"search": "파일럿 리더", "page": 2, "page_size": 1})
    assert all(not x.get("report_missing") for x in r2.json()["items"])
    # 참가자 목록 플래그
    pr = client.get("/api/v1/admin/participants", headers=auth_headers, params={"search": "파일럿 리더", "page_size": 200}).json()
    me = [x for x in pr["items"] if x["id"] == pid][0]
    assert me["report_missing"] is True and me["last_analysis_status"] == "degraded" and me["last_analysis_fail_count"] == 2
