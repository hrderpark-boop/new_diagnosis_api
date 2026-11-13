"""P9 (2026-11-10, 운영 Jessica 11/10 검토) — 전수 질문 보장·스몰톡 시간대·내부 문구·닫는 턴·대상 없는 질문·말투·입버릇·휴식 제안·마지막 답 받기."""
import inspect
import random
from datetime import datetime, timedelta
from types import SimpleNamespace

from diag_project.data.competencies import COMPETENCY_FRAMEWORK
from diag_project.services import bei_engine as B


def _subs(ch):
    return [v["name"] for v in COMPETENCY_FRAMEWORK[ch]["indicators"].values()]


def _run_chapter(ch: str, rng: random.Random) -> dict:
    """엔진만으로 한 챕터를 끝까지 — 라우트의 전이 순서를 그대로 따른다(리더 답은 무작위: 사례 없음·진전 없음·슬롯 채움·매핑)."""
    subs = _subs(ch)
    st: dict = {}
    st, ep = B.new_episode(st, ch, B.pick_opener(st, ch, subs), "k")
    guard = 0
    while True:
        guard += 1
        assert guard < 200
        st, ep = B.record_leader_turn(st, ch, ep)
        nxt = None
        if ep["kind"] == "sweep":
            no_case = rng.random() < 0.5
            if no_case and ep["leader_turns"] <= 1:
                st = B.close_episode(st, ch, ep, "no_case", [], subs); st = B.mark_unconfirmed(st, ch, ep["opener_sub"]); nxt = "plan"
            elif ep["leader_turns"] == 1 and B.sweep_followup_allowed(st, ch, subs, ep):
                continue
            else:
                lab = [{"sub": ep["opener_sub"], "strength": rng.choice(["strong", "weak"]), "quote": "q"}] if rng.random() < 0.6 else []
                st = B.close_episode(st, ch, ep, "sweep_done", lab, subs); nxt = "plan"
        else:
            no_case = rng.random() < 0.3 and not B.filled_slots(ep)
            if not no_case and rng.random() < 0.7:
                k = next((k for k in B.SLOT_KEYS if ep["slots"][k]["status"] != "filled"), None)
                if k:
                    ep["slots"][k] = {"status": "filled", "quote": "q"}
            st = B.update_episode(st, ch, ep)
            reason = B.episode_done_reason(ep, st, ch, subs)
            if no_case:
                if ep.get("retry", 0) < B.EPISODE_RETRY_MAX and ep["leader_turns"] <= 2 and reason is None:
                    ep["retry"] = 1; st = B.update_episode(st, ch, ep); continue
                st = B.close_episode(st, ch, ep, "no_case", [], subs); st = B.mark_no_case(st, ch, ep["opener_sub"]); nxt = "plan"
            elif reason:
                labs = [{"sub": s, "strength": rng.choice(["strong", "weak"]), "quote": "q"} for s in rng.sample(subs, k=min(len(subs), rng.randint(0, 3)))]
                st = B.close_episode(st, ch, ep, "done" if reason == "slots" else reason, labs, subs); nxt = "plan"
            else:
                continue
        plan = B.plan_after_episode(st, ch, subs)
        if plan == B.STATE_EPISODE:
            sub = B.pick_opener(st, ch, subs)
            if sub:
                st, ep = B.new_episode(st, ch, sub, "k"); continue
            plan = B.STATE_SWEEP
        if plan == B.STATE_SWEEP:
            sub = B.sweep_target(st, ch, subs)
            if sub:
                st, ep = B.new_episode(st, ch, sub, "k", kind="sweep"); continue
        return st


def test_p9_1_completed_chapter_has_no_unasked_sub():
    """완주 챕터에서 unasked 1.0 = 0 — 어떤 답 흐름에서도 모든 하위역량을 한 번은 묻고 닫는다(5챕터 × 200회 무작위)."""
    rng = random.Random(1110)
    worst = {}
    for ch in [k for k in COMPETENCY_FRAMEWORK if k != "supplementary"]:
        subs = _subs(ch)
        for _ in range(200):
            st = _run_chapter(ch, rng)
            assert B.unasked(st, ch, subs) == [], (ch, B.unasked(st, ch, subs))
            assert B.coverage_summary(st, ch, subs)["not_explored"] == []
            worst[ch] = max(worst.get(ch, 0), B.bei_turns(st, ch))
    # 예약 덕분에 예산을 넘는 턴은 남은 미질문을 한 턴씩 묻는 경우뿐 — 넘더라도 하위역량 수 이내
    for ch, w in worst.items():
        assert w <= B.chapter_budget(ch) + len(_subs(ch)), (ch, w)


def test_p9_1_reserve_closes_episode_and_people_budget():
    ch = "people_management"; subs = _subs(ch)
    assert B.chapter_budget(ch) == 24 and B.episode_max(ch) == 2 and B.SWEEP_MAX_PER_CHAPTER is None
    st, ep = B.new_episode({}, ch, subs[0], "k")
    st["bei_turns"] = {ch: 24 - 16}                     # (P12-3) 남은 16턴 = 미질문 8개 × 2턴 → 예약 침범
    ep = dict(ep, leader_turns=3)
    assert B.unasked(st, ch, subs) == subs[1:] and B.episode_done_reason(ep, st, ch, subs) == "reserve"
    st["bei_turns"] = {ch: 24 - 17}
    assert B.episode_done_reason(ep, st, ch, subs) is None
    assert B.episode_turn_max(len(subs)) == 6 and B.episode_turn_max(5) == 6      # (P12b-2) 전 영역 사례 최대 6턴
    assert B.episode_done_reason(dict(ep, leader_turns=6), st, ch, subs) == "turns"
    # 사람관리는 사례 2개까지 — 2개를 들은 뒤에는 예산이 넉넉해도 SWEEP
    st2: dict = {}
    for i in range(2):
        st2, e = B.new_episode(st2, ch, subs[i], "k")
        st2 = B.close_episode(st2, ch, dict(e, leader_turns=5), "done", [{"sub": subs[i], "strength": "strong", "quote": "q"}], subs)
    st2["bei_turns"] = {ch: 8}
    assert B.plan_after_episode(st2, ch, subs) == "sweep"


def test_p9_2_smalltalk_time_guard_and_guide():
    from diag_project.prompts.phase3a.layer3_state import _build_rapport_guide
    from diag_project.services.output_guard import mentions_future_daypart
    from diag_project.services.time_greeting import current_daypart
    assert mentions_future_daypart("오전과 오후 중 어느 쪽이 더 바쁘셨어요?", "오전") == ["오후"]
    assert mentions_future_daypart("오전과 오후 중 어느 쪽이 더 바쁘셨어요?", "저녁") == []
    assert mentions_future_daypart("점심은 드셨어요?", "오전 마무리") == ["점심"] and mentions_future_daypart("오전은 어떠셨어요?", "오후") == []
    assert current_daypart(datetime(2026, 11, 10, 9, 30)) == "오전"
    g = _build_rapport_guide({"forced_rapport_category": "스몰톡", "current_daypart": "오전"})
    assert "지금은 '오전'입니다" in g and "오후" in g and "질문형으로만" in g
    src = inspect.getsource(__import__("diag_project.routes.diagnoses", fromlist=["x"]))
    assert "mentions_future_daypart" in src and "smalltalk_time" in src


def test_p9_3_internal_phrases_are_leaks_and_sources_removed():
    from diag_project.prompts.phase3a import layer1_system, layer3_state
    from diag_project.services.leak_lexicon import find_state_report
    for s in ("그럼 영역 도입 질문을 드리겠습니다.", "이번 역량에서는 사례를 두 가지 듣겠습니다.", "이번 교육에서는 편하게 말씀해 주시면 됩니다.",
              "사례를 세 가지 정도 여쭙겠습니다."):
        assert find_state_report(s), s
    assert not find_state_report("분기 초에 목표를 팀 회의에서 공유하셨습니다.")
    assert "영역 도입" not in inspect.getsource(layer3_state) and "사례 2~3개" not in inspect.getsource(layer1_system)


def test_p9_4_close_side_keeps_one_receive_statement():
    from diag_project.services.output_guard import clean_close_side, close_side_violation
    body = ("이대리 반응이 뚜렷하게 남아 있지 않으셨습니다. 그 대화에서 무엇을 기대하셨는지 여쭙고 싶습니다. 그때 기준을 먼저 말했다면 결과가 달랐을 것입니다. "
            "다음에는 기준을 먼저 정해 보시면 좋겠습니다. 어떤 점이 궁금합니다.")
    out, n = clean_close_side(body, max_statements=1)
    assert out == "이대리 반응이 뚜렷하게 남아 있지 않으셨습니다." and n == 4
    for bad in ("그 부분이 궁금합니다.", "어떻게 하셨습니까?", "미리 알렸다면 덜 흔들렸을 텐데요.", "한 번 더 물어보시길 권합니다."):
        assert close_side_violation(bad), bad
    assert close_side_violation("같은 자리에서 최운영 씨가 어떤 표정이었는지, 혹은 다른 분들이 무엇을 말했는지 기억나는 대로 짚어 주시면 됩니다.")   # p9a 사람관리
    assert not close_side_violation("그 자리에서 전에 틀렸던 판단을 먼저 인정하셨다는 점도 기록해 두겠습니다.")
    anchor = "이번에는 일을 맡기는 쪽 이야기입니다. 최근에 직접 하고 싶은 일을 팀원에게 맡기신 적 있으셨습니까?"
    full, _ = clean_close_side("납기를 두 번 놓친 뒤 따로 부르셨습니다. 그 뒤가 궁금합니다. " + anchor, max_statements=1,
                               keep=["이번에는 일을 맡기는 쪽 이야기입니다.", "최근에 직접 하고 싶은 일을 팀원에게 맡기신 적 있으셨습니까?"])
    assert full == "납기를 두 번 놓친 뒤 따로 부르셨습니다. " + anchor


def test_p9_5_question_without_referent_detected_and_assembled():
    from diag_project.services.output_guard import attach_referent, question_lacks_referent
    user = "둘을 따로 불러서 얘기를 들었고요, 그 다음에 분담표를 다시 짰어요."
    assert question_lacks_referent("달라진 부분이 있었는지 궁금합니다.", [user])
    assert question_lacks_referent("그 뒤로 달라진 점이 있었습니까?", [user])
    assert not question_lacks_referent("분담표를 다시 짠 뒤 두 사람은 어떻게 받아들였습니까?", [user])
    assert not question_lacks_referent("그 자리에서 리더님이 처음 꺼낸 말은 무엇이었고 팀원들은 그 말을 어떻게 받았는지 기억나십니까?", [user])
    fixed = attach_referent("달라진 부분이 있었는지 궁금합니다.", user)
    assert fixed == "달라진 부분이 있었는지 궁금합니다."          # (P12-1) 명사구 머리(''분담표'와 관련해')는 붙이지 않는다 — 겹치는 낱말이 없으면 다시 쓴다(8-w4b)


def test_p9_6_register_per_persona():
    from diag_project.services import intro_messages as IM
    from diag_project.services.persona_register import apply_register, register_violations
    out, n, left = apply_register("Jessica", "팀 목표를 어떻게 나누시는지 듣고 싶어요. 최근에 목표를 같이 정하신 일이 있으셨어요? 회의로 꽉 찬 오전이셨군요. 그렇게 읽히네요.")
    # (승인 조건 1) '~군요/~네요' 받는 문장은 Jessica 도 그대로 — 고치는 것은 해요체 질문과 (scope="all" 일 때) 그 밖의 해요체 평서문
    assert left == [] and n == 2 and out == "팀 목표를 어떻게 나누시는지 듣고 싶습니다. 최근에 목표를 같이 정하신 일이 있으셨습니까? 회의로 꽉 찬 오전이셨군요. 그렇게 읽히네요."
    q_only = apply_register("Jessica", "두 분을 따로 부르셨어요. 그 자리에서 무엇을 먼저 말씀하셨어요?", scope="questions")
    assert q_only == ("두 분을 따로 부르셨어요. 그 자리에서 무엇을 먼저 말씀하셨습니까?", 1, [])          # 받는 문장은 손대지 않는다
    assert apply_register("Daniel", "그렇게 풀어가셨군요. 그때 기준이 뭐였어요?", scope="questions")[0] == "그렇게 풀어가셨군요. 그때 기준이 뭐였습니까?"
    assert apply_register("Jessica", "네, 알겠어요. 안내드릴게요.", scope="questions", fixed=["안내드릴게요."])[0] == "네, 알겠어요. 안내드리겠습니다."
    assert apply_register("Jessica", "목표를 어떻게 정하고 점검하셨는지 함께 짚어볼 거예요.")[0] == "목표를 어떻게 정하고 점검하셨는지 함께 짚어보겠습니다."
    assert apply_register("Ella", "최근에 실수를 바로 알리신 일이 있으셨습니까?")[0] == "최근에 실수를 바로 알리신 일이 있으셨어요?"
    assert register_violations("Daniel", "그렇게 풀어가셨군요. 그 기준이 무엇이었는지요?") == [] and register_violations("Lucas", "조치는 들었고요, 결과는요?") == []
    # 고정 문장은 어느 페르소나도 자기 말투 규칙에 걸리지 않는다(6명 전부)
    import re
    for pk, lines in IM.PERSONA_LINES.items():
        for k, v in lines.items():
            v2 = re.sub(r"'[^']*'", "''", re.sub(r"\{[^}]*\}", "가나", v))
            assert register_violations(pk, v2) == [], (pk, k, v)
    for pk in IM.PERSONA_LINES:      # 범위 문장 폴백도 교정 뒤 위반 0
        for ch in IM.CHAPTER_SCOPE_LINES:
            assert apply_register(pk, IM.chapter_scope_line(ch))[2] == [], (pk, ch)
    from diag_project.data.coaches_persona import COACHES_PERSONA
    jes = next(v for v in COACHES_PERSONA.values() if "Jessica" in v["name"])["system_prompt"]
    assert "질문은 '~습니까'로만 끝낸다" in jes and "/어땠어요'" not in jes and "확인하셨죠?" not in jes and "있었나요?'" not in jes


def test_p9_7_phrase_caps_and_opener_frames():
    from diag_project.services.anchor_render import OPENER_FRAME_EXAMPLES, OPENER_FRAMES
    from diag_project.services.phrase_caps import count_phrases, enforce_phrase_caps
    assert len(OPENER_FRAMES) == 5 and len(OPENER_FRAME_EXAMPLES) == 5 and not any("살펴보려" in x for x in OPENER_FRAME_EXAMPLES)   # (P11-F) 5종
    t = "목표를 어떻게 나누셨는지 살펴보려고 합니다. 그 기준을 말씀해 주시겠습니까?"
    assert enforce_phrase_caps(t, session_texts=["살펴보려고 합니다."], chapter_texts=["말씀해 주시겠습니까?"]) == (t, {})
    out, done = enforce_phrase_caps(t, session_texts=["살펴보려고 합니다. 살펴보려고 해요."], chapter_texts=["말씀해 주시겠습니까? 말씀해 주시겠습니까?"])
    _cp = count_phrases([out])
    assert done == {"salpyeo": 1} and _cp["salpyeo"] == 0 and _cp["malsseum"] == 1 and "짚어 주십시오" not in out   # (P11c-5) '말씀해 주시겠습니까?' 는 상한을 넘어도 바꾸지 않는다(원문 유지)
    src = inspect.getsource(__import__("diag_project.routes.diagnoses", fromlist=["x"]))
    assert "enforce_phrase_caps" in src and 'return fallback_q, "bare"' in src      # (P12-6) 여는 문장은 질문만


def test_p9_8_pause_only_after_case_close_40min_then_30min():
    from diag_project.services.event_tracker import should_suggest_pause, sitting_start_index, sitting_stats
    ok = dict(instruction_used="EPISODE_OPEN", case_closed=True)
    assert should_suggest_pause(elapsed_min=14, minutes_since_last_suggest=None, **ok) is False        # 11/10: 14분째 제안은 이제 없다
    assert should_suggest_pause(elapsed_min=41, minutes_since_last_suggest=None, **ok) is True
    assert should_suggest_pause(elapsed_min=60, minutes_since_last_suggest=19, **ok) is False
    assert should_suggest_pause(elapsed_min=71, minutes_since_last_suggest=30, **ok) is True
    assert should_suggest_pause(elapsed_min=90, minutes_since_last_suggest=None, instruction_used="EPISODE_PROBE", case_closed=False) is False   # 사례 도중 금지
    assert should_suggest_pause(elapsed_min=90, minutes_since_last_suggest=None, instruction_used="EPISODE_OPEN", case_closed=False) is False
    assert "sitting_messages" not in inspect.signature(should_suggest_pause).parameters                 # 턴 수 기준 폐지
    t0 = datetime(2026, 11, 10, 9, 0)
    msgs = [SimpleNamespace(created_at=t0 + timedelta(minutes=m), instruction_used=i) for m, i in
            ((0, None), (20, "EPISODE_PROBE"), (41, "USER_REQUESTS_PAUSE"), (50, None), (55, "EPISODE_PROBE"))]
    i = sitting_start_index(msgs)
    assert i == 3                                                                                        # '다음에 하기' 뒤 재개한 첫 메시지부터
    assert sitting_stats([m.created_at for m in msgs[i:]], now=t0 + timedelta(minutes=60))[0] == 10.0


def test_p9_9_summary_material_includes_sweep_answers_and_last_receive_wired():
    from diag_project.prompts.phase3a.layer3_state import _get_instruction_guide
    from diag_project.services.close_render import clean_close_summary
    g = _get_instruction_guide("CHAPTER_READY_TO_END", {"chapter": "performance_management", "bei_close_episodes": [
        {"idx": 1, "kind": "episode", "context": "분기 초에 절감 목표가 내려왔어요", "action": "품목별로 나눠 맡을 걸 정했어요", "result": ""},
        {"idx": 1, "kind": "sweep", "context": "", "action": "늦은 이유를 먼저 물어봤어요", "result": ""},
        {"idx": 2, "kind": "sweep", "context": "", "action": "중간에 한 번 알려 달라고 했어요", "result": ""},
        {"idx": 3, "kind": "sweep", "context": "", "action": "주간 회의에서 숫자를 같이 봤어요", "result": ""}]})
    # (p9c) 재료에 '사례'·'보완 답' 꼬리표를 붙이지 않는다 — 꼬리표를 되읊는 문장이 나왔다
    assert "행동 '늦은 이유를 먼저 물어봤어요'" in g and "합쳐서 2~3문장으로" in g and "보완 답" not in g
    assert len([x for x in clean_close_summary("가. 나. 다. 라. 마.", 5).split(". ") if x]) == 3
    src = inspect.getsource(__import__("diag_project.routes.diagnoses", fromlist=["x"]))
    assert "render_last_receive" in src and '"sweep_done")' in src and "final_receive" in src


def test_p9_followups_from_first_sim():
    """p9a 1차 시뮬에서 본 것 — '~죠'·'~텐데요'·청유 '~볼까요?' 도 합쇼체로 / 범위 문장 예시는 진단과 무관한 분야 / 대상 있는 질문은 건드리지 않는다."""
    from diag_project.prompts.phase3a import layer3_state
    from diag_project.services.output_guard import question_lacks_referent
    from diag_project.services.persona_register import apply_register
    assert apply_register("Jessica", "네, 하반기에 교육 일정이 몰리면 시간 쓰는 방식이 자연스럽게 정해지죠.", scope="questions")[1] == 0   # 받는 문장은 범위 밖
    assert apply_register("Jessica", "네, 하반기에 교육 일정이 몰리면 시간 쓰는 방식이 자연스럽게 정해지죠.") == (
        "네, 하반기에 교육 일정이 몰리면 시간 쓰는 방식이 자연스럽게 정해집니다.", 1, [])
    assert apply_register("Jessica", "교육 기획과 운영을 함께 맡으시는군요, 팀원 네 분과 함께 움직이는 자리일 텐데요.")[2] == []
    assert apply_register("Jessica", "그럼 시작해볼까요?")[0] == "그럼 시작하겠습니다."
    assert "시간과 자원을 어떻게 나눠 쓰셨는지" not in inspect.getsource(layer3_state)
    assert not question_lacks_referent("그 전환을 리더님께서 어떻게 확인하셨습니까?", ["이기획이 멘토를 맡겠다고 먼저 나섰습니다."])
    src = inspect.getsource(__import__("diag_project.routes.diagnoses", fromlist=["x"]))
    assert "_trimmed_w3" in src and "_areg_first" in src


def test_p9_followups_from_second_sim():
    """p9b 2차 시뮬에서 본 것 — 해라체·전언 꼴 여는 문장 / 잘린 요약 꼬리 / 영역 첫 턴의 허위 귀속 / 스몰톡 되물음의 목표 질문."""
    from diag_project.services.anchor_render import OPENER_FRAMES, _frame_example
    from diag_project.services.close_render import clean_close_summary
    from diag_project.services.output_guard import drop_unfinished_tail, smalltalk_followup_ok, strip_false_attribution
    from diag_project.services.persona_register import apply_register, register_violations
    assert apply_register("Jessica", "업무를 조직의 목표와 어떻게 이어 붙이는지는 리더마다, 팀마다 꽤 다르다.")[0].endswith("꽤 다릅니다.")
    assert apply_register("Jessica", "팀마다, 사람마다 목표를 나누는 방식은 조금씩 다르더랍니다.")[0].endswith("조금씩 다릅니다.")
    assert register_violations("Ella", "일을 어디까지 맡길지는 리더마다 선이 다르다.") and apply_register("Jessica", "그것이 문제다.")[2] == ["그것이 문제다."]
    # (2026-11-11 P10-3·4) 틀 설명은 어미를 싣지 않고(합쇼체 틀을 해요체 코치가 베꼈다), 채움 문장 틀은 삭제 — 예시는 코치 말투로 바꿔 준다
    assert not any(("다릅니다" in f or "입니다" in f or "습니다" in f) for f in OPENER_FRAMES) and "마다" not in _frame_example("Jessica", 2)
    assert register_violations("Jessica", _frame_example("Jessica", 0), scope="strict") == [] and register_violations("Ella", _frame_example("Ella", 1), scope="strict") == []
    assert _frame_example("Jessica", 2).endswith("있으셨습니까?") and "관한 것입니다. " in _frame_example("Jessica", 2) and "건데요" not in _frame_example("Jessica", 2)   # (P11d-4)
    cut = "합동 리뷰를 만드셨고, 같은 문제로 회의가 없었습니다. 같은 해 7월 신규 리더십 과정 운영"
    assert drop_unfinished_tail(cut) == ("합동 리뷰를 만드셨고, 같은 문제로 회의가 없었습니다.", 1) and "과정 운영" not in clean_close_summary(cut, 3)
    assert drop_unfinished_tail("끝난 문장입니다.") == ("끝난 문장입니다.", 0)
    out, removed = strip_false_attribution("목표를 어떻게 세우셨는지 짚어보겠습니다. 방금 말씀하신 '기준'과 이어서 여쭙니다. '성과관리'는 무엇이라고 보십니까?", "네, 다음으로 이어가 주세요.")
    assert removed == ["기준"] and "말씀하신" not in out and out.endswith("무엇이라고 보십니까?")
    assert not smalltalk_followup_ok("그 와중에 팀 목표는 어떻게 맞춰가고 계십니까?")


def test_p9_conditional_approval_items():
    """P9 조건부 승인 4건 — 점검표 문장 누설 / 누구의 반응인지 없는 질문 / ALIGN 받기 폴백은 정의 구절 인용."""
    from diag_project.prompts.phase3a.episode_card import build_episode_card
    from diag_project.services import bei_engine as B
    from diag_project.services.align_render import definition_quote, render_align
    from diag_project.services.leak_lexicon import find_state_report
    from diag_project.services.output_guard import attach_referent, key_person, question_lacks_referent
    # 2. 점검표 문장
    for s in ("이 사례에서 아직 여쭙지 않은 부분은 상대 반응입니다.", "이 사례에서 아직 여쭙지 않은 것은 리더님께서 지금 돌아보실 때의 판단입니다.",
              "이 사례에서 다음으로 여쭙겠습니다."):
        assert find_state_report(s), s
    assert not find_state_report("6월부터 공통 교안으로 나갔고 같은 문제로 회의가 열리지 않았습니다.")
    st, ep = B.new_episode({}, "people_management", "갈등관리", "conflict_management")
    card = build_episode_card(instruction="EPISODE_PROBE", chapter="people_management", ep=dict(ep, leader_turns=2), bei_turns=2, budget=24)
    assert "리더에게 말하지 않는다" in card and "여쭙지 않은" not in card            # 금지 예문을 지시문에 쓰지 않는다(베낀다)
    # 3. 누구의 반응·태도·표정·변화인지 없는 질문 → 직전 답의 인물을 붙인다
    user = "하루를 비워서 두 분을 한자리에 앉혔어요. 각자 양보 못 할 항목을 세 개씩만 적어 보게 했고, 나머지는 제가 정했습니다."
    q = "말이나 표정, 이후 태도 변화 중 기억에 남는 것을 말씀해 주십시오."
    assert question_lacks_referent(q, [user]) and key_person(user) == "두 분"
    assert attach_referent(q, user) == "두 분의 말이나 표정, 이후 태도 변화 중 기억에 남는 것을 말씀해 주십시오."
    assert not question_lacks_referent(attach_referent(q, user), [user])
    assert not question_lacks_referent("그 제안을 받은 박선임 님의 반응은 어땠습니까?", [user])
    assert key_person("박선임 님은 그럼 그렇게 하죠 하고 받아들였어요.") == "박선임 님" and attach_referent("반응은 어땠습니까?", "그날 바로 보고했습니다.").startswith("상대분의 ")
    # 4. ALIGN 받기 폴백 — 낱말 하나가 아니라 정의 구절
    assert definition_quote("people_management", "사람관리는 한 사람 한 사람의 상태를 알고 맞춰 주는 일 같아요.") == "한 사람 한 사람의 상태를 알고 맞춰 주는 일"
    assert definition_quote("performance_management", "성과관리는 목표를 같이 정하고 중간에 점검해서 끝까지 가게 하는 일이라고 봐요.") == "목표를 같이 정하고 중간에 점검해서 끝까지 가게 하는 일"
    assert definition_quote("organization_management", "소통이요.") == "" and definition_quote("organization_management", "네") == ""
    assert definition_quote("organization_management", "조직관리는 방향 정하기입니다.") == "방향 정하기"          # 4어절 미만이어도 정의 한 줄은 그대로 받는다
    out = render_align(llm_text="", chapter="people_management", sub_names=["갈등관리"], persona_name="Jessica (제시카)", anchor="최근에 그런 일이 있으셨습니까?",
                       user_text="사람관리는 한 사람 한 사람의 상태를 알고 맞춰 주는 일 같아요.")
    assert out.startswith("'한 사람 한 사람의 상태를 알고 맞춰 주는 일'이라고 보시는군요.") and "중심에 두고" not in out


def test_p9_followups_from_confirm_sim():
    """p9c 확인 시뮬에서 본 것 — 종료 요약의 지시문 되읊기·해석 한 줄 / 여는 턴·영역 첫 턴의 허위 귀속 / 늦은 시간 인사."""
    from datetime import datetime as _dt
    from diag_project.services.close_render import clean_close_summary
    from diag_project.services.leak_lexicon import find_state_report
    from diag_project.services.output_guard import drop_summary_noise, strip_false_attribution
    from diag_project.services.time_greeting import get_time_greeting
    meta = ("3번째 재료는 사례가 아니라 보완 답의 중복 문장이라 별도 사례로 쓰지 않고, 보완 답의 행동 내용을 한 문장에 묶었습니다. 재료에 없는 사실은 더하지 않았습니다. "
            "작년 3월 개편 지시 때 두 분을 따로 불러 이유부터 들으셨고, 파일럿 만족도가 높게 나와 하반기 전체 개편으로 이어졌습니다.")
    out, n = drop_summary_noise(meta)
    assert n == 2 and out.startswith("작년 3월 개편 지시 때") and "재료" not in clean_close_summary(meta, 3)
    assert find_state_report("3번째 재료는 사례가 아니라 보완 답의 중복 문장입니다.") and find_state_report("재료에 없는 사실은 더하지 않았습니다.")
    assert drop_summary_noise("이기획 님이 먼저 멘토를 맡겠다고 나섰다는 건 리더님이 길러 두신 역량이 팀으로 번진 장면으로 보입니다.") == ("", 1)
    assert drop_summary_noise("표로 정리해 가져가셨고, 이후 납기를 한 번도 놓치지 않았습니다.")[1] == 0
    u1 = "자료 지연이 거의 사라졌고, 하반기엔 강사 둘이 운영 개선안을 먼저 들고 왔습니다."
    o1, r1 = strip_false_attribution("기준이 스스로 돌아가기 시작했다는 뜻이군요. 방금 말씀하신 '기준'과 이어서 여쭙니다. 개인 사정으로 힘든 팀원을 배려하신 적, 근래에 있습니까?", u1)
    assert r1 == ["기준"] and "말씀하신" not in o1
    o2, r2 = strip_false_attribution("딱히 떠오르는 일이 없으시다면 그대로 넘어가겠습니다. 방금 말씀하신 '기준'과 연결해 여쭙니다. 잘하는 팀원에게 어려운 일을 맡기신 적 있습니까?", "딱히 그런 일은 없었던 것 같아요.")
    assert r2 == ["기준"] and "연결해" not in o2
    o3, r3 = strip_false_attribution("네, 사람관리 영역으로 넘어가겠습니다. 방금 말씀하신 '일정표를 다시 짜 팀에 공유하셨다'는 대목과 이어서, 사람을 움직이신 방식을 짚어보려 합니다.", "네, 다음으로 이어가 주세요.")
    assert len(r3) == 1 and o3 == "네, 사람관리 영역으로 넘어가겠습니다. 사람을 움직이신 방식을 짚어보려 합니다."
    q = get_time_greeting(_dt(2026, 11, 10, 23, 40))["greeting_question"]
    assert "시간 시간" not in q and q.endswith("?")
    src = inspect.getsource(__import__("diag_project.routes.diagnoses", fromlist=["x"]))
    assert "_is_probe or _is_open or instruction_used == \"COMPETENCY_ASK\"" in src and "_uniq_m" in src
