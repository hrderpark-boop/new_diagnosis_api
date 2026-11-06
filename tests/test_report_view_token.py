"""(2026-11-06 P5) '고객 화면 보기' 열람 토큰 — 1회용 서명 토큰(60초, session_id 한정, jti 소진) + 세션 전용 열람 토큰(30분).

  - 마스터는 어느 세션이든 발급, HR 은 자사 참여자만(타사 session_id 403)
  - 1회용 토큰은 교환 경로(POST /reports/{sid}/view-session)에서만, 두 번째 교환은 401, 만료는 401, 다른 세션은 403
  - 열람 토큰은 그 세션의 GET 만 — 재분석(POST)·대화(POST)는 403, 다른 세션 GET 은 403
"""
import time
import uuid

from jose import jwt

ELLA = uuid.UUID("00000000-0000-0000-0000-000000000011")


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _make_session(client, company_id=None):
    from diag_project.database import async_session
    from diag_project.models.diagnosis_session import DiagnosisSession
    from diag_project.models.participant import Participant

    async def _mk():
        async with async_session() as db:
            p = Participant(email=f"vt-{uuid.uuid4().hex[:8]}@test.local", name="열람", company_id=company_id)
            db.add(p); await db.flush()
            s = DiagnosisSession(user_id=p.id, coach_id=ELLA, status="completed")
            db.add(s); await db.commit()
            return str(p.id), str(s.id)
    return client.portal.call(_mk)


def _make_company_admin(client):
    from diag_project.database import async_session
    from diag_project.models.admin_user import AdminUser, UserRole
    from diag_project.models.company import Company
    from diag_project.services.auth import create_access_token, hash_password

    async def _mk():
        async with async_session() as db:
            tag = uuid.uuid4().hex[:6]
            c = Company(name=f"열람사-{tag}", code=f"VT-{tag}")
            db.add(c); await db.flush()
            a = AdminUser(email=f"hr-vt-{tag}@test.local", name="hr", role=UserRole.CLIENT_ADMIN.value,
                          password_hash=hash_password("pw-1"), company_id=c.id)
            db.add(a); await db.commit(); await db.refresh(a)
            return c.id, create_access_token(a)
    return client.portal.call(_mk)


def _issue(client, headers, sid):
    return client.post(f"/api/v1/admin/sessions/{sid}/view-token", headers=headers)


def _exchange(client, sid, vt):
    return client.post(f"/api/v1/reports/{sid}/view-session", headers=_bearer(vt))


def test_master_issues_exchanges_and_views_once(client, auth_headers):
    from diag_project.services.report_view_token import reset_used_jti
    reset_used_jti()
    pid, sid = _make_session(client)
    r = _issue(client, auth_headers, sid)
    assert r.status_code == 200 and r.json()["expires_in"] == 60 and r.json()["session_id"] == sid
    vt = r.json()["view_token"]
    assert jwt.get_unverified_claims(vt)["typ"] == "report_view" and jwt.get_unverified_claims(vt)["sid"] == sid
    # 1회용 토큰으로 리포트를 직접 열 수는 없다(교환 전용)
    assert client.get(f"/api/v1/reports/{sid}", headers=_bearer(vt)).status_code == 403
    ex = _exchange(client, sid, vt)
    assert ex.status_code == 200 and ex.json()["expires_in"] == 1800
    viewer = ex.json()["viewer_token"]
    # 두 번째 교환은 jti 소진 → 401
    assert _exchange(client, sid, vt).status_code == 401
    # 열람 토큰: 그 세션의 GET 은 인증 통과(리포트가 없어 404 'Report not ready' — 401/403 이 아니다)
    g = client.get(f"/api/v1/reports/{sid}", headers=_bearer(viewer))
    assert g.status_code == 404 and g.json()["detail"]["message"] == "Report not ready"
    assert client.get(f"/api/v1/reports/{sid}/progress", headers=_bearer(viewer)).status_code in (200, 404)
    # POST 는 전부 403(재분석·대화)
    assert client.post(f"/api/v1/reports/{sid}/analyze", headers=_bearer(viewer)).status_code == 403
    assert client.post("/api/v1/diagnoses/submit_message", headers=_bearer(viewer),
                       json={"session_id": sid, "diagnosis_id": sid, "content": "안녕"}).status_code == 403
    # 다른 세션은 403
    _, sid_b = _make_session(client)
    assert client.get(f"/api/v1/reports/{sid_b}", headers=_bearer(viewer)).status_code == 403


def test_view_token_bound_to_session_and_expiry(client, auth_headers):
    from diag_project.services.report_view_token import reset_used_jti
    from diag_project.services.auth import _signing_key
    from diag_project.config import settings
    reset_used_jti()
    pid_a, sid_a = _make_session(client)
    _, sid_b = _make_session(client)
    vt = _issue(client, auth_headers, sid_a).json()["view_token"]
    assert _exchange(client, sid_b, vt).status_code == 403          # 다른 세션으로 교환 불가
    assert _exchange(client, sid_a, vt).status_code == 200          # 위 403 은 jti 를 소진하지 않는다 — 발급된 세션에서는 열린다
    # 만료된 1회용 토큰
    claims = jwt.get_unverified_claims(vt)
    expired = jwt.encode({**claims, "jti": uuid.uuid4().hex, "exp": int(time.time()) - 5}, _signing_key(), algorithm=settings.ALGORITHM)
    assert _exchange(client, sid_a, expired).status_code == 401
    # 열람 토큰(typ=report_viewer)으로는 교환할 수 없다
    viewer = jwt.encode({**claims, "typ": "report_viewer", "exp": int(time.time()) + 600}, _signing_key(), algorithm=settings.ALGORITHM)
    assert _exchange(client, sid_a, viewer).status_code == 403
    assert client.post(f"/api/v1/admin/sessions/{uuid.uuid4()}/view-token", headers=auth_headers).status_code == 404


def test_hr_admin_only_own_company(client, auth_headers):
    from diag_project.services.report_view_token import reset_used_jti
    reset_used_jti()
    comp_x, hr_x = _make_company_admin(client)
    comp_y, hr_y = _make_company_admin(client)
    _, sid_x = _make_session(client, company_id=comp_x)
    _, sid_none = _make_session(client)
    assert _issue(client, _bearer(hr_x), sid_x).status_code == 200      # 자사 참여자
    assert _issue(client, _bearer(hr_y), sid_x).status_code == 403      # 타사 session_id
    assert _issue(client, _bearer(hr_x), sid_none).status_code == 403   # 소속 없는 참여자
    # 마스터가 고객사 Y 로 들어간 상태(X-Act-As-Company)에서는 X 참여자 403, 대리 없는 마스터는 200
    assert _issue(client, {**auth_headers, "X-Act-As-Company": str(comp_y)}, sid_x).status_code == 403
    assert _issue(client, {**auth_headers, "X-Act-As-Company": str(comp_x)}, sid_x).status_code == 200
    assert _issue(client, auth_headers, sid_x).status_code == 200
    # 참여자 토큰으로는 발급 불가
    from diag_project.services.participant_auth import create_participant_token
    pid, sid = _make_session(client)
    assert _issue(client, _bearer(create_participant_token(pid)), sid).status_code == 401
