"""(2026-10-23 B) 운영 스모크 — 6명 코치 × 세션 시작 → 자가진단 → 라포 3턴 → 정의 → ALIGN 까지 실제 라우트를 FM_LLM_STUB 으로 호출.
어느 턴이든 500 이면 실패. 9fad8ae(라포 3턴 TypeError 500)가 이 테스트 없이 운영에 나갔다. CI(.github/workflows/tests.yml)에 포함.
"""
import uuid

import pytest
from fastapi.testclient import TestClient

TEMPLATE_ID = "10000000-0000-0000-0000-000000000008"
# 라포(3턴) → 기대 없음 → 안내 → 정의 → 확인 → ALIGN 을 밟는 리더 입력. 스텁 코치는 턴마다 다른 정형 문장을 낸다.
INPUTS = [
    "안녕하세요, 박기진입니다.",
    "바쁜 쪽이에요. 하반기 교육 일정이 몰려서요.",
    "교육팀 팀장이고 팀원은 5명, 교육 기획과 운영을 맡고 있습니다.",
    "아니요, 특별히 기대하는 건 없어요.",
    "네.",
    "조직관리는 방향을 세우고 구성원이 스스로 움직이게 하는 일이라고 생각합니다. 통제보다 환경을 만드는 쪽이요.",
    "네, 맞아요.",
    "네, 좋습니다.",
    "최근 평가 플랫폼을 도입할 때 팀원들이 반대해서 파일럿부터 돌렸습니다.",
    "네.",
]


def _instructions(client, session_id):
    from diag_project.database import async_session
    from diag_project.models.diagnosis_session import ChatMessage
    from sqlalchemy import select

    async def _q():
        async with async_session() as db:
            rows = (await db.execute(select(ChatMessage).where(ChatMessage.session_id == uuid.UUID(session_id))
                                     .order_by(ChatMessage.created_at.asc()))).scalars().all()
            return [(m.role, m.instruction_used, m.chapter) for m in rows]
    return client.portal.call(_q)


@pytest.mark.parametrize("coach_key", ["1", "2", "3", "4", "5", "6"])
def test_smoke_start_to_align_every_coach(client: TestClient, seed_data, monkeypatch, coach_key):
    monkeypatch.setenv("FM_LLM_STUB", "1")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    from diag_project.routes.diagnoses import COACH_UUID_TO_KEY
    coach_uuid = {v: k for k, v in COACH_UUID_TO_KEY.items()}[coach_key]

    login = client.post("/api/v1/participants/token", json={
        "email": f"smoke-{coach_key}-{uuid.uuid4().hex[:6]}@example.com", "password": "password",
        "name": "박기진", "group_code": "G-TEST"})
    assert login.status_code == 200, login.text
    pid = login.json()["participant_id"]

    start = client.post("/api/v1/diagnoses/start", json={
        "coach_id": coach_uuid, "participant_id": pid, "template_id": TEMPLATE_ID, "force_new": True})
    assert start.status_code == 201, start.text
    sid = start.json()["session_id"]

    se = client.patch(f"/api/v1/sessions/{sid}/self-eval", json={"scores": {
        "organization_management": 3.5, "performance_management": 3, "people_management": 4,
        "work_management": 2.5, "self_management": 3}})
    assert se.status_code == 200, se.text

    reached = False
    for i, content in enumerate(INPUTS, 1):
        r = client.post("/api/v1/diagnoses/submit_message",
                        json={"session_id": sid, "diagnosis_id": sid, "content": content})
        assert r.status_code < 500, f"코치 {coach_key} 턴 {i} HTTP {r.status_code}: {r.text[:300]}"
        assert r.status_code in (200, 201), f"코치 {coach_key} 턴 {i} HTTP {r.status_code}: {r.text[:300]}"
        body = r.json()
        assert body.get("llm_error") is not True, body
        assert (body.get("coach_response_message") or "").strip(), f"턴 {i} 빈 응답"
        instrs = [ins for role, ins, _ in _instructions(client, sid) if role == "model"]
        if "COMPETENCY_ALIGN" in instrs:
            reached = True
            break
    instrs = [ins for role, ins, _ in _instructions(client, sid) if role == "model"]
    assert reached, f"코치 {coach_key}: {len(INPUTS)}턴 안에 COMPETENCY_ALIGN 도달 못함 — {instrs}"
    # 라포 3턴(역할 질문 턴 포함)이 실제로 지나갔다 — 9fad8ae 는 여기서 500 이었다.
    assert any(ins and ins.startswith("RAPPORT") for ins in instrs) or len(instrs) >= 3, instrs
