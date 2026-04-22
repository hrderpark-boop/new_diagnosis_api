# tests/test_coaches.py

import pytest
from fastapi.testclient import TestClient
from uuid import UUID, uuid4

# ⚠️ (C-3 인증) 1. 헬퍼 함수가 'headers'를 받도록 수정
def create_test_coach(client: TestClient, suffix: str = "", headers: dict = None) -> dict:
    """
    테스트용 코치를 생성하고 JSON 응답을 반환하는 헬퍼 함수
    (인증 헤더 필요)
    """
    user_uuid = str(uuid4())
    coach_data = {
        "name": f"Test Coach {suffix}",
        "description": "A coach for testing purposes.",
        "avatar_url": "http://example.com/avatar.jpg",
        "character_tags": "friendly, supportive",
        "user_id": user_uuid,
        "email": f"test_coach_{user_uuid}@test.com"
    }
    
    # ⚠️ (C-3 인증) 2. client 호출 시 headers 전달
    response = client.post("/api/v1/coaches/", json=coach_data, headers=headers)
    
    # (이제 201이 되어야 함)
    assert response.status_code == 201, f"Helper creation failed: {response.json()}"
    return response.json()


# ==========================================================
# 코치(Coach) CRUD 테스트
# ==========================================================

# ⚠️ (C-3 인증) 3. 'auth_headers' Fixture를 인자로 추가
def test_create_coach(client: TestClient, auth_headers: dict):
    """(C) 새로운 코치 생성 API를 테스트합니다."""
    user_uuid = str(uuid4())
    coach_data = {
        "name": "Create Coach",
        "email": f"create_coach_{user_uuid}@example.com",
        "user_id": user_uuid,
        "description": "Creating a coach.",
        "avatar_url": "http://example.com/create.jpg",
        "character_tags": "create",
        "is_active": True
    }
    
    # ⚠️ (C-3 인증) 4. headers=auth_headers 전달
    response = client.post("/api/v1/coaches/", json=coach_data, headers=auth_headers)
    
    assert response.status_code == 201
    data = response.json()
    assert data["name"] == "Create Coach"
    assert data["email"] == coach_data["email"]


def test_read_coaches(client: TestClient, auth_headers: dict):
    """(R) 모든 코치 조회 API를 테스트합니다."""
    # 최소 2개의 코치를 생성 (헬퍼 함수에 헤더 전달)
    coach1_name = create_test_coach(client, "ForReadList1", headers=auth_headers)["name"]
    coach2_name = create_test_coach(client, "ForReadList2", headers=auth_headers)["name"]

    # 조회 시에도 헤더 전달
    response = client.get("/api/v1/coaches/", headers=auth_headers)
    
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data["items"], list)
    assert data["total"] >= 2
    names = [item["name"] for item in data["items"]]
    assert coach1_name in names
    assert coach2_name in names


def test_read_single_coach(client: TestClient, auth_headers: dict):
    """(R) 단일 코치 조회 API를 테스트합니다."""
    created_coach = create_test_coach(client, "ForReadSingle", headers=auth_headers)
    coach_id = created_coach["id"]

    response = client.get(f"/api/v1/coaches/{coach_id}", headers=auth_headers)
    
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == coach_id
    assert data["name"] == created_coach["name"]


def test_read_non_existent_coach(client: TestClient, auth_headers: dict):
    """(R) 존재하지 않는 코치 조회 시 404 응답을 테스트합니다."""
    non_existent_id = str(uuid4())
    
    response = client.get(f"/api/v1/coaches/{non_existent_id}", headers=auth_headers)
    
    # ⚠️ (C-3 수정) 401이 아니라 404가 떠야 함 (인증은 통과, 데이터가 없음)
    assert response.status_code == 404


def test_update_coach(client: TestClient, auth_headers: dict):
    """(U) 코치 정보 업데이트(PATCH) API를 테스트합니다."""
    created_coach = create_test_coach(client, "ForUpdate", headers=auth_headers)
    coach_id = created_coach["id"]

    update_data = {
        "name": "Updated Coach Name",
        "description": "Updated description.",
        "character_tags": "updated, professional"
    }

    response = client.patch(
        f"/api/v1/coaches/{coach_id}", json=update_data, headers=auth_headers
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == coach_id
    assert data["name"] == "Updated Coach Name"
    assert data["description"] == "Updated description."


def test_delete_coach(client: TestClient, auth_headers: dict):
    """(D) 코치 삭제 API를 테스트합니다."""
    created_coach = create_test_coach(client, "ForDelete", headers=auth_headers)
    coach_id = created_coach["id"]

    # 삭제
    delete_response = client.delete(f"/api/v1/coaches/{coach_id}", headers=auth_headers)
    assert delete_response.status_code == 204

    # 확인 (404)
    get_response = client.get(f"/api/v1/coaches/{coach_id}", headers=auth_headers)
    assert get_response.status_code == 404