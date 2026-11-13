"""(2026-11-04 BEI 1단계) 스텁 스모크 — 6명 코치 × 조직관리 1챕터를 실제 라우트(FM_LLM_STUB=1: 코치·슬롯 판정·매핑 전부 스텁)로 완주한다.

시뮬 리더(tools/sim_leader.Leader, stub 모드)가 고정 설정(교육팀장·사례 6개)으로 답한다. 어느 턴이든 500 이면 실패.
확인: ALIGN → 사례 2개(6슬롯 종료) → SWEEP 2개(사례 1 다시 꺼냄·남은 사례) → CHAPTER_READY_TO_END, 챕터 리더 턴 ≤ 예산(16), covered 4/4(스텁 매핑은 여는 하위역량만 strong).
CI(.github/workflows/tests.yml)에 포함된다.
"""
import asyncio
import uuid

import pytest
from fastapi.testclient import TestClient

TEMPLATE_ID = "10000000-0000-0000-0000-000000000008"
CH = "organization_management"


def _store(client, session_id):
    from diag_project.database import async_session
    from diag_project.models.diagnosis_session import ChatMessage, DiagnosisSession
    from sqlalchemy import select

    async def _q():
        async with async_session() as db:
            sess = await db.get(DiagnosisSession, uuid.UUID(session_id))
            rows = (await db.execute(select(ChatMessage).where(ChatMessage.session_id == uuid.UUID(session_id))
                                     .order_by(ChatMessage.created_at.asc()))).scalars().all()
            return dict(sess.self_assessment_data or {}), [(m.role, m.instruction_used, m.chapter, m.content) for m in rows]
    return client.portal.call(_q)


@pytest.mark.parametrize("coach_key", ["1", "2", "3", "4", "5", "6"])
def test_bei_chapter_one_every_coach_stub(client: TestClient, seed_data, monkeypatch, coach_key):
    monkeypatch.setenv("FM_LLM_STUB", "1")
    monkeypatch.setenv("FM_PREWARM", "0")   # 챕터 종료 사전분석(Sonnet) 호출 금지
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    from diag_project.routes.diagnoses import COACH_UUID_TO_KEY
    from diag_project.services import bei_engine as B
    from tools.sim_leader import ONBOARDING, Leader, _load_profile
    from pathlib import Path
    coach_uuid = {v: k for k, v in COACH_UUID_TO_KEY.items()}[coach_key]
    profile = _load_profile(str(Path(__file__).resolve().parents[1] / "tools/sim_profiles/edu_team_lead.json"))
    leader = Leader(profile, stub=True, provider="claude")

    login = client.post("/api/v1/participants/token", json={
        "email": f"bei-{coach_key}-{uuid.uuid4().hex[:6]}@example.com", "password": "password", "name": "박기진", "group_code": "G-TEST"})
    assert login.status_code == 200, login.text
    pid = login.json()["participant_id"]
    hdr = {"Authorization": f"Bearer {login.json()['access_token']}"}
    start = client.post("/api/v1/diagnoses/start", json={"coach_id": coach_uuid, "participant_id": pid, "template_id": TEMPLATE_ID, "force_new": True}, headers=hdr)
    assert start.status_code == 201, start.text
    sid = start.json()["session_id"]
    coach_text = start.json().get("coach_response_message") or ""

    queue = list(ONBOARDING)
    meta: dict = {}
    reached_end = False
    # (2026-11-11 단계 표시) 도는 턴이 없으면 idle · 인증 없이는 볼 수 없다
    _ts = client.get(f"/api/v1/diagnoses/{sid}/turn_stage", headers=hdr)
    assert _ts.status_code == 200 and _ts.json() == {"stage": "idle", "label": "", "elapsed_s": 0.0}
    assert client.get(f"/api/v1/diagnoses/{sid}/turn_stage").status_code in (401, 403)
    for i in range(1, 45):
        u = queue.pop(0) if queue else asyncio.run(leader.answer(coach_text, chapter=meta.get("chapter"), instr=meta.get("instruction_used"),
                                                                 target_sub=meta.get("target"), bei_state=meta.get("bei_state"), probe=meta.get("probe_type_used"), bei=meta.get("bei")))
        r = client.post("/api/v1/diagnoses/submit_message", json={"session_id": sid, "diagnosis_id": sid, "content": u}, headers=hdr)
        assert r.status_code in (200, 201), f"코치 {coach_key} 턴 {i} HTTP {r.status_code}: {r.text[:300]}"
        body = r.json()
        assert body.get("llm_error") is not True, body
        coach_text = body.get("coach_response_message") or ""
        assert coach_text.strip(), f"턴 {i} 빈 응답"
        meta = body.get("_phase3a_metadata") or {}
        if body.get("is_topic_completed") and body.get("has_next_chapter"):
            reached_end = True
            break
    assert reached_end, f"코치 {coach_key}: 44턴 안에 조직관리를 닫지 못함 (마지막 meta={meta})"

    store, rows = _store(client, sid)
    instrs = [ins for role, ins, ch, _ in rows if role == "model"]
    # 종료 턴(CHAPTER_READY_TO_END)은 START_CHAPTER 표식 때문에 다음 챕터로 태깅된다 — 챕터 필터 없이 마지막 코치 턴을 본다
    assert "COMPETENCY_ALIGN" in instrs and "EPISODE_OPEN" in instrs and "SWEEP_ANCHOR" in instrs and instrs[-1] == "CHAPTER_READY_TO_END"
    assert B.chapter_state(store, CH) == "close"
    assert 1 <= B.bei_turns(store, CH) <= B.chapter_budget(CH)
    eps = [e for e in B.episodes(store, CH) if e.get("kind") == "episode"]
    assert len(eps) == 2 and all(e["status"] == "done" and len(B.filled_slots(e)) == 6 for e in eps), eps
    cov = B.coverage_summary(store, CH, [v["name"] for v in __import__("diag_project.data.competencies", fromlist=["COMPETENCY_FRAMEWORK"]).COMPETENCY_FRAMEWORK[CH]["indicators"].values()])
    # 사례 2개(비전·전략 여는 질문) + SWEEP 혁신은 남은 사례(E7). SWEEP 변화관리는 리더가 사례 1(E1)을 다시 꺼내 '같은 사례' 안내를 받는다.
    # (2026-11-12 P11-H) 그 뒤의 '네, 맞아요'는 받을 내용이 없는 답이라 리더 턴으로 세지 않고 질문만 다시 낸다(종전에는 이 답이 보완 1턴을 차지해
    #   뒤따른 같은 사례 반복이 보완 완료로 닫혔다). 리더가 같은 사례를 한 번 더 말하면 그 항목은 미확인으로 남는다 → 3/4 + 미확인 1.
    assert cov["covered"] == ["비전 제시 및 공유", "전략적 사고", "혁신적 사고"] and cov["not_explored"] == [] and cov["unconfirmed"] == ["변화관리(변화지향)"]
    _gl_p11 = [g for g in (store.get("guard_log") or []) if g.get("reask")]
    assert _gl_p11 and all(g.get("bei") == "reask" and g.get("slot_judge") is None for g in _gl_p11)   # 다시 묻기 턴은 슬롯 판정·리더 턴을 쓰지 않는다
    # 파생 원장: 분석이 읽는 asked_subs = covered ∪ SWEEP 앵커 하위역량
    assert set(store["asked_subs"][CH]) == {"비전 제시 및 공유", "전략적 사고", "변화관리(변화지향)", "혁신적 사고"}
    assert "SWEEP_FOLLOWUP" in instrs or "SWEEP_ANCHOR" in instrs
    # (2026-11-12 P11b-7) 보완 질문의 답이 실제 사례(E7)면 일반 사례로 올릴지(promoted)·예산이 모자라 종전대로 닫을지(no_budget)를 그 항목에 적는다.
    #   올렸으면 리더 턴 4 안에서 닫히고 닫힌 사유가 남는다. 미질문 예약은 침범하지 않는다(챕터 리더 턴 ≤ 예산은 위에서 확인).
    _sw_p = [e for e in B.episodes(store, CH) if e.get("kind") == "sweep" and e.get("promote")]
    assert _sw_p and all(e["promote"] in ("promoted", "no_budget") for e in _sw_p), B.episodes(store, CH)
    for e in _sw_p:
        if e["promote"] == "promoted":
            assert e["status"] == "sweep_done" and 2 <= int(e["leader_turns"]) <= B.SWEEP_PROMOTE_MAX_TURNS and e.get("promote_end"), e
        else:
            assert int(e["leader_turns"]) <= 2, e
    assert [g.get("sweep_promote") for g in (store.get("guard_log") or []) if g.get("sweep_promote")]
    # 사례 행(Event) 2건 — 분석 입력 '[수집된 핵심 사건]' 블록의 재료
    from diag_project.database import async_session
    from diag_project.models.event import Event
    from sqlalchemy import select

    async def _events():
        async with async_session() as db:
            return (await db.execute(select(Event).where(Event.session_id == uuid.UUID(sid)))).scalars().all()
    evs = client.portal.call(_events)
    assert len(evs) == 3 and all(e.situation and e.mapped_subcompetency for e in evs)   # 사례 2 + SWEEP 보완 1(변화관리는 미확인 — 위 P11-H 주석)
    # (2026-11-05 P4-1) 페르소나 슬롯은 챕터당 1회(Ella 없음) — 세션 원장 slot_chapters·slot_used_idx 에 기록, 문구 인덱스 = 챕터 순서(조직관리 0)
    slot_turns = [g for g in store.get("guard_log", []) if g.get("slot") and g.get("slot") != "Michael_q"]
    assert len(slot_turns) == (0 if coach_key == "1" else 1), [(g.get("episode"), g.get("slot")) for g in slot_turns]
    if coach_key != "1":
        assert store.get("slot_chapters") == {CH: 1} and store.get("slot_used_idx") == [0] and slot_turns[0].get("slot_idx") == 0
    # (P4-2) '좋습니다' 리드 0 · (P4-3) 흉터 0 · 여는 문장은 스텁 모드에서 사전 앵커(opener=stub)
    coach_texts = [c for role, ins, ch, c in rows if role == "model"]
    assert not any(c.lstrip().startswith("좋습니다") for c in coach_texts)
    from diag_project.services.output_guard import broken_statements
    from diag_project.services.intro_messages import all_fixed_sentences
    _fixed = {x.replace(" ", "") for x in all_fixed_sentences()}
    for c in coach_texts:
        assert not [b for b in broken_statements("\n".join(l for l in c.split("\n") if not l.strip().startswith("·"))) if b.replace(" ", "") not in _fixed], c
    assert {g.get("opener") for g in store["guard_log"] if g.get("instr") in ("COMPETENCY_ALIGN", "EPISODE_OPEN")} == {"bare"}      # (P12-6) 여는 문장은 질문만(사전 질문)
    # Michael 실행 의지 질문은 세션 누적(michael_q_count ≤ 3)
    if coach_key == "5":
        assert 0 <= int(store.get("michael_q_count") or 0) <= 3
