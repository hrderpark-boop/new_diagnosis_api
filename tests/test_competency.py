# tests/test_competency.py

import pytest
from fastapi.testclient import TestClient
from uuid import UUID, uuid4
import logging

# ==========================================================
# 헬퍼 함수 (Helper Functions)
# ⚠️ (C-3/5) 1. 'headers'를 받도록 수정
# ==========================================================

def create_test_competency(client: TestClient, suffix: str = "", headers: dict = None) -> dict:
    """(Helper) 테스트용 역량을 생성합니다."""
    competency_data = {
        "name": f"Test Competency {suffix}",
        "description": "A competency for testing."
    }
    # ⚠️ (C-3/5) 2. headers 전달
    response = client.post("/api/v1/competencies/", json=competency_data, headers=headers)
    assert response.status_code == 201, f"Helper (Competency) creation failed: {response.json()}"
    return response.json()

def create_test_indicator(client: TestClient, competency_id: str, suffix: str = "", headers: dict = None) -> dict:
    """(Helper) 테스트용 지표를 생성합니다."""
    indicator_data = {
        "competency_id": competency_id,
        "name": f"Test Indicator {suffix}",
        "description": "An indicator for testing."
    }
    # ⚠️ (C-3/5) 2. headers 전달
    response = client.post("/api/v1/indicators/", json=indicator_data, headers=headers)
    assert response.status_code == 201, f"Helper (Indicator) creation failed: {response.json()}"
    return response.json()

# ==========================================================
# Fixture
# ==========================================================

@pytest.fixture(scope="function")
def setup_competency_data(client: TestClient, auth_headers: dict): # 👈 3. auth_headers Fixture 요청
    """테스트 함수에서 사용할 기본 역량 및 지표 데이터를 생성합니다."""
    
    # ⚠️ (C-3/5) 4. 헬퍼에 auth_headers 전달
    competency1 = create_test_competency(client, "Setup1", headers=auth_headers)
    competency2 = create_test_competency(client, "Setup2", headers=auth_headers)
    indicator1 = create_test_indicator(client, competency1["id"], "Setup1", headers=auth_headers)
    
    return {
        "c1": competency1,
        "c2": competency2,
        "i1": indicator1,
        "auth_headers": auth_headers # 👈 5. 헤더를 테스트 함수로 전달
    }

# ==========================================================
# 역량(Competency) CRUD 테스트
# ==========================================================

# ⚠️ (C-3/5) 6. 모든 테스트가 'auth_headers' 또는 'setup_competency_data'를 사용하도록 수정

def test_create_competency(client: TestClient, auth_headers: dict):
    """(C) 새로운 역량 생성 API를 테스트합니다."""
    competency_data = {
        "name": "Create Competency",
        "description": "Testing creation."
    }
    response = client.post("/api/v1/competencies/", json=competency_data, headers=auth_headers)
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Create Competency"

def test_read_competencies(client: TestClient, setup_competency_data: dict):
    """(R) 모든 역량 조회 API를 테스트합니다."""
    headers = setup_competency_data["auth_headers"]
    response = client.get("/api/v1/competencies/", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data["items"], list)
    assert data["total"] >= 2

def test_read_single_competency(client: TestClient, setup_competency_data: dict):
    """(R) 단일 역량 조회 API를 테스트합니다."""
    headers = setup_competency_data["auth_headers"]
    c1_id = setup_competency_data["c1"]["id"]
    
    response = client.get(f"/api/v1/competencies/{c1_id}", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == c1_id

def test_read_non_existent_competency(client: TestClient, auth_headers: dict):
    """(R) 존재하지 않는 역량 조회 시 404 응답을 테스트합니다."""
    non_existent_id = str(uuid4())
    response = client.get(f"/api/v1/competencies/{non_existent_id}", headers=auth_headers)
    
    # ⚠️ (C-3/5) 7. 401 -> 404로 수정 (인증은 통과, 데이터가 없음)
    assert response.status_code == 404 

def test_update_competency(client: TestClient, setup_competency_data: dict):
    """(U) 역량 정보 업데이트(PATCH) API를 테스트합니다."""
    headers = setup_competency_data["auth_headers"]
    c1_id = setup_competency_data["c1"]["id"]
    
    update_data = {"name": "Updated Competency Name"}
    response = client.patch(f"/api/v1/competencies/{c1_id}", json=update_data, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Competency Name"

def test_delete_competency(client: TestClient, setup_competency_data: dict):
    """(D) 역량 삭제 API를 테스트합니다."""
    headers = setup_competency_data["auth_headers"]
    c2_id = setup_competency_data["c2"]["id"]
    
    delete_response = client.delete(f"/api/v1/competencies/{c2_id}", headers=headers)
    assert delete_response.status_code == 204
    
    get_response = client.get(f"/api/v1/competencies/{c2_id}", headers=headers)
    assert get_response.status_code == 404

# ==========================================================
# 지표(Indicator) CRUD 테스트
# ==========================================================

def test_create_indicator_for_competency(client: TestClient, setup_competency_data: dict):
    """(C) 역량에 대한 지표 생성 API를 테스트합니다."""
    headers = setup_competency_data["auth_headers"]
    c1_id = setup_competency_data["c1"]["id"]
    
    indicator_data = {
        "competency_id": c1_id,
        "name": "New Indicator",
        "description": "Testing indicator creation."
    }
    response = client.post("/api/v1/indicators/", json=indicator_data, headers=headers)
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "New Indicator"
    assert data["competency_id"] == c1_id

def test_read_indicators_for_competency(client: TestClient, setup_competency_data: dict):
    """(R) 특정 역량에 대한 지표 목록 조회 API를 테스트합니다."""
    headers = setup_competency_data["auth_headers"]
    c1_id = setup_competency_data["c1"]["id"]
    
    response = client.get(f"/api/v1/competencies/{c1_id}/indicators/", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert data[0]["id"] == setup_competency_data["i1"]["id"]

def test_read_single_indicator_for_competency(client: TestClient, setup_competency_data: dict):
    """(R) 단일 지표 조회 API를 테스트합니다."""
    headers = setup_competency_data["auth_headers"]
    i1_id = setup_competency_data["i1"]["id"]
    
    response = client.get(f"/api/v1/indicators/{i1_id}", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == i1_id

def test_fail_read_indicator_from_wrong_competency(client: TestClient, setup_competency_data: dict):
    """(R) 다른 역량 ID로 지표 목록 조회 시 빈 리스트를 반환하는지 테스트합니다."""
    headers = setup_competency_data["auth_headers"]
    c2_id = setup_competency_data["c2"]["id"] # i1이 속하지 않은 c2
    
    response = client.get(f"/api/v1/competencies/{c2_id}/indicators/", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) == 0 # 👈 i1이 포함되지 않아야 함

def test_update_indicator_for_competency(client: TestClient, setup_competency_data: dict):
    """(U) 지표 정보 업데이트(PATCH) API를 테스트합니다."""
    headers = setup_competency_data["auth_headers"]
    i1_id = setup_competency_data["i1"]["id"]
    
    update_data = {"name": "Updated Indicator Name"}
    response = client.patch(f"/api/v1/indicators/{i1_id}", json=update_data, headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == "Updated Indicator Name"

def test_delete_indicator_for_competency(client: TestClient, setup_competency_data: dict):
    """(D) 지표 삭제 API를 테스트합니다."""
    headers = setup_competency_data["auth_headers"]
    c1_id = setup_competency_data["c1"]["id"]
    
    # 새 지표 생성 및 삭제
    indicator_to_delete = create_test_indicator(client, c1_id, "DeleteMe", headers=headers)
    indicator_id = indicator_to_delete["id"]
    
    delete_response = client.delete(f"/api/v1/indicators/{indicator_id}", headers=headers)
    assert delete_response.status_code == 204
    
    get_response = client.get(f"/api/v1/indicators/{indicator_id}", headers=headers)
    assert get_response.status_code == 404