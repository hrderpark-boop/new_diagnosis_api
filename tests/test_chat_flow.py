# tests/test_chat_flow.py

from fastapi.testclient import TestClient
from diag_project.main import app

client = TestClient(app)

def test_chat_flow_with_seed_data():
    print("\n🚀 [테스트 시작] 시드 데이터 기반 채팅 흐름 점검")

    # 1. 로그인 (seed.py에 있는 계정 사용)
    login_payload = {
        "email": "test@example.com",
        "password": "password123",
        "group_code": "G-TEST"
    }
    login_res = client.post("/api/v1/participants/token", json=login_payload)
    assert login_res.status_code == 200, f"로그인 실패: {login_res.text}"
    print("✅ 1. 로그인 성공")

    # 2. Ella 코치로 진단 시작 (seed.py에 있는 ID 사용)
    # Ella ID: ...10 / Persona ID: ...110
    start_payload = {
        "coach_id": "10000000-0000-0000-0000-000000000010", 
        "participant_id": "10000000-0000-0000-0000-000000000002",
        "template_id": "10000000-0000-0000-0000-000000000008",
        "coach_persona_id": "10000000-0000-0000-0000-000000000110"
    }
    
    start_res = client.post("/api/v1/diagnoses/start", json=start_payload)
    assert start_res.status_code == 201, f"진단 생성 실패: {start_res.text}"
    
    data = start_res.json()
    diagnosis_id = data["diagnosis_id"]
    session_id = data["session_id"]
    message = data["coach_response_message"]
    
    print(f"✅ 2. 진단 세션 생성 성공 (ID: {diagnosis_id})")
    print(f"📝 [Ella의 첫 인사]: {message}")

    # [검증] 우리가 llm_service.py에 하드코딩한 멘트가 맞는지 확인
    assert "Ella" in message or "엘라" in message
    assert "실례가 안된다면" in message # 우리가 수정한 멘트 특징
    print("✅ 3. 첫인사 멘트 검증 완료")

    # 3. 사용자 답변 전송 (이름 말하기)
    chat_payload = {
        "session_id": session_id,
        "diagnosis_id": diagnosis_id,
        "content": "안녕하세요, 저는 박기진입니다."
    }
    
    chat_res = client.post("/api/v1/diagnoses/submit_message", json=chat_payload)
    assert chat_res.status_code == 201, f"메시지 전송 실패: {chat_res.text}"
    
    chat_data = chat_res.json()
    ai_reply = chat_data["coach_response_message"]
    
    print(f"📝 [AI 답변]: {ai_reply}")
    
    # [검증] AI가 이름을 인식하고 반갑다고 하는지 확인
    assert "박기진" in ai_reply or "기진" in ai_reply
    assert "반가워요" in ai_reply or "반갑습니다" in ai_reply
    print("✅ 4. AI 답변 로직 검증 완료 (이름 인식 성공)")