"""채팅 흐름 스모크 (2026-10-16 재작성).

구 버전은 모듈 수준 TestClient(startup 없음), 폐기된 코치 id(…0010), 실제 LLM 문구 단언으로 통과가 불가능했다.
지금은 conftest 의 client(startup)·seed_data(seed.py + companies G-TEST) 와 FM_LLM_STUB=1(LLM 미호출 정형 답변)로
로그인 → 세션 시작(현재 코치 id …0011) → 턴 2개 → 세션 provider 고정값까지 결정론적으로 확인한다.
"""
from fastapi.testclient import TestClient

TEMPLATE_ID = "10000000-0000-0000-0000-000000000008"   # seed.py 의 리더십 핵심 역량 진단 템플릿


def test_chat_flow_with_seed_data(client: TestClient, seed_data, monkeypatch):
    monkeypatch.setenv("FM_LLM_STUB", "1")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)

    # 1. 로그인 — G-TEST 는 companies 에 시드돼 있어 그룹코드 게이트를 통과한다.
    login = client.post("/api/v1/participants/token",
                        json={"email": "test@example.com", "password": "password", "name": "박기진", "group_code": "G-TEST"})
    assert login.status_code == 200, f"로그인 실패: {login.text}"
    participant_id = login.json()["participant_id"]
    hdr = {"Authorization": f"Bearer {login.json()['access_token']}"}  # (2026-10-29) 참여자 API 는 토큰 필수

    # 2. 세션 시작 — 코치 id 는 런타임 매핑(COACH_UUID_TO_KEY)에서 가져온다(키 '1' = …0011).
    from diag_project.routes.diagnoses import COACH_UUID_TO_KEY
    coach_uuid = {v: k for k, v in COACH_UUID_TO_KEY.items()}["1"]
    assert coach_uuid.endswith("0011")
    start = client.post("/api/v1/diagnoses/start", json={
        "coach_id": coach_uuid, "participant_id": participant_id,
        "template_id": TEMPLATE_ID, "force_new": True,
    }, headers=hdr)
    assert start.status_code == 201, f"진단 생성 실패: {start.text}"
    data = start.json()
    session_id = data["session_id"]
    assert data["coach_response_message"].strip(), "첫 인사가 비어 있다"

    # 3. 턴 2개 — 라포 첫 턴은 템플릿, 이후 LLM 턴은 FM_LLM_STUB 정형 답변. 오류 턴이 아니어야 한다.
    for content in ("안녕하세요, 저는 박기진입니다.", "요즘은 팀 리딩과 신규 사업 검토가 제 주요 업무입니다."):
        r = client.post("/api/v1/diagnoses/submit_message",
                        json={"session_id": session_id, "diagnosis_id": session_id, "content": content}, headers=hdr)
        assert r.status_code in (200, 201), f"메시지 전송 실패: {r.text}"
        body = r.json()
        assert body.get("llm_error") is not True, body
        assert body["coach_response_message"].strip()

    # 4. 세션에 LLM provider 가 고정됐다(고객사 값 없음 → 환경 기본값 claude, 2026-10-29).
    import uuid
    from diag_project.database import async_session
    from diag_project.models.diagnosis_session import DiagnosisSession

    async def _load():
        async with async_session() as db:
            return await db.get(DiagnosisSession, uuid.UUID(session_id))

    session = client.portal.call(_load)
    assert session is not None
    assert session.llm_provider == "claude"
    assert session.status == "in_progress"
