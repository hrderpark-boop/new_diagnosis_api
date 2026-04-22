# tests/test_participants.py

import pytest
from fastapi.testclient import TestClient
from uuid import UUID, uuid4
import logging

# ==========================================================
# 헬퍼 함수 (Helper Functions)
# ==========================================================

def create_test_group(client: TestClient, suffix: str = "") -> dict:
    """테스트용 그룹(Group)을 생성하고 JSON 응답을 반환합니다."""
    code = f"GRP-{uuid4()}"[:10].upper()
    group_data = {
        "name": f"Test Group {suffix}",
        "group_code": code
    }
    response = client.post("/api/v1/groups/", json=group_data)
    
    if response.status_code != 201:
         logging.warning(f"Helper (Group) creation failed: {response.json()}")
    
    assert response.status_code == 201, f"Helper (Group) creation failed: {response.json()}"
    return response.json()

def create_test_participant(client: TestClient, group_id: str, suffix: str = "") -> dict:
    """테스트용 참가자(Participant)를 생성하고 JSON 응답을 반환합니다."""
    email = f"participant_{suffix}_{uuid4()}@test.com"
    participant_data = {
        "name": f"Test Participant {suffix}",
        "email": email,
        "password": "testpassword123",
        "group_id": group_id
    }
    response = client.post("/api/v1/participants/", json=participant_data)
    
    assert response.status_code == 201, f"Helper (Participant) creation failed: {response.json()}"
    return response.json()

# ⚠️ (C-3/4) 1. 로그인 헬퍼 함수 추가
def get_participant_token(client: TestClient, email: str, group_code: str) -> dict:
    """(Helper) 특정 유저로 로그인하고 auth_headers 딕셔너리를 반환합니다."""
    login_data = {
        "email": email,
        "password": "testpassword123",
        "group_code": group_code
    }
    login_res = client.post("/api/v1/participants/token", json=login_data)
    assert login_res.status_code == 200, f"Auth helper failed to log in: {login_res.json()}"
    
    token = login_res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# ==========================================================
# 참가자(Participant) CRUD 테스트
# ==========================================================

def test_create_participant(client: TestClient):
    """(C) 참가자 생성 API를 테스트합니다. (인증 불필요)"""
    group = create_test_group(client, "ForCreate")
    group_id = group["id"]
    
    email = f"participant_create_{uuid4()}@test.com"
    participant_data = {
        "name": "Test Participant Create",
        "email": email,
        "password": "testpassword123",
        "group_id": group_id
    }
    
    response = client.post("/api/v1/participants/", json=participant_data)
    
    assert response.status_code == 201
    data = response.json()
    assert data["email"] == email

def test_create_participant_duplicate_email(client: TestClient):
    """(C) 이메일 중복 시 409 오류를 테스트합니다. (인증 불필요)"""
    group = create_test_group(client, "ForDuplicateEmail")
    group_id = group["id"]
    p1 = create_test_participant(client, group_id, "P1")
    
    participant_data = {
        "name": "Test Participant P2",
        "email": p1["email"], # 👈 중복 이메일
        "password": "anotherpassword",
        "group_id": group_id
    }
    response = client.post("/api/v1/participants/", json=participant_data)
    assert response.status_code == 409

def test_read_participants(client: TestClient, auth_headers: dict):
    """(R) 모든 참가자 조회 API를 테스트합니다. (인증 필요)"""
    group = create_test_group(client, "ForReadList")
    group_id = group["id"]
    
    p1 = create_test_participant(client, group_id, "List1")
    p2 = create_test_participant(client, group_id, "List2")
    
    response = client.get("/api/v1/participants/", headers=auth_headers) 
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data["items"], list)

def test_read_single_participant(client: TestClient, auth_headers: dict):
    """(R) 단일 참가자 조회 API를 테스트합니다. (인증 필요)"""
    group = create_test_group(client, "ForReadSingle")
    p1 = create_test_participant(client, group["id"], "Single")
    p1_id = p1["id"]
    
    response = client.get(f"/api/v1/participants/{p1_id}", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["id"] == p1_id

# ⚠️ (C-3/4) 2. 'auth_headers' Fixture를 제거 (이 테스트는 자체 로그인이 필요)
def test_update_participant(client: TestClient):
    """(U) 참가자가 '자기 자신'의 정보를 업데이트(PATCH)하는지 테스트합니다."""
    group1 = create_test_group(client, "Group1")
    group2 = create_test_group(client, "Group2")
    p1 = create_test_participant(client, group1["id"], "ForUpdate")
    p1_id = p1["id"]

    # ⚠️ (C-3/4) 3. 'p1' 유저로 직접 로그인해서 토큰 획득
    p1_headers = get_participant_token(client, p1["email"], group1["group_code"])

    update_data = {
        "name": "Updated Name",
        "email": f"updated_{uuid4()}@test.com",
        "group_id": group2["id"],
        "password": "newpassword123" 
    }
    
    # ⚠️ (C-3/4) 4. 'p1'의 토큰으로 'p1'의 정보를 수정
    response = client.patch(f"/api/v1/participants/{p1_id}", json=update_data, headers=p1_headers)
    
    # ‼️ 이제 403이 아닌 200이 되어야 합니다.
    assert response.status_code == 200 
    data = response.json()
    assert data["id"] == p1_id
    assert data["name"] == "Updated Name"
    
    # (변경된 비밀번호로 로그인 테스트)
    login_data = {
        "email": update_data["email"], 
        "password": "newpassword123",
        "group_code": group2["group_code"] # 👈 변경된 그룹 코드로 로그인
    }
    login_response = client.post("/api/v1/participants/token", json=login_data)
    assert login_response.status_code == 200
    assert "access_token" in login_response.json()

# ⚠️ (C-3/4) 5. 'auth_headers' Fixture를 제거 (이 테스트는 자체 로그인이 필요)
def test_delete_participant(client: TestClient):
    """(D) 참가자가 '자기 자신'을 삭제하는지 테스트합니다."""
    group = create_test_group(client, "ForDelete")
    p1 = create_test_participant(client, group["id"], "DeleteMe")
    p1_id = p1["id"]
    
    # ⚠️ (C-3/4) 6. 'p1' 유저로 직접 로그인해서 토큰 획득
    p1_headers = get_participant_token(client, p1["email"], group["group_code"])

    # ⚠️ (C-3/4) 7. 'p1'의 토큰으로 'p1'을 삭제
    delete_response = client.delete(f"/api/v1/participants/{p1_id}", headers=p1_headers)

    # ‼️ 이제 403이 아닌 204가 되어야 합니다.
    assert delete_response.status_code == 204
    
    # (삭제 확인)
    # ⚠️ (C-3/4) 8. 다른 유저의 토큰(auth_headers)으로 조회 시도
    # (conftest의 auth_headers가 다른 유저를 생성하므로, 여기서 auth_headers를 새로 만듭니다)
    other_group = create_test_group(client, "Other")
    other_p = create_test_participant(client, other_group["id"], "OtherUser")
    other_headers = get_participant_token(client, other_p["email"], other_group["group_code"])
    
    get_response = client.get(f"/api/v1/participants/{p1_id}", headers=other_headers)
    assert get_response.status_code == 404

# ==========================================================
# 참가자 인증(Login) 테스트 (변경 없음)
# ==========================================================

def test_participant_login(client: TestClient):
    """(Auth) 참가자 로그인 API를 테스트합니다."""
    group = create_test_group(client, "ForLogin")
    p1 = create_test_participant(client, group["id"], "LoginUser")
    
    login_data = {
        "email": p1["email"],
        "password": "testpassword123",
        "group_code": group["group_code"]
    }
    
    response = client.post("/api/v1/participants/token", json=login_data)
    
    assert response.status_code == 200
    data = response.json()
    
    assert "access_token" in data
    assert data["token_type"] == "bearer"

def test_participant_login_wrong_password(client: TestClient):
    """(Auth) 잘못된 비밀번호로 로그인 시 401을 테스트합니다."""
    group = create_test_group(client, "WrongPass")
    p1 = create_test_participant(client, group["id"], "WrongPassUser")
    
    login_data = {
        "email": p1["email"],
        "password": "WRONG_PASSWORD", 
        "group_code": group["group_code"]
    }
    
    response = client.post("/api/v1/participants/token", json=login_data)
    
    assert response.status_code == 401
    assert "Incorrect email, password, or group code" in response.json()["detail"]

def test_participant_login_wrong_group(client: TestClient):
    """(Auth) 잘못된 그룹 코드로 로그인 시 401을 테스트합니다."""
    group = create_test_group(client, "WrongGroup")
    p1 = create_test_participant(client, group["id"], "WrongGroupUser")
    
    login_data = {
        "email": p1["email"],
        "password": "testpassword123",
        "group_code": "WRONG-CODE-123" 
    }
    
    response = client.post("/api/v1/participants/token", json=login_data)
    
    assert response.status_code == 401
    assert "Incorrect email, password, or group code" in response.json()["detail"]