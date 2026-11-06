"""(2026-11-06 P7) 사례 없는 리더 대응 + 전수 탐색 보장 — 11/6 Ella 운영 세션(미탐색 14/26) 원인 교정.
  P7-1 사례 유무를 사례 열기 전에(incident) · 2턴 연속 진전 없음 조기 종료 · NO_CASE_REFRAME
  P7-2 리포트에 '미탐색' 없음 — 26칸 전부 점수(1.0 '사례 미확인'), 추천 카드 재료에서 제외
  P7-3 그만하겠다 → 안내 한 줄 + 선택(이어서/지금 마치기), /finish 로 completed
  P7-4 정의 질문 5틀 · P7-5 밀어붙이는 되받기 금지
"""
import uuid

from diag_project.services import bei_engine as B

CH = "organization_management"
SUBS = ["비전 제시 및 공유", "전략적 사고", "변화관리(변화지향)", "혁신적 사고"]


def _slots(**kw):
    out = {k: {"status": "empty", "quote": ""} for k in B.SLOT_KEYS}
    for k, (st, q) in kw.items():
        out[k] = {"status": st, "quote": q}
    return out


def test_p7_1_incident_in_schema_and_stub():
    from diag_project.llm_schemas import slot_judge_schema
    from diag_project.services.slot_judge import _stub_slots
    assert "incident" in slot_judge_schema()["properties"]
    j = _stub_slots([("model", "여는 질문"), ("user", "딱히 그런 일은 없었어요.")], None)
    assert j["no_case"] is True and j["incident"] is False
    j2 = _stub_slots([("model", "여는 질문"), ("user", "작년 3월에 개편 지시가 내려왔을 때 두 강사가 반대했어요.")], None)
    assert j2["incident"] is True


def test_p7_1_stall_closes_episode_before_eight_turns():
    st, ep = B.new_episode({}, CH, SUBS[0], "vision_sharing")
    ep["slots"] = _slots(context=("filled", "작년 3월"))
    ep["leader_turns"] = 2
    # 진전 없는 턴 2번 → stall 2 → 'stalled'
    ep = B.update_stall(ep, filled_before=1); assert ep["stall"] == 1
    assert B.episode_done_reason(ep, st, CH) is None
    ep = B.update_stall(ep, filled_before=1); assert ep["stall"] == 2
    assert B.episode_done_reason(ep, st, CH) == "stalled"
    # 진전이 있으면 0 으로
    ep["slots"] = _slots(context=("filled", "작년 3월"), action=("filled", "따로 불렀어요"))
    ep = B.update_stall(ep, filled_before=1); assert ep["stall"] == 0
    # 슬롯이 하나도 없으면 stalled 로 닫지 않는다(그 경우는 no_case 경로)
    ep0 = dict(ep, slots=_slots(), stall=3)
    assert B.episode_done_reason(ep0, st, CH) is None
    # stalled 사례도 사례 수에 든다
    st = B.close_episode(st, CH, dict(ep, status="open"), "stalled", [{"sub": SUBS[0], "strength": "strong", "quote": "따로 불렀어요"}], SUBS)
    assert B.counted_episodes(st, CH) == 1 and B.EPISODE_STALL_TURNS == 2
    assert "NO_CASE_REFRAME" in B.BEI_INSTRUCTIONS and "EPISODE_RETRY" not in B.BEI_INSTRUCTIONS


def test_p7_1_route_wiring_and_guides():
    import inspect
    from diag_project.routes import diagnoses as d
    from diag_project.prompts.phase3a.episode_card import BEI_GUIDES, TURN_FORMAT_RULES
    src = inspect.getsource(d._submit_message_phase3a)
    assert '_jd.get("incident") is False' in src and 'instruction_used = "NO_CASE_REFRAME"' in src and "_bei.update_stall(_ep, _filled_before)" in src
    assert "\"EPISODE_RETRY\"" not in src   # 상수 EPISODE_RETRY_MAX 는 남는다
    g = BEI_GUIDES["NO_CASE_REFRAME"]
    assert "작은 일이어도 됩니다" in g and "추궁은 금지" in g and "진짜 기억이 없으신가요" in g
    assert "밀어붙이지 않는다" in TURN_FORMAT_RULES


def test_p7_5_pushy_receive_is_state_leak():
    from diag_project.services.output_guard import find_state_leak, strip_state_leak
    txt = "그 부분은 마음에 걸려요. 진짜 기억이 없으신가요? 그럼 다른 장면으로 가 볼게요."
    hits = find_state_leak(txt)
    assert any("마음에 걸려요" in h for h in hits) and any("진짜 기억이" in h for h in hits)
    out, n = strip_state_leak("솔직히 말씀하신 건지 궁금하네요. 그럼 최근 회의 장면 하나만 들려주세요.")
    assert n == 1 and out.strip().startswith("그럼 최근 회의")


def test_p7_2_recommender_skips_unconfirmed_cells():
    from diag_project.services.course_recommender import _flatten_measured
    det = {CH: {"sub_ledger": {
        "비전 제시 및 공유": {"measured": True, "score": 2.0, "evidence": ["x"]},
        "전략적 사고": {"measured": True, "score": 1.0, "unconfirmed": True, "unconfirmed_kind": "not_explored", "evidence": []},
        "혁신적 사고": {"measured": True, "score": 1.0, "unconfirmed": True, "unconfirmed_kind": "no_case", "evidence": []},
    }}}
    assert [m["sub_name"] for m in _flatten_measured(det)] == ["비전 제시 및 공유"]


def _participant_session(client):
    from diag_project.database import async_session
    from diag_project.models.diagnosis_session import DiagnosisSession
    from diag_project.models.participant import Participant
    from diag_project.services.participant_auth import create_participant_token
    ELLA = uuid.UUID("00000000-0000-0000-0000-000000000011")

    async def _mk():
        async with async_session() as db:
            p = Participant(email=f"p7-{uuid.uuid4().hex[:8]}@test.local", name="마침")
            db.add(p); await db.flush()
            s = DiagnosisSession(user_id=p.id, coach_id=ELLA, status="in_progress", current_topic="성과관리",
                                 self_assessment_data={"pending_instruction": {"kind": "user_pause", "question": "q?"}})
            db.add(s); await db.commit()
            return str(p.id), str(s.id)
    pid, sid = client.portal.call(_mk)
    return pid, sid, {"Authorization": f"Bearer {create_participant_token(pid)}"}


def test_p7_3_finish_endpoint_marks_completed(client):
    pid, sid, hdr = _participant_session(client)
    assert client.post(f"/api/v1/diagnoses/{sid}/finish").status_code == 401
    r = client.post(f"/api/v1/diagnoses/{sid}/finish", headers=hdr)
    assert r.status_code == 200 and r.json()["finished_early"] is True
    st = client.get(f"/api/v1/diagnoses/{sid}/state", headers=hdr).json()
    assert st["status"] == "completed" and st["is_completed"] is True and st["needs_user_decision"] is False
    # 다시 부르면 already
    assert client.post(f"/api/v1/diagnoses/{sid}/finish", headers=hdr).json().get("already") is True
    # 다른 참여자는 403
    _, _, hdr2 = _participant_session(client)
    assert client.post(f"/api/v1/diagnoses/{sid}/finish", headers=hdr2).status_code == 403


def test_p7_3_finish_choice_line_and_route_wiring():
    import inspect
    from diag_project.services.intro_messages import FINISH_CHOICE_LINE, finish_choice_line
    from diag_project.routes import diagnoses as d
    from diag_project.prompts.phase3a.layer3_state import _get_instruction_guide
    assert finish_choice_line("Michael") == FINISH_CHOICE_LINE == "남은 항목은 이어서 하시면 채워지고, 지금 마치면 최저 수준으로 기록됩니다. 이어서 할까요, 마칠까요?"
    src = inspect.getsource(d._submit_message_phase3a)
    assert '_decision_kind = "finish_or_continue"' in src and '"kind": "user_pause"' in src and '"decision_kind": _decision_kind' in src
    assert "_user_pause_resume" in src and "continue_ack" in src
    g = _get_instruction_guide("USER_REQUESTS_PAUSE", {"chapter": CH})
    assert "받아들이는 평서문 1문장" in g and "[SESSION_PAUSE]" not in g


def test_p7_sweep_cap_ignores_no_case_and_repeat_no_case_not_duplicate():
    from diag_project.services import input_anomaly as IA
    st: dict = {"bei_turns": {"people_management": 10}, "covered": {"people_management": {"갈등관리": [{"episode": 1}]}}}
    subs = ["갈등관리", "신뢰형성", "팀워크 촉진(협업)", "코칭 및 피드백", "권한위임", "동기부여", "공감(감성지능)", "의사소통", "인재육성"]
    opened = []
    for i in range(8):
        t = B.sweep_target(st, "people_management", subs)
        if t is None:
            break
        st, ep = B.new_episode(st, "people_management", t, t, kind="sweep")
        st = B.close_episode(st, "people_management", ep, "no_case" if i < 6 else "sweep_done", [], subs)
        if i < 6:
            st = B.mark_unconfirmed(st, "people_management", t)
        opened.append(t)
    assert len(opened) == 8                                   # no_case 1턴짜리는 상한에 안 센다 → 8개 전부 물었다
    assert B.sweep_count(st, "people_management") == 2        # 사례를 찾은 보완만 센다
    # '없어요' 반복은 중복 입력이 아니다(사례 단계로)
    a = IA.detect(user_text="딱히 그런 일은 없었던 것 같아요.", prev_user_text="딱히 그런 일은 없었던 것 같아요.", earlier_user_texts=["딱히 그런 일은 없었던 것 같아요."],
                  prev_coach_text="최근에 그런 일이 있으셨어요?", prev_instruction="EPISODE_OPEN", event_texts=[], pause_pending=False, awaiting_choice=False, definition_reasked=False)
    assert a is None
    b = IA.detect(user_text="두 사람을 따로 불러서 이유를 들었어요.", prev_user_text="두 사람을 따로 불러서 이유를 들었어요.", earlier_user_texts=[],
                  prev_coach_text="그 뒤에는요?", prev_instruction="EPISODE_PROBE", event_texts=[], pause_pending=False, awaiting_choice=False, definition_reasked=False)
    assert b is not None and b.kind == "repeat_prev"
    import inspect
    from diag_project.routes import diagnoses as d
    assert "_quote_required = not (_bei.is_no_case_text(_llm_user_text)" in inspect.getsource(d._submit_message_phase3a)


def test_p7_5_false_attribution_clause_removed_but_real_quote_kept():
    """(P7-5) '방금 말씀하신 '피드백'과도 닿아 있는데요,' — 리더가 '피드백'을 말하지 않았으면 절 삭제, 실제 말('평소대로')은 보존."""
    from diag_project.services.output_guard import strip_false_attribution
    user = "그쪽은 기억이 잘 안 나요."
    txt = ("그렇게 기억이 흐릿한 쪽도 있으시죠, 리더님. 방금 말씀하신 '피드백'과도 닿아 있는데요, 그래도 최근에 팀원과 짧게라도 나눈 대화 중에 "
           "무언가 하나 떠오르는 장면이 있으실까요?")
    out, removed = strip_false_attribution(txt, user)
    assert removed == ["피드백"]
    assert "말씀하신" not in out and "'피드백'" not in out
    assert out.startswith("그렇게 기억이 흐릿한 쪽도 있으시죠, 리더님. 그래도 최근에")
    assert out.endswith("있으실까요?")
    # 리더가 실제로 한 말은 그대로
    user2 = "보통은 그냥 평소대로 하는 편이라서요. 딱히 떠오르는 일은 없네요."
    txt2 = "방금 말씀하신 '평소대로'와도 이어지는데요, 그 평소의 방식은 어떤 모습이었을까요?"
    out2, removed2 = strip_false_attribution(txt2, user2)
    assert removed2 == [] and out2 == txt2
    # 라우트 배선: 사례 턴(_is_probe)에서 8-y 앞에 적용
    import pathlib
    src = pathlib.Path("diag_project/routes/diagnoses.py").read_text()
    assert "strip_false_attribution" in src and src.index("strip_false_attribution") < src.index("# 8-y.")


def test_p7_close_no_case_fixed_line_per_persona_and_wiring():
    """(P7 승인 조건 2) 사례 0 챕터 종료: 다리만 남기지 않고 페르소나별 고정 1문장 + 다리."""
    import pathlib
    from diag_project.services.intro_messages import PERSONA_LINES, close_no_case_line, chapter_end_bridge
    from diag_project.services.leak_lexicon import find_leaks, find_state_report
    from diag_project.services.output_guard import find_state_leak, find_praise, has_question
    assert close_no_case_line("Ella") == "이 영역은 오늘 떠오르는 장면이 많지 않으셨네요. 그것도 그대로 기록할게요."
    for pk in PERSONA_LINES:
        line = close_no_case_line(pk)
        assert line and not has_question(line) and not find_praise(line), pk
        assert not find_leaks(line) and not find_state_report(line) and not find_state_leak(line), pk
        wrap = f"{line} {chapter_end_bridge('성과관리', pk)}"
        assert "'성과관리'" in wrap
    src = pathlib.Path("diag_project/routes/diagnoses.py").read_text()
    assert "close_no_case_line" in src and '"no_case_fixed"' in src


def test_p7_vague_repeat_is_not_duplicate_and_leak_stem():
    """(P7 p7c) '글쎄요, 그건 잘 모르겠어요' 반복은 '같은 사례' 중복이 아니다 / '마음에 걸리는 건' 도 추궁 문장."""
    from diag_project.services import input_anomaly as IA
    from diag_project.services.output_guard import find_state_leak
    v = "글쎄요, 그건 잘 모르겠어요. 그냥 평소대로 했던 것 같아요."
    a = IA.detect(user_text=v, prev_user_text=v, earlier_user_texts=[v, "네."], prev_coach_text="맡을 일을 정하는 기준은 무엇이었는지 궁금해요.",
                  prev_instruction="SWEEP_FOLLOWUP", event_texts=[], pause_pending=False, awaiting_choice=False, definition_reasked=False)
    assert a is None or a.kind not in ("repeat_prev", "repeat_any"), a
    assert find_state_leak("목표를 대충 맞추셨다는 말씀이 마음에 걸리는 건, 합의가 잘 보이지 않아서예요.")
