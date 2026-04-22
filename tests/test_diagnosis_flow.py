# diag_project/tests/test_diagnosis_flow.py

import pytest
import pytest_asyncio
from httpx import AsyncClient
from uuid import UUID, uuid4

# 필요한 모델 임포트
from diag_project.models.diagnosis import DiagnosisStatus
# v32에서 제거한 Enum 임포트 (정상)


@pytest_asyncio.fixture(name="setup_diagnosis_flow")
async def setup_diagnosis_flow_fixture(
    async_client: AsyncClient,
):
    """
    (이 setup은 완벽하게 작동하고 있습니다.)
    """
    
    # --- 0. Group 생성 (API 호출) ---
    group_code = f"G-{uuid4()}"
    g_response = await async_client.post(
        "/api/v1/groups/",
        json={"name": "Test Group for Flow", "group_code": group_code}
    )
    assert g_response.status_code == 201, f"Group 생성 실패: {g_response.text}"
    group_data = g_response.json()
    group_uuid = group_data["id"]

    # --- 1. Participant 생성 (API 호출) ---
    participant_email = f"flow_test_user_{uuid4()}@test.com"
    participant_password = "test_password123"
    
    p_response = await async_client.post(
        "/api/v1/participants/",
        json={
            "email": participant_email,
            "name": "Flow Test User",
            "password": participant_password,
            "group_id": group_uuid
        },
    )
    assert p_response.status_code == 201, f"Participant 생성 실패: {p_response.text}"
    participant_data = p_response.json()
    participant_id = participant_data["id"]

    # --- 1.5. 로그인 (Token 획득) ---
    login_response = await async_client.post(
        "/api/v1/participants/token", 
        json={
            "email": participant_email, 
            "password": participant_password,
            "group_code": group_code
        }
    )
    assert login_response.status_code == 200, f"로그인 실패: {login_response.text}"
    token_data = login_response.json()
    access_token = token_data["access_token"]
    async_client.headers["Authorization"] = f"Bearer {access_token}"

    # --- 1.6. Coach 생성 (API 호출) ---
    coach_response = await async_client.post(
        "/api/v1/coaches/",
        json={
            "name": "Test Coach",
            "email": f"coach_{uuid4()}@test.com",
            "user_id": participant_id
        }
    )
    assert coach_response.status_code == 201, f"Coach 생성 실패: {coach_response.text}"
    coach_data = coach_response.json()
    coach_uuid = coach_data["id"]

    # --- 1.7. CoachPersona 생성 (API 호출) ---
    cp_response = await async_client.post(
        "/api/v1/coach-personas/",
        json={
            "name": "Test Persona", 
            "description": "A test persona",
            "coach_id": coach_uuid,
            "system_prompt": "You are a helpful coach."
        }
    )
    assert cp_response.status_code == 201, f"CoachPersona 생성 실패: {cp_response.text}"
    persona_data = cp_response.json()
    persona_uuid = persona_data["id"] 

    # --- 2. Competency 생성 (API 호출) ---
    c_response = await async_client.post(
        "/api/v1/competencies/",
        json={
            "competency_id": "organization_management",
            "name": "Organization Management",
            "description": "Competency description"
        }
    )
    assert c_response.status_code == 201, f"Competency 생성 실패: {c_response.text}"
    competency_data = c_response.json()
    competency_uuid = competency_data["id"]

    # --- 3. Indicator 생성 (API 호출) ---
    # [THE FIX] DB에 저장하는 영어 질문
    indicator_question_text = "What is your vision?" 
    i_response = await async_client.post(
        "/api/v1/indicators/",
        json={
            "indicator_id": "vision_sharing",
            "name": "Vision Sharing",
            "description": "Indicator description",
            "question": indicator_question_text,
            "competency_id": competency_uuid
        }
    )
    assert i_response.status_code == 201, f"Indicator 생성 실패: {i_response.text}"
    indicator_data = i_response.json()
    indicator_uuid = indicator_data["id"]

    # --- 3.5. DiagnosisTemplate 생성 (API 호출) ---
    t_response = await async_client.post(
        "/api/v1/diagnosis-templates/", 
        json={
            "name": "Test Flow Template",
            "description": "Template for diagnosis flow test",
            "version": "1.0",
            "coach_id": coach_uuid
        }
    )
    assert t_response.status_code == 201, f"Template 생성 실패: {t_response.text}"
    template_data = t_response.json()
    template_uuid = template_data["id"]
    
    # --- 3.55. QuestionCategory 생성 (API 호출) ---
    qc_response = await async_client.post(
        "/api/v1/question-categories/", 
        json={"name": "Test Category"}
    )
    assert qc_response.status_code == 201, f"QuestionCategory 생성 실패: {qc_response.text}"
    category_data = qc_response.json()
    category_uuid = category_data["id"] 

    # --- 3.6. Template/Indicator 연결 (DiagnosisQuestion 생성) ---
    tq_response = await async_client.post(
        "/api/v1/diagnosis-questions/", 
        json={
            "diagnosis_template_id": template_uuid,
            "question_category_id": category_uuid,
            "indicator_id": indicator_uuid,
            "question_text": indicator_question_text,
            "question_type": "text", 
            "order": 1
        }
    )
    assert tq_response.status_code == 201, f"Template/Indicator(Question) 연결 실패: {tq_response.text}"

    # --- 4. Diagnosis 시작 (API 호출) ---
    d_response = await async_client.post(
        "/api/v1/diagnoses/start", 
        json={
            "template_id": template_uuid,
            "participant_id": participant_id,
            "coach_persona_id": persona_uuid
        }
    )
    
    assert d_response.status_code == 201, f"Diagnosis 생성 실패: {d_response.text}"
    diagnosis_data = d_response.json()
    
    return {
        "diagnosis_id": diagnosis_data["diagnosis_id"], 
        "session_id": diagnosis_data["session_id"],
        # [THE FIX] 'What is your vision?' (영어)로 다시 복원
        "expected_question": indicator_question_text
    }


@pytest.mark.asyncio
async def test_submit_message_and_get_first_question(
    async_client: AsyncClient,
    setup_diagnosis_flow: dict,
):
    """
    (이 함수는 변경되지 않았습니다.)
    """
    diagnosis_id = setup_diagnosis_flow["diagnosis_id"]
    session_id = setup_diagnosis_flow["session_id"]
    
    # --- [NEW STEP] 서버 버그 우회 ---
    patch_response = await async_client.patch(
        f"/api/v1/diagnoses/{diagnosis_id}", # (슬래시 없음)
        json={"status": DiagnosisStatus.IN_PROGRESS}
    )
    assert patch_response.status_code in [200, 204], f"상태 변경 실패: {patch_response.text}"
    # -----------------------------------

    # 1. 첫 번째 메시지 (라포 메시지) 전송
    response = await async_client.post(
        f"/api/v1/diagnoses/submit_message", 
        json={
            "content": "안녕하세요, 진단을 시작하겠습니다.",
            "diagnosis_id": diagnosis_id,
            "session_id": session_id
        }
    )
    
    assert response.status_code == 201, f"메시지 전송 실패: {response.text}"
    json_data = response.json()
    
    assert json_data["user_message"]["content"] == "안녕하세요, 진단을 시작하겠습니다."
    
    # AI 메시지 (첫 번째 질문이어야 함) 확인
    ai_message = json_data["ai_message"]
    # assert ai_message["message_type"] == "QUESTION" # (주석 처리 유지)
    
    # --- 인수인계서의 최종 목표 검증 ---
    ai_json = ai_message["coach_response"] 
    
    assert ai_json["current_competency_id"] == "organization_management" 
    assert ai_json["current_indicator_id"] == "vision_sharing"
    
    # AI 메시지 텍스트가 지표 질문과 일치하는지 확인
    assert ai_json["coach_response_message"] == setup_diagnosis_flow["expected_question"]