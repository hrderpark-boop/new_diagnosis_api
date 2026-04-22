# tests/test_diagnosis_setup.py

import pytest
from fastapi.testclient import TestClient
from uuid import UUID, uuid4

# ==========================================================
# 헬퍼 함수 (Helper Functions)
# ==========================================================

def create_test_coach(client: TestClient, suffix: str = "", headers: dict = None) -> dict:
    """(Helper) 테스트용 코치를 생성합니다."""
    user_uuid = str(uuid4())
    coach_data = {
        "name": f"Test Coach {suffix}", "description": "A coach for testing purposes.",
        "avatar_url": "http://example.com/avatar.jpg", "character_tags": "friendly, supportive",
        "user_id": user_uuid, "email": f"test_coach_{user_uuid}@test.com"
    }
    response = client.post("/api/v1/coaches/", json=coach_data, headers=headers)
    assert response.status_code == 201, f"Helper (Coach) creation failed: {response.json()}"
    return response.json()

def create_test_template(client: TestClient, coach_id: str, suffix: str = "", headers: dict = None) -> dict:
    """(Helper) 테스트용 진단 템플릿을 생성합니다."""
    template_data = {
        "name": f"Test Template {suffix}",
        "description": "Template for testing",
        "version": "1.0",
        "coach_id": coach_id
    }
    response = client.post("/api/v1/diagnosis-templates/", json=template_data, headers=headers)
    assert response.status_code == 201, f"Helper (Template) creation failed: {response.json()}"
    return response.json()

# ⚠️ (C-3/Missing) 1. 카테고리 생성 헬퍼 추가
def create_test_category(client: TestClient, suffix: str = "", headers: dict = None) -> dict:
    """(Helper) 테스트용 질문 카테고리를 생성합니다."""
    category_data = {
        "name": f"Test Category {suffix}",
        "description": "Category for testing"
    }
    # (참고: 이 API도 나중에 보호해야 함)
    response = client.post("/api/v1/question-categories/", json=category_data, headers=headers)
    assert response.status_code == 201, f"Helper (Category) creation failed: {response.json()}"
    return response.json()

# ⚠️ (C-3/Missing) 2. category_id를 인자로 받도록 헬퍼 수정
def create_test_question(client: TestClient, template_id: str, category_id: str, suffix: str = "", headers: dict = None) -> dict:
    """(Helper) 테스트용 질문을 생성합니다."""
    question_data = {
        "diagnosis_template_id": template_id,
        "question_text": f"Test Question {suffix}?",
        "question_type": "multiple_choice",
        "order_num": 1,
        "question_category_id": category_id # 👈 3. 누락된 필드 추가
    }
    response = client.post("/api/v1/diagnosis-questions/", json=question_data, headers=headers)
    assert response.status_code == 201, f"Helper (Question) creation failed: {response.json()}"
    return response.json()

def create_test_choice(client: TestClient, question_id: str, suffix: str = "", headers: dict = None) -> dict:
    """(Helper) 테스트용 선택지를 생성합니다."""
    choice_data = {
        "diagnosis_question_id": question_id,
        "choice_text": f"Test Choice {suffix}",
        "score": 1.0,
        "order_num": 1
    }
    response = client.post("/api/v1/question-choices/", json=choice_data, headers=headers)
    assert response.status_code == 201, f"Helper (Choice) creation failed: {response.json()}"
    return response.json()

# ==========================================================
# Fixture
# ==========================================================

@pytest.fixture(scope="function")
def setup_data(client: TestClient, auth_headers: dict):
    """테스트 모듈에서 사용할 기본 데이터를 생성합니다."""
    
    coach = create_test_coach(client, "Setup", headers=auth_headers)
    
    # ⚠️ 4. (C-3/Missing) Fixture에서 카테고리 생성
    category = create_test_category(client, "Setup", headers=auth_headers)
    
    template = create_test_template(client, coach["id"], "Setup", headers=auth_headers)
    
    # ⚠️ 5. (C-3/Missing) 질문 생성 시 category_id 전달
    question = create_test_question(client, template["id"], category["id"], "Setup", headers=auth_headers)
    
    choice = create_test_choice(client, question["id"], "Setup", headers=auth_headers)

    return {
        "coach": coach,
        "template": template,
        "question": question,
        "choice": choice,
        "auth_headers": auth_headers 
    }

# ==========================================================
# 진단 설정(Diagnosis Setup) 테스트
# ==========================================================

def test_create_and_read_template(client: TestClient, setup_data: dict):
    """(C/R) 진단 템플릿 생성 및 조회 테스트"""
    headers = setup_data["auth_headers"]
    template_id = setup_data["template"]["id"]
    
    response = client.get(f"/api/v1/diagnosis-templates/{template_id}", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["name"] == setup_data["template"]["name"]

def test_read_templates(client: TestClient, setup_data: dict):
    """(R) 모든 진단 템플릿 조회 테스트"""
    headers = setup_data["auth_headers"]
    response = client.get("/api/v1/diagnosis-templates/", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data["items"], list)
    assert len(data["items"]) > 0

def test_create_and_read_question(client: TestClient, setup_data: dict):
    """(C/R) 진단 질문 생성 및 조회 테스트"""
    headers = setup_data["auth_headers"]
    question_id = setup_data["question"]["id"]

    response = client.get(f"/api/v1/diagnosis-questions/{question_id}", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["question_text"] == setup_data["question"]["question_text"]

def test_read_questions_by_template(client: TestClient, setup_data: dict):
    """(R) 템플릿 ID로 질문 목록 조회 테스트"""
    headers = setup_data["auth_headers"]
    template_id = setup_data["template"]["id"]

    response = client.get(f"/api/v1/diagnosis-templates/{template_id}/questions", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0
    assert data[0]["id"] == setup_data["question"]["id"]

def test_create_and_read_choice(client: TestClient, setup_data: dict):
    """(C/R) 질문 선택지 생성 및 조회 테스트"""
    headers = setup_data["auth_headers"]
    choice_id = setup_data["choice"]["id"]
    
    response = client.get(f"/api/v1/question-choices/{choice_id}", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert data["choice_text"] == setup_data["choice"]["choice_text"]

def test_read_choices_by_question(client: TestClient, setup_data: dict):
    """(R) 질문 ID로 선택지 목록 조회 테스트"""
    headers = setup_data["auth_headers"]
    question_id = setup_data["question"]["id"]

    response = client.get(f"/api/v1/diagnosis-questions/{question_id}/choices", headers=headers)
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) > 0
    assert data[0]["id"] == setup_data["choice"]["id"]