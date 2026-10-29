"""보안 P0 회귀 테스트 (2026-10-29).

  - 리포트 전체 목록은 마스터만
  - 참여자 API(진단·대화·자가진단·리포트)는 토큰 필수, 본인 세션만(고객사 HR 은 자사 참여자만)
  - 옛 가짜 토큰은 전환 스위치(FM_ALLOW_LEGACY_PARTICIPANT_TOKEN)가 켜져 있을 때만
  - 관리자 로그인 5회 실패 → 429, 참여자 접속 과다 → 429
"""
import uuid

ELLA = uuid.UUID("00000000-0000-0000-0000-000000000011")


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _ptoken(pid) -> dict:
    from diag_project.services.participant_auth import create_participant_token
    return _bearer(create_participant_token(pid))


def _make_session(client, company_id=None):
    from diag_project.database import async_session
    from diag_project.models.diagnosis_session import DiagnosisSession
    from diag_project.models.participant import Participant

    async def _mk():
        async with async_session() as db:
            p = Participant(email=f"sec-{uuid.uuid4().hex[:8]}@test.local", name="보안", company_id=company_id)
            db.add(p); await db.flush()
            s = DiagnosisSession(user_id=p.id, coach_id=ELLA, status="in_progress")
            db.add(s); await db.commit()
            return str(p.id), str(s.id)
    return client.portal.call(_mk)


def _make_company_admin(client):
    """고객사 하나 + 그 회사 HR 관리자 토큰."""
    from diag_project.database import async_session
    from diag_project.models.admin_user import AdminUser, UserRole
    from diag_project.models.company import Company
    from diag_project.services.auth import create_access_token, hash_password

    async def _mk():
        async with async_session() as db:
            tag = uuid.uuid4().hex[:6]
            c = Company(name=f"보안사-{tag}", code=f"SEC-{tag}")
            db.add(c); await db.flush()
            a = AdminUser(email=f"hr-{tag}@test.local", name="hr", role=UserRole.CLIENT_ADMIN.value,
                          password_hash=hash_password("pw-1"), company_id=c.id)
            db.add(a); await db.commit(); await db.refresh(a)
            return c.id, create_access_token(a)
    return client.portal.call(_mk)


def test_report_list_requires_super_admin(client, auth_headers):
    assert client.get("/api/v1/reports/").status_code == 401
    pid, _ = _make_session(client)
    assert client.get("/api/v1/reports/", headers=_ptoken(pid)).status_code in (401, 403)
    assert client.get("/api/v1/reports/", headers=auth_headers).status_code == 200


def test_participant_endpoints_require_token(client):
    pid, sid = _make_session(client)
    assert client.get("/api/v1/diagnoses/active", params={"participant_id": pid}).status_code == 401
    assert client.get(f"/api/v1/diagnoses/{sid}/state").status_code == 401
    assert client.get(f"/api/v1/sessions/{sid}/self-eval").status_code == 401
    assert client.get(f"/api/v1/reports/{sid}").status_code == 401
    assert client.post("/api/v1/diagnoses/submit_message",
                       json={"session_id": sid, "diagnosis_id": sid, "content": "안녕"}).status_code == 401
    # 위조 서명 토큰도 401
    assert client.get(f"/api/v1/diagnoses/{sid}/state", headers=_bearer("abc.def.ghi")).status_code == 401


def test_participant_cannot_touch_other_session(client):
    pid_a, sid_a = _make_session(client)
    pid_b, sid_b = _make_session(client)
    ha = _ptoken(pid_a)
    assert client.get(f"/api/v1/diagnoses/{sid_a}/state", headers=ha).status_code == 200
    assert client.get(f"/api/v1/diagnoses/{sid_b}/state", headers=ha).status_code == 403
    assert client.get(f"/api/v1/sessions/{sid_b}/self-eval", headers=ha).status_code == 403
    assert client.get(f"/api/v1/reports/{sid_b}", headers=ha).status_code == 403
    assert client.get("/api/v1/diagnoses/active", params={"participant_id": pid_b}, headers=ha).status_code == 403
    assert client.post("/api/v1/diagnoses/submit_message", headers=ha,
                       json={"session_id": sid_b, "diagnosis_id": sid_b, "content": "남의 세션"}).status_code == 403


def test_client_admin_only_own_company(client, auth_headers):
    company_id, hr_token = _make_company_admin(client)
    _, own_sid = _make_session(client, company_id=company_id)
    _, other_sid = _make_session(client)
    assert client.get(f"/api/v1/sessions/{own_sid}/self-eval", headers=_bearer(hr_token)).status_code == 200
    assert client.get(f"/api/v1/sessions/{other_sid}/self-eval", headers=_bearer(hr_token)).status_code == 403
    # 마스터는 전부
    assert client.get(f"/api/v1/sessions/{other_sid}/self-eval", headers=auth_headers).status_code == 200


def test_legacy_token_only_while_switch_on(client, monkeypatch):
    pid, sid = _make_session(client)
    legacy = _bearer(f"fake-jwt-token-for-{pid}")
    monkeypatch.setenv("FM_ALLOW_LEGACY_PARTICIPANT_TOKEN", "1")
    assert client.get(f"/api/v1/diagnoses/{sid}/state", headers=legacy).status_code == 200
    monkeypatch.setenv("FM_ALLOW_LEGACY_PARTICIPANT_TOKEN", "0")
    assert client.get(f"/api/v1/diagnoses/{sid}/state", headers=legacy).status_code == 401


def test_participant_login_issues_signed_token(client, seed_data):
    r = client.post("/api/v1/participants/token", json={
        "email": f"tok-{uuid.uuid4().hex[:6]}@example.com", "password": "password", "name": "토큰", "group_code": "G-TEST"})
    assert r.status_code == 200, r.text
    tok = r.json()["access_token"]
    assert not tok.startswith("fake-jwt-token-for-")
    from diag_project.services.auth import decode_token
    payload = decode_token(tok)
    assert payload["typ"] == "participant" and payload["sub"] == r.json()["participant_id"]
    # 참여자 토큰으로 관리자 API 는 못 쓴다
    assert client.get("/api/v1/admin/participants", headers=_bearer(tok)).status_code in (401, 403)


def test_admin_login_locks_after_five_failures(client):
    email = f"nobody-{uuid.uuid4().hex[:6]}@test.local"
    for _ in range(5):
        assert client.post("/api/v1/admin/auth/login", json={"email": email, "password": "wrong"}).status_code == 401
    r = client.post("/api/v1/admin/auth/login", json={"email": email, "password": "wrong"})
    assert r.status_code == 429 and "Retry-After" in r.headers
    # 다른 계정은 영향 없음
    assert client.post("/api/v1/admin/auth/login",
                       json={"email": f"x-{email}", "password": "wrong"}).status_code == 401


def test_participant_login_rate_limited(client):
    from diag_project.services import rate_limit
    for _ in range(rate_limit.PARTICIPANT_MAX_REQ):
        client.post("/api/v1/participants/token", json={"email": "", "password": "", "group_code": "NOPE"})
    r = client.post("/api/v1/participants/token", json={"email": "", "password": "", "group_code": "NOPE"})
    assert r.status_code == 429
