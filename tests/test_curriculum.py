"""맞춤 교육체계도 구성 규칙(services/curriculum.py) + API. 실행: pytest tests/test_curriculum.py"""
from diag_project.services.curriculum import MIN_REPORTS, build_curriculum, sub_levels


def _details(org, perf, people, work, self_):
    """역량별 하위역량 점수 dict → details(구 형식 sub_scores)."""
    return {
        "organization_management": {"sub_scores": org},
        "performance_management": {"sub_scores": perf},
        "people_management": {"sub_scores": people},
        "work_management": {"sub_scores": work},
        "self_management": {"sub_scores": self_},
    }


ORG_LOW = {"비전 제시 및 공유": 1.2, "전략적 사고": 1.4}
PEOPLE_LOW = {"갈등관리": 2.1, "신뢰형성": 1.8}
PERF_MID = {"목표설정 및 공유": 3.0, "실행력": 2.9}
WORK_HIGH = {"업무분장": 4.0, "자원 및 시간관리": 3.9}
SELF_HIGH = {"자기인식": 3.6, "회복탄력성": 4.0}


def test_sub_levels_uses_ledger_measured_only_and_rounds():
    d = {"people_management": {"sub_ledger": {
        "갈등관리": {"measured": True, "score": 2.4},
        "신뢰형성": {"measured": False, "score": 1.0},
        "코칭 및 피드백": {"measured": True, "score": 3.6},
    }, "sub_scores": {"갈등관리": 9}}}
    assert sub_levels(d) == {"people_management": {"갈등관리": 2, "코칭 및 피드백": 4}}


def test_insufficient_sample():
    out = build_curriculum([_details(ORG_LOW, PERF_MID, PEOPLE_LOW, WORK_HIGH, SELF_HIGH)] * (MIN_REPORTS - 1))
    assert out["status"] == "insufficient" and out["competencies"] == []


def test_focus_required_elective_and_strength():
    out = build_curriculum([_details(ORG_LOW, PERF_MID, PEOPLE_LOW, WORK_HIGH, SELF_HIGH)] * 4)
    assert out["status"] == "ok" and out["n_reports"] == 4
    comps = {c["key"]: c for c in out["competencies"]}
    # 가장 약한 두 역량이 집중 + 맨 앞
    assert [c["key"] for c in out["competencies"][:2]] == ["organization_management", "people_management"]
    assert comps["organization_management"]["priority"] == "focus"
    assert comps["people_management"]["priority"] == "focus"
    org_items = {r["sub"]: r["items"] for r in comps["organization_management"]["rows"]}
    assert org_items["비전 제시 및 공유"][0]["tier"] == "required" and org_items["비전 제시 및 공유"][0]["track"] == "A"
    people_items = {r["sub"]: r["items"] for r in comps["people_management"]["rows"]}
    assert people_items["갈등관리"][0]["track"] == "B"           # 2.1 → Lv2 → B
    # 집중이 아닌 역량은 선택(성과관리 Lv3 → C)
    perf_items = {r["sub"]: r["items"] for r in comps["performance_management"]["rows"]}
    assert perf_items["목표설정 및 공유"][0]["tier"] == "elective" and perf_items["목표설정 및 공유"][0]["track"] == "C"
    # Lv4 인원이 많으면 강점 확산(D), 개선 과정은 없음
    work_items = {r["sub"]: r["items"] for r in comps["work_management"]["rows"]}
    assert [i["tier"] for i in work_items["업무분장"]] == ["strength"] and work_items["업무분장"][0]["track"] == "D"
    assert out["counts"]["required"] == 4 and out["counts"]["strength"] >= 2
    # 과정 정보는 Pool 에서(이름·교육목표)
    assert org_items["비전 제시 및 공유"][0]["course"] and org_items["비전 제시 및 공유"][0]["goal"]


def test_baseline_makes_relatively_weak_competency_focus():
    """조직 평균이 3.0 이상이어도 비교 기준(회사 전체)보다 낮으면 집중 역량."""
    team = [_details({"비전 제시 및 공유": 3.2}, {"실행력": 3.4}, {"신뢰형성": 3.1}, {"업무분장": 3.6}, {"자기인식": 3.8})] * 3
    company = team + [_details({"비전 제시 및 공유": 4.0}, {"실행력": 3.4}, {"신뢰형성": 3.9}, {"업무분장": 3.6}, {"자기인식": 3.8})] * 6
    out = build_curriculum(team, company)
    focus = [c["key"] for c in out["competencies"] if c["priority"] == "focus"]
    assert set(focus) == {"organization_management", "people_management"}
    assert all(c["baseline_avg"] is not None for c in out["competencies"])


def test_curriculum_endpoint_scoped(client, auth_headers):
    import uuid
    from tests.test_org_units import _client_admin_headers, _new_company
    cid = _new_company(client, auth_headers, "CUR-" + uuid.uuid4().hex[:6])
    hr = _client_admin_headers(client, cid)
    r = client.get("/api/v1/admin/education/curriculum", headers=hr)
    assert r.status_code == 200 and r.json()["status"] == "insufficient" and r.json()["n_reports"] == 0
