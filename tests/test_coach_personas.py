# tests/test_coach_personas.py

import pytest
from fastapi.testclient import TestClient
from uuid import UUID, uuid4

# ⚠️ (C-3 수정) 1. 'create_test_coach' 헬퍼 함수를 여기에 복사합니다.
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
    
    response = client.post("/api/v1/coaches/", json=coach_data, headers=headers)
    
    assert response.status_code == 201, f"Helper (Coach) creation failed: {response.json()}"
    return response.json()

# ⚠️ (C-3 수정) 2. 이 Fixture는 이제 이 파일의 헬퍼를 사용합니다.
@pytest.fixture(scope="function")
def setup_coach(client: TestClient, auth_headers: dict):
    """(Fixture) 테스트용 코치를 생성합니다."""
    coach = create_test_coach(client, "PersonaCoach", headers=auth_headers)
    return coach

# ⚠️ (C-3 수정) 3. 테스트가 auth_headers를 받도록 합니다.
def test_create_coach_and_persona(client: TestClient, auth_headers: dict):
    """
    코치 및 코치 페르소나 생성 및 조회 테스트.
    """
    
    # 1. 코치 생성 (auth_headers 사용)
    coach = create_test_coach(client, "PersonaCoach", headers=auth_headers)
    coach_id = coach["id"]

    # 2. 페르소나 생성
    persona_data = {
        "coach_id": coach_id,
        "name": "Friendly Persona",
        "description": "A friendly and supportive persona.",
        "system_prompt": "You are a friendly coach.",
        "is_active": True
    }
    
    # ⚠️ (C-3) /coach-personas/ API도 auth_headers를 사용해야 함
    # (다음 단계에서 이 라우트를 보호할 때, 이 테스트는 이미 준비됨)
    response = client.post("/api/v1/coach-personas/", json=persona_data, headers=auth_headers)
    
    # (참고: 'coach-personas' 라우트가 아직 보호되지 않았다면 이 테스트는 201을 기대합니다)
    assert response.status_code == 201, f"Persona creation failed: {response.json()}"
    data = response.json()
    assert data["name"] == "Friendly Persona"
    assert data["coach_id"] == coach_id