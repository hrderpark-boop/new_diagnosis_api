"""관리자 도메인(fm-hr · fm-ops)이 CORS 화이트리스트에 있는지. 실행: pytest tests/test_cors_domains.py"""


def test_admin_domains_allowed(client):
    for origin in ("https://fm.connectn.co.kr", "https://fm-hr.connectn.co.kr", "https://fm-ops.connectn.co.kr"):
        r = client.options("/api/v1/admin/auth/me", headers={
            "Origin": origin, "Access-Control-Request-Method": "GET", "Access-Control-Request-Headers": "authorization"})
        assert r.headers.get("access-control-allow-origin") == origin, origin


def test_unknown_origin_blocked(client):
    r = client.options("/api/v1/admin/auth/me", headers={"Origin": "https://evil.example.com", "Access-Control-Request-Method": "GET"})
    assert r.headers.get("access-control-allow-origin") is None
