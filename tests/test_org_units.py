"""조직 참여 코드(AS1) · HR 교육 데이터 테스트.

- 코드 규칙(services/org_codes.py) 순수 함수
- 마스터 API: 접두어 지정, 본부·팀 등록, 일괄 등록, 수정·삭제 제약
- 참여자 로그인 게이트: 조직 코드로 회사·소속이 함께 정해짐, 사용 중지 코드는 거부
- 고객사 HR 격리: 다른 회사 조직은 못 봄
- 교육 요약: 강화·개선 필요 역량 판정 규칙
실행: pytest tests/test_org_units.py
"""
import uuid

from diag_project.services import org_codes
from diag_project.routes.admin_education import strength_and_growth, courses_of


# ── 순수 규칙 ────────────────────────────────────────────────────────────────
def test_prefix_rules():
    assert org_codes.validate_prefix("a") is None
    assert org_codes.validate_prefix("ACME") is not None          # 4자
    assert org_codes.validate_prefix("A1") is not None            # 숫자
    assert org_codes.validate_prefix("A", ["B", "CD"]) is None
    assert org_codes.validate_prefix("A", ["A"]) is not None      # 같은 접두어
    assert org_codes.validate_prefix("AS", ["A"]) is not None     # 앞부분 겹침(모호)
    assert org_codes.validate_prefix("A", ["AS"]) is not None


def test_codes_and_numbers():
    assert org_codes.division_code("a", " s ") == "AS"
    assert org_codes.team_code("AS", 1) == "AS1"
    assert org_codes.team_code("AS", 10) == "AS10"
    assert org_codes.next_team_number([]) == 1
    assert org_codes.next_team_number(["1", "2", "5"]) == 6
    assert org_codes.validate_team_number(0) is not None
    assert org_codes.validate_team_number(100) is not None
    assert org_codes.validate_division_code("SAL") is not None


def test_strength_and_growth_tiebreak_and_minimum():
    one = {"radar_chart": {"organization_management": 3.0}}
    assert strength_and_growth(one) == (None, None)               # 측정 1개면 가르지 않음
    tie = {
        "radar_chart": {"organization_management": 2.0, "performance_management": 2.0, "people_management": 1.0},
        "details": {
            "organization_management": {"sub_scores": {"a": 1.0, "b": 1.0}},
            "performance_management": {"sub_scores": {"a": 2.0, "b": 2.0}},
        },
    }
    s, g = strength_and_growth(tie)
    assert s == "performance_management"                           # 동점 → 하위역량 평균 높은 쪽
    assert g == "people_management"
    # measured_count 0 인 역량은 측정에서 빠진다
    mc = {"details": {
        "organization_management": {"measured_count": 0, "score": 1.0},
        "performance_management": {"measured_count": 2, "score": 3.0},
        "people_management": {"measured_count": 1, "score": 2.0},
    }}
    assert strength_and_growth(mc) == ("performance_management", "people_management")


def test_courses_of():
    sc = {"course_recommendation": {"growth": [{"course": "피드백 대화", "track": "A"}, {"x": 1}],
                                    "strength": {"course": "실행력 코칭", "track": "D"}}}
    got = courses_of(sc)
    assert [(c["course"], c["kind"]) for c in got] == [("피드백 대화", "growth"), ("실행력 코칭", "strength")]
    assert courses_of({}) == []


# ── API 흐름 ─────────────────────────────────────────────────────────────────
def _client_admin_headers(client, company_id):
    from diag_project.database import async_session
    from diag_project.models.admin_user import AdminUser, UserRole
    from diag_project.services.auth import create_access_token, hash_password

    async def _make():
        async with async_session() as db:
            a = AdminUser(email=f"hr-{uuid.uuid4().hex[:8]}@test.local", name="hr", role=UserRole.CLIENT_ADMIN.value,
                          company_id=uuid.UUID(company_id), password_hash=hash_password("pytest-password-1"))
            db.add(a)
            await db.commit()
            await db.refresh(a)
            return a

    a = client.portal.call(_make)
    return {"Authorization": f"Bearer {create_access_token(a)}"}


def _new_company(client, auth_headers, code):
    r = client.post("/api/v1/admin/companies", json={"name": f"조직테스트 {code}", "code": code}, headers=auth_headers)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def test_org_code_flow(client, auth_headers):
    cid = _new_company(client, auth_headers, "ORGT-" + uuid.uuid4().hex[:6])
    other = _new_company(client, auth_headers, "ORGT-" + uuid.uuid4().hex[:6])
    base = "/api/v1/admin"

    # 접두어 없이 본부 등록 → 400
    r = client.post(f"{base}/companies/{cid}/org-units", json={"level": "division", "name": "영업본부", "short_code": "S"}, headers=auth_headers)
    assert r.status_code == 400

    # 접두어 지정 + 다른 회사와 앞부분 겹침 거부
    assert client.patch(f"{base}/companies/{cid}", json={"org_prefix": "qz"}, headers=auth_headers).json()["org_prefix"] == "QZ"
    assert client.patch(f"{base}/companies/{other}", json={"org_prefix": "Q"}, headers=auth_headers).status_code == 400

    # 본부 → 팀(자동 번호) → 팀(번호 지정)
    div = client.post(f"{base}/companies/{cid}/org-units", json={"level": "division", "name": "영업본부", "short_code": "s"}, headers=auth_headers)
    assert div.status_code == 201 and div.json()["code"] == "QZS"
    div_id = div.json()["id"]
    t1 = client.post(f"{base}/companies/{cid}/org-units", json={"level": "team", "name": "영업1팀", "parent_id": div_id}, headers=auth_headers)
    t2 = client.post(f"{base}/companies/{cid}/org-units", json={"level": "team", "name": "영업2팀", "parent_id": div_id}, headers=auth_headers)
    t10 = client.post(f"{base}/companies/{cid}/org-units", json={"level": "team", "name": "해외팀", "parent_id": div_id, "number": 10}, headers=auth_headers)
    assert (t1.json()["code"], t2.json()["code"], t10.json()["code"]) == ("QZS1", "QZS2", "QZS10")
    # 같은 본부 코드 중복 → 409
    assert client.post(f"{base}/companies/{cid}/org-units", json={"level": "division", "name": "판매본부", "short_code": "S"}, headers=auth_headers).status_code == 409

    # 조직 코드가 생긴 뒤 접두어 변경 → 409
    assert client.patch(f"{base}/companies/{cid}", json={"org_prefix": "QY"}, headers=auth_headers).status_code == 409

    # 참여자가 조직 코드(소문자·공백)로 로그인 → 회사·소속이 함께 정해짐
    email = f"org-{uuid.uuid4().hex[:8]}@test.local"
    r = client.post("/api/v1/participants/token", json={"email": email, "name": "조직 참여자", "group_code": " qzs1 ", "password": "pw"})
    assert r.status_code == 200, r.text

    tree = client.get(f"{base}/companies/{cid}/org-units", headers=auth_headers).json()
    d = tree["divisions"][0]
    assert d["code"] == "QZS" and d["registered_total"] == 1
    assert [t["code"] for t in d["teams"]] == ["QZS1", "QZS2", "QZS10"]
    assert d["teams"][0]["registered"] == 1

    # 참여자 목록: 본부로 거르면 소속 팀 인원 포함 + 소속 표시, group_code 는 회사 코드
    lst = client.get(f"{base}/participants", params={"org_unit_id": div_id}, headers=auth_headers).json()
    row = next(i for i in lst["items"] if i["email"] == email)
    assert row["org_code"] == "QZS1" and row["division_name"] == "영업본부"
    assert row["group_code"].startswith("ORGT-")

    # 참여자가 있는 팀은 삭제 불가, 빈 팀은 삭제 가능
    assert client.delete(f"{base}/org-units/{t1.json()['id']}", headers=auth_headers).status_code == 409
    assert client.delete(f"{base}/org-units/{t10.json()['id']}", headers=auth_headers).status_code == 200
    # 하위 팀이 있는 본부는 삭제 불가
    assert client.delete(f"{base}/org-units/{div_id}", headers=auth_headers).status_code == 409

    # 사용 중지한 코드로는 로그인 거부
    assert client.patch(f"{base}/org-units/{t2.json()['id']}", json={"is_active": False}, headers=auth_headers).status_code == 200
    r = client.post("/api/v1/participants/token", json={"email": f"x-{uuid.uuid4().hex[:6]}@test.local", "name": "x", "group_code": "QZS2", "password": "pw"})
    assert r.status_code == 403

    # 고객사 HR: 자사 트리는 보이고, 다른 회사 트리는 403, 쓰기는 403
    hr = _client_admin_headers(client, cid)
    assert client.get(f"{base}/companies/{cid}/org-units", headers=hr).status_code == 200
    assert client.get(f"{base}/companies/{other}/org-units", headers=hr).status_code == 403
    assert client.post(f"{base}/companies/{cid}/org-units", json={"level": "division", "name": "x", "short_code": "X"}, headers=hr).status_code == 403

    # 교육 요약·명단: 리포트가 없으면 완료 0, 명단엔 미완료로
    summ = client.get(f"{base}/education/summary", headers=hr).json()
    assert summ["participants"] == 1 and summ["completed"] == 0
    ppl = client.get(f"{base}/education/people", headers=hr).json()
    assert ppl["total"] == 1 and ppl["items"][0]["completed"] is False and ppl["items"][0]["org_code"] == "QZS1"


def test_bulk_create_and_row_error_rollback(client, auth_headers):
    cid = _new_company(client, auth_headers, "ORGB-" + uuid.uuid4().hex[:6])
    base = "/api/v1/admin"
    assert client.patch(f"{base}/companies/{cid}", json={"org_prefix": "WB"}, headers=auth_headers).status_code == 200
    rows = [
        {"division": "생산본부", "division_code": "P", "team": "생산1팀"},
        {"division": "생산본부", "division_code": "P", "team": "생산2팀"},
        {"division": "경영지원본부", "division_code": "M", "team": "인사팀"},
        {"division": "생산본부", "division_code": "P", "team": "생산1팀"},   # 중복 → 건너뜀
    ]
    r = client.post(f"{base}/companies/{cid}/org-units/bulk", json={"rows": rows}, headers=auth_headers)
    assert r.status_code == 201, r.text
    codes = [c["code"] for c in r.json()["created"]]
    assert codes == ["WBP", "WBP1", "WBP2", "WBM", "WBM1"] and r.json()["skipped"] == 1

    # 한 행이 규칙 위반(본부 코드 숫자)이면 전부 되돌림
    bad = [{"division": "연구소", "division_code": "R", "team": "연구1팀"},
           {"division": "잘못", "division_code": "9", "team": "x"}]
    r = client.post(f"{base}/companies/{cid}/org-units/bulk", json={"rows": bad}, headers=auth_headers)
    assert r.status_code == 400 and "2행" in r.json()["detail"]
    tree = client.get(f"{base}/companies/{cid}/org-units", headers=auth_headers).json()
    assert [d["code"] for d in tree["divisions"]] == ["WBM", "WBP"] or [d["code"] for d in tree["divisions"]] == ["WBP", "WBM"]
    assert all(d["code"] != "WBR" for d in tree["divisions"])


def test_office_period_stats_status_and_catalog(client, auth_headers):
    cid = _new_company(client, auth_headers, "ORGO-" + uuid.uuid4().hex[:6])
    base = "/api/v1/admin"
    assert client.patch(f"{base}/companies/{cid}", json={"org_prefix": "WO"}, headers=auth_headers).status_code == 200

    # 본부 → 실 → 팀, 본부 직속 팀
    div = client.post(f"{base}/companies/{cid}/org-units", json={"level": "division", "name": "영업본부", "short_code": "S"}, headers=auth_headers).json()
    off = client.post(f"{base}/companies/{cid}/org-units", json={"level": "office", "name": "마케팅실", "short_code": "M", "parent_id": div["id"]}, headers=auth_headers)
    assert off.status_code == 201 and off.json()["code"] == "WOSM"
    t1 = client.post(f"{base}/companies/{cid}/org-units", json={"level": "team", "name": "브랜드팀", "parent_id": off.json()["id"]}, headers=auth_headers).json()
    t2 = client.post(f"{base}/companies/{cid}/org-units", json={"level": "team", "name": "영업1팀", "parent_id": div["id"]}, headers=auth_headers).json()
    assert (t1["code"], t2["code"]) == ("WOSM1", "WOS1")
    # 실 아래 실은 안 됨
    assert client.post(f"{base}/companies/{cid}/org-units", json={"level": "office", "name": "x", "short_code": "X", "parent_id": off.json()["id"]}, headers=auth_headers).status_code == 400

    tree = client.get(f"{base}/companies/{cid}/org-units", headers=auth_headers).json()
    d = tree["divisions"][0]
    assert [o["code"] for o in d["offices"]] == ["WOSM"] and [t["code"] for t in d["offices"][0]["teams"]] == ["WOSM1"]
    assert [t["code"] for t in d["teams"]] == ["WOS1"]

    # 참여자 2명: 실 소속 팀 1, 본부 직속 팀 1
    for code in ("wosm1", "wos1"):
        r = client.post("/api/v1/participants/token", json={"email": f"o-{uuid.uuid4().hex[:8]}@test.local", "name": "o", "group_code": code, "password": "pw"})
        assert r.status_code == 200, r.text

    # 조직별 통계: 본부는 하위 전체(2명), 실은 1명, 팀 2행. 리포트 없으니 모두 미시작, 평균 None
    st = client.get(f"{base}/companies/{cid}/org-stats", params={"level": "division"}, headers=auth_headers).json()
    assert st["total"]["registered"] == 2 and st["total"]["not_started"] == 2
    assert st["rows"][0]["registered"] == 2 and st["rows"][0]["averages"]["people_management"] is None
    so = client.get(f"{base}/companies/{cid}/org-stats", params={"level": "office"}, headers=auth_headers).json()
    assert [(r["code"], r["registered"]) for r in so["rows"]] == [("WOSM", 1)]
    stt = client.get(f"{base}/companies/{cid}/org-stats", params={"level": "team"}, headers=auth_headers).json()
    assert sorted(r["code"] for r in stt["rows"]) == ["WOS1", "WOSM1"]
    assert client.get(f"{base}/companies/{cid}/org-stats", params={"level": "x"}, headers=auth_headers).status_code == 400

    # 참여자 목록: 미완료 필터 + 조직순 정렬 + 실 이름
    lst = client.get(f"{base}/participants", params={"company_id": cid, "status": "incomplete", "sort": "org"}, headers=auth_headers).json()
    assert [i["org_code"] for i in lst["items"]] == ["WOS1", "WOSM1"]
    assert lst["items"][1]["office_name"] == "마케팅실" and lst["items"][1]["progress_status"] == "not_started"
    assert client.get(f"{base}/participants", params={"company_id": cid, "status": "completed"}, headers=auth_headers).json()["total"] == 0

    # 진단 기간: HR 도 자사는 설정 가능, 한쪽만·역순은 거부, 일별 추이는 기간 길이만큼
    hr = _client_admin_headers(client, cid)
    assert client.put(f"{base}/companies/{cid}/period", json={"diagnosis_start": "2026-11-01"}, headers=hr).status_code == 400
    assert client.put(f"{base}/companies/{cid}/period", json={"diagnosis_start": "2026-11-10", "diagnosis_end": "2026-11-01"}, headers=hr).status_code == 400
    r = client.put(f"{base}/companies/{cid}/period", json={"diagnosis_start": "2026-11-01", "diagnosis_end": "2026-11-15"}, headers=hr)
    assert r.status_code == 200 and r.json()["diagnosis_end"] == "2026-11-15"
    daily = client.get(f"{base}/stats/daily", params={"start": "2026-11-01", "end": "2026-11-15"}, headers=hr).json()
    assert len(daily) == 15 and daily[0]["date"] == "2026-11-01" and "누적완료" in daily[0]
    other = _new_company(client, auth_headers, "ORGO-" + uuid.uuid4().hex[:6])
    assert client.put(f"{base}/companies/{other}/period", json={"diagnosis_start": None, "diagnosis_end": None}, headers=hr).status_code == 403

    # 과정 안내서: 5개 역량 × 하위역량 × A~D, 교육목표 포함, 자리표시 VOD 주소는 숨김
    cat = client.get(f"{base}/education/catalog", headers=hr).json()
    assert len(cat["competencies"]) == 5 and [t["track"] for t in cat["tracks"]] == ["A", "B", "C", "D"]
    sub = cat["competencies"][0]["subs"][0]
    assert set(sub["courses"]) == {"A", "B", "C", "D"} and sub["courses"]["A"]["goal"]
    assert sum(len(c["subs"]) for c in cat["competencies"]) == 26
