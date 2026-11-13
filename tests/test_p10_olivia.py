"""P10 — 운영 Olivia 완주(2026-11-11) 검토 반영.

P10-1 스몰톡: 내용 없는 답은 LLM 없이 고정 받기 + 예비 되물음(코치별 3종 × 시간대), LLM 은 1회만(재생성 없음), 누설 사전 기동 예열
P10-2 질문: 정의 질문 완결 문장 5종 / 슬롯 문장은 사례 내용을 넣어 쓴다(고정 문장 없음) / 15자 이하 대상 없는 질문에 대상 붙이기
P10-3 입버릇: '궁금' 챕터 1회 · 채움 문장 금지 · '이번에는 ~쪽 이야기' 세션 2회 · 여는 문장 틀에서 채움 문장 삭제
P10-4 말투: 여는 문장·범위 문장·다리는 코치 어미 강제(해요체 코치의 '~습니다' 포함), 받는 문장만 자유
P10-5 받기: 고정 받기 문구 전수 삭제, 폴백은 리더 절 인용, 마지막 답 받기는 인용 필수
P10-6 닫는 턴 누수: 요청형('조금 더 듣고 싶어요')·의문사 나열·평서문+물음표
P10-7 첫 영역 진입 다리(코치별 고정)
"""
import inspect
import re

from diag_project.services import intro_messages as IM

PERSONAS = ["Ella", "Jessica", "Olivia", "Daniel", "Michael", "Lucas"]
CASE = ["작년 하반기에 리더십 과정을 개편하면서 두 과정만 먼저 시범 운영을 해보자고 했어요. 강사들은 전면 도입을 원했고 팀원들도 일정이 밀린다고 반발했죠."]


def _route_src() -> str:
    return inspect.getsource(__import__("diag_project.routes.diagnoses", fromlist=["x"])._submit_message_phase3a)


# ── P10-1 ────────────────────────────────────────────────────────────────────────────────────────
def test_p10_1_contentless_smalltalk_answers_skip_llm():
    from diag_project.services.input_anomaly import is_contentless_smalltalk as f
    for t in ("그냥 그래요", "별로요", "네", "바쁜 쪽이에요.", "평소랑 비슷했어요, 딱히 특별한 건 없었고요", "뭐 그냥 그렇죠"):
        assert f(t), t
    for t in ("오늘은 회의가 많아서 정신없이 보냈어요", "하반기에 교육 일정이 몰려서 바쁘게 보내고 있어요.", "점심 먹고 산책 좀 했습니다"):
        assert not f(t), t


def test_p10_1_reserve_questions_three_per_coach_per_daypart_and_safe():
    from diag_project.services.output_guard import is_question, mentions_future_daypart, smalltalk_followup_ok
    groups = {"morning": ["오전", "오전 마무리"], "midday": ["점심", "오후"], "evening": ["저녁", "늦은 시간"]}
    for p in PERSONAS:
        assert set(IM.SMALLTALK_RESERVE[p]) == set(groups)
        for g, parts in groups.items():
            qs = IM.SMALLTALK_RESERVE[p][g]
            assert len(qs) == 3 == len(set(qs)), (p, g)
            for q in qs:
                assert q.endswith("?") and is_question(q) and smalltalk_followup_ok(q), (p, q)      # 질문형 · 일·역할을 묻지 않는다
                assert "," not in q and "아니면" not in q, (p, q)                                    # 둘 중 고르라는 꼴이 아니다
                for part in parts:
                    assert not mentions_future_daypart(q, part), (p, part, q)                        # 아직 오지 않은 시간대를 말하지 않는다
        assert IM.smalltalk_reserve_question(p, "오전", 0) != IM.smalltalk_reserve_question(p, "오전", 1)
        assert IM.smalltalk_flat_receive(p) and "?" not in IM.smalltalk_flat_receive(p)
    assert IM.smalltalk_reserve_question("Olivia (올리비아)", "저녁", 4) == IM.SMALLTALK_RESERVE["Olivia"]["evening"][1]
    assert IM.smalltalk_reserve_question("Olivia", None, 0) in IM.SMALLTALK_RESERVE["Olivia"]["evening"]


def test_p10_1_smalltalk_turn_wiring_one_llm_call_no_regen():
    src = _route_src()
    assert 'if _tm.get("no_regen") or _tm.get("budget_used"):' in src and '"regen_skipped"' in src   # 재생성 요청은 건너뛴다
    assert "is_contentless_smalltalk" in src and '_tm["smalltalk"] = "fixed"' in src              # 내용 없는 답 → LLM 없음
    assert '_tm["smalltalk"] = "reserve"' in src and "_smalltalk_reserve()" in src                # 검사 탈락 → 예비 되물음
    assert '_pl_r("smalltalk_q")' not in src                                                       # 옛 고정 질문(바쁜 쪽·여유 있는 쪽)은 쓰지 않는다
    i = src.index("if _smalltalk and _echoes(_recv, request.content):")
    assert "_timed_regen" not in src[i: src.index("elif _echoes(_recv, request.content):", i)]      # 스몰톡 되받기 반복은 재생성 없이 예비로
    main_src = inspect.getsource(__import__("diag_project.main", fromlist=["x"]).on_startup)
    assert "guard_lexicon" in main_src and "run_in_executor" in main_src                          # 누설 사전은 기동 때 예열(첫 LLM 턴이 1.9초를 치르지 않게)


# ── P10-2 ────────────────────────────────────────────────────────────────────────────────────────
def test_p10_2_definition_questions_are_complete_sentences():
    for p in PERSONAS:
        vs = IM.definition_question_variants("성과관리", p)
        assert len(vs) == 5 == len(set(vs)), p
        for v in vs:
            assert "'성과관리'" in v and v.endswith("?"), (p, v)
            assert not re.search(r"(풀면요|하면요|떠올라요|떠오르세요|떠오릅니까|한 문장으로)\??", v), (p, v)     # 폐기한 생략형
            assert len(v) >= 18, (p, v)
    assert IM.definition_question("조직관리", "Olivia", 0) == "'조직관리'를 리더님은 어떤 일이라고 생각하세요?"
    assert IM.definition_question("일관리", "Olivia", 3) == "리더님 팀에서 '일관리'가 잘 된다는 건 어떤 모습이라고 생각하세요?"   # 받침 조사 '가'
    assert IM.definition_question("사람관리", "Jessica", 2).endswith("말씀하시겠습니까?")
    from diag_project.services.persona_register import register_violations
    for p in ("Ella", "Olivia", "Michael", "Jessica", "Daniel"):
        for i in range(5):
            assert register_violations(p, IM.definition_question("조직관리", p, i), scope="strict") == [], (p, i)


def test_p10_2_slot_sentence_must_carry_case_words():
    from diag_project.services.slot_render import slot_sentence_ok as ok
    good = [("counterfactual", "시범 운영 없이 바로 전면 도입하셨다면 팀원들은 어떻게 움직였을까요?", "Olivia"),
            ("other_side", "전면 도입을 원했던 강사들 자리에서는 시범 운영 결정이 어떤 장면이었을까요?", "Olivia"),
            ("criterion", "전면 도입 대신 두 과정 시범 운영으로 정하실 때 무엇을 기준으로 삼으셨습니까?", "Jessica"),
            ("reason", "전면 도입 말고 시범 운영을 고른 이유, 한 줄로 하면 무엇입니까?", "Lucas"),
            ("cheer", "강사들 반발이 있는데도 시범 운영부터 가신 그 선택, 응원해요.", "Michael"),
            ("observation", "강사들과 팀원들 사이에서 시범 운영을 혼자 정해야 했던 자리, 가볍지 않으셨겠습니다.", "Daniel"),
            ("will", "다음에 또 과정을 개편하게 되면 시범 운영 전에 무엇부터 하시겠어요?", "Michael")]
    for kind, text, p in good:
        assert ok(kind, text, CASE, persona_name=p) == (True, ""), (kind, text)
    # 옛 고정 슬롯 문장은 전부 불합격 — 사례 낱말이 없다
    for kind, text, p in (("counterfactual", "반대로 하셨다면 어떻게 됐을까요?", "Olivia"), ("other_side", "그 팀원 입장에서는 어떤 장면이었을까요?", "Olivia"),
                          ("criterion", "그 결정의 기준은 무엇이었습니까?", "Jessica"), ("reason", "그 방법을 고른 이유, 한 줄로 하면요?", "Lucas"),
                          ("cheer", "그 선택, 응원합니다.", "Michael"), ("observation", "그 자리, 저도 압니다. 쉽지 않지요.", "Daniel"),
                          ("will", "다음에 비슷한 상황이 오면 어떻게 하실 생각이세요?", "Michael")):
        assert ok(kind, text, CASE, persona_name=p)[0] is False, text
    assert ok("criterion", "전면 도입 대신 시범 운영으로 정하실 때 뭘 기준으로 삼으셨어요?", CASE, persona_name="Jessica") == (False, "register")
    assert ok("counterfactual", "월세 대신 전세로 들어가셨다면 팀원들은 시범 운영을 어떻게 봤을까요?", CASE, persona_name="Olivia") == (False, "example_copied")
    assert ok("cheer", "강사들 반발에도 시범 운영부터 가신 건 정말 훌륭한 선택이라 응원해요.", CASE, persona_name="Michael")[1] == "praise_or_advice"
    assert ok("counterfactual", "시범 운영 없이 전면 도입하셨다면 팀원들은 어땠을까요? 강사들은요?", CASE, persona_name="Olivia")[0] is False     # 한 문장만
    used = ["시범 운영 없이 바로 전면 도입하셨다면 팀원들은 어떻게 움직였을까요?"]
    assert ok("counterfactual", used[0], CASE, persona_name="Olivia", used=used) == (False, "repeated")


def test_p10_2_slot_render_stub_and_wiring():
    import asyncio
    import os
    from diag_project.services.slot_render import render_slot
    old = os.environ.get("FM_LLM_STUB")
    os.environ["FM_LLM_STUB"] = "1"
    try:
        txt, mode = asyncio.run(render_slot(None, kind="criterion", persona_name="Jessica", transcript=[("model", "…"), ("user", CASE[0])]))
        assert mode == "stub" and txt and txt.endswith("?")
        assert asyncio.run(render_slot(None, kind="cheer", persona_name="Michael", transcript=[("user", "네")]))[0] is None
    finally:
        if old is None:
            os.environ.pop("FM_LLM_STUB", None)
        else:
            os.environ["FM_LLM_STUB"] = old
    assert asyncio.run(render_slot(None, kind="criterion", persona_name="Jessica", transcript=[("user", CASE[0])])) == (None, "miss:no_llm")   # LLM 없으면 넣지 않는다
    src = _route_src()
    assert "render_slot as _rsl" in src and 'kind="will"' in src and '"slot_texts"' in src
    for gone in ("PERSONA_SLOT_VARIANTS", "MICHAEL_WILL_QUESTIONS", "DANIEL_OBSERVATIONS", "slot_variants_for"):
        assert not hasattr(IM, gone) and gone not in src, gone


def test_p10_2_short_bare_probe_question_gets_referent():
    from diag_project.services.output_guard import attach_referent, is_short_bare_question as short
    ans = "지난달 주간 회의에서 박선임과 김책임 두 분이 일정 문제로 부딪혔어요. 제가 따로 불러서 분담표를 다시 짰습니다."
    assert short("그때 어떤 이야기가 오갔나요?", [ans]) and attach_referent("그때 어떤 이야기가 오갔나요?", ans) == "그때 두 분과 어떤 이야기가 오갔나요?"
    assert short("그 뒤에는 어떻게 됐나요?", [ans]) and attach_referent("그 뒤에는 어떻게 됐나요?", ans) == "그 뒤에는 어떻게 됐나요?"      # (P12-1) 명사구 머리는 붙이지 않는다
    assert not short("두 분은 뭐라고 하셨어요?", [ans])              # 사람을 가리킨다
    assert not short("분담표는 누가 짰나요?", [ans])                 # 리더가 쓴 낱말이 있다
    assert not short("그 회의가 끝난 뒤에 두 분이 일정표를 놓고 다시 이야기한 자리가 있었나요?", [ans])   # 15자 넘음
    src = _route_src()
    assert "is_short_bare_question as _isbq_w3" not in src and '"attached_short"' not in src      # (P12e-5) 사람·대상을 붙이던 수선(8-w3)은 삭제


# ── P10-3 ────────────────────────────────────────────────────────────────────────────────────────
def test_p10_3_phrase_caps_gunggeum_side_story_filler():
    from diag_project.services.phrase_caps import CAPS, enforce_phrase_caps as e, is_filler_sentence
    assert CAPS["gunggeum"] == ("chapter", 1) and CAPS["side_story"] == ("session", 2) and CAPS["filler"][0] == "ban"
    # 채움 문장은 처음부터 지운다
    out, done = e("그 일을 맡기셨군요. 일을 어디까지 맡길지는 팀마다, 사람마다 달라요. 최근에 새 일을 맡겨 보신 적 있으셨어요?", session_texts=[], chapter_texts=[])
    assert out == "그 일을 맡기셨군요. 최근에 새 일을 맡겨 보신 적 있으셨어요?" and done == {"filler": 1}
    assert is_filler_sentence("업무를 조직 목표와 어떻게 연결하는지는 리더마다, 팀마다 방식이 다릅니다.") and not is_filler_sentence("팀마다 일정이 달랐나요?")
    # '이번에는 ~쪽 이야기' — 세션 2회까지, 3회째 문장은 지운다(질문은 남는다)
    t = "이번에는 사람을 키우는 쪽 이야기예요. 최근에 팀원에게 새 일을 맡겨 보신 적 있으셨어요?"
    assert e(t, session_texts=["이번에는 일을 나누는 쪽 이야기예요."], chapter_texts=[]) == (t, {})
    assert e(t, session_texts=["이번에는 일을 나누는 쪽 이야기예요.", "이번엔 목표를 세우는 쪽 이야기입니다."], chapter_texts=[]) == (
        "최근에 팀원에게 새 일을 맡겨 보신 적 있으셨어요?", {"side_story": 1})
    # '궁금' — 챕터 1회. 2회째: 끝의 간접 질문은 묻는 꼴로 바꾸고, 뒤에 진짜 질문이 있으면 그 문장을 지운다
    assert e("강사 두 분이 반발하셨군요. 그때 두 분이 어떤 말을 했는지 궁금해요.", session_texts=[], chapter_texts=[])[1] == {}
    assert e("강사 두 분이 반발하셨군요. 그때 두 분이 어떤 말을 했는지 궁금해요.", session_texts=[], chapter_texts=["그 뒤가 어떻게 됐는지 궁금해요."]) == (
        "강사 두 분이 반발하셨군요. 그때 두 분이 어떤 말을 했는지 들려주시겠어요?", {"gunggeum": 1})
    assert e("그때 두 분이 어떤 말을 했는지 궁금합니다.", session_texts=[], chapter_texts=["그 뒤가 궁금합니다."], formal=True)[0].endswith("들려주시겠습니까?")
    assert e("그 장면이 궁금해요. 그때 두 분은 뭐라고 하셨어요?", session_texts=[], chapter_texts=["어떻게 됐는지 궁금해요."]) == (
        "그때 두 분은 뭐라고 하셨어요?", {"gunggeum": 1})
    # 목록 줄 구조는 건드리지 않는다
    align = "· 비전 제시\n· 변화관리\n\n먼저 하나부터 볼게요. 최근에 방향을 바꾸신 적 있으셨어요?"
    assert e(align, session_texts=[], chapter_texts=[]) == (align, {})


def test_p10_3_opener_frames_drop_filler_and_cap_side_story():
    from diag_project.services.anchor_render import OPENER_FRAME_EXAMPLES, OPENER_FRAMES, opener_frame_for, opener_shape_ok
    from diag_project.services.phrase_caps import is_filler_sentence
    assert len(OPENER_FRAMES) == 5 == len(OPENER_FRAME_EXAMPLES)   # (P11-F) 3종 → 5종
    assert not any("마다" in f for f in OPENER_FRAMES) and not any(is_filler_sentence(x) for ex in OPENER_FRAME_EXAMPLES for x in ex.split(". "))
    seq = [opener_frame_for(i) for i in range(26)]                 # 5챕터 세션의 여는 사례 수를 넉넉히
    assert seq.count(1) == 2 and seq[:3] == [0, 1, 2] and all(a != b for a, b in zip(seq, seq[1:]))    # '이번에는 ~쪽 이야기' 틀은 세션 2회, 같은 틀 연속 없음
    assert opener_shape_ok("목표를 정하는 방식은 팀마다, 사람마다 달라요. 최근에 팀 목표를 새로 잡으신 적 있으셨어요?") == (False, "filler")
    assert opener_shape_ok("목표를 정하고 나누는 일에 관한 건데요, 최근에 팀 목표를 새로 잡으신 적 있으셨어요?") == (True, "")
    assert opener_shape_ok("목표를 정하고 나누는 일에 관한 것입니다만, 최근에 팀 목표를 새로 잡으신 적 있으셨습니까?") == (True, "")
    assert opener_shape_ok("장을 볼 때 무엇부터 담으시는지 듣고 싶어요. 최근에 계획에 없던 것을 장바구니에 담으신 적 있으셨어요?") == (False, "example_copied")
    # 결 예시는 진단과 무관한 분야 — 하위역량 낱말(맡기다·위임·목표)이 없다
    assert not any(re.search(r"(맡기|맡겨|위임|목표|팀원|성과)", ex) for ex in OPENER_FRAME_EXAMPLES)


# ── P10-4 ────────────────────────────────────────────────────────────────────────────────────────
def test_p10_4_strict_register_for_opener_scope_bridge():
    from diag_project.services.persona_register import apply_register as ar, is_formal_statement, register_hint, register_violations as rv
    # 해요체 코치: 여는 문장·범위 문장·다리의 '~습니다/~ㅂ니다'는 섞임 — strict 에서만 잡고 고친다
    pairs = [("이번에는 일을 맡기는 쪽 이야기입니다.", "이번에는 일을 맡기는 쪽 이야기예요."),
             ("맡길 일과 직접 할 일을 어떻게 가르시는지 듣고 싶습니다.", "맡길 일과 직접 할 일을 어떻게 가르시는지 듣고 싶어요."),
             ("팀의 방향을 어떻게 세우셨는지 함께 짚어보겠습니다.", "팀의 방향을 어떻게 세우셨는지 함께 짚어볼게요."),
             ("목표를 정하는 방식을 살펴보려고 합니다.", "목표를 정하는 방식을 살펴보려고 해요."),
             ("이 부분은 리더에게 꽤 어렵습니다.", "이 부분은 리더에게 꽤 어려워요."), ("일정이 바뀌면 순서를 다시 고릅니다.", "일정이 바뀌면 순서를 다시 골라요."),
             ("그 장면이 잘 보입니다.", "그 장면이 잘 보여요."), ("함께 만듭니다.", "함께 만들어요."), ("편하게 말씀해 주십시오.", "편하게 말씀해 주세요."),
             ("이제 '성과관리'로 넘어가겠습니다.", "이제 '성과관리'로 넘어갈게요."), ("아닙니다.", "아니에요.")]
    for src, want in pairs:
        for p in ("Olivia", "Ella", "Michael"):
            assert rv(p, src, scope="strict") == [src], (p, src)
            assert ar(p, src, scope="strict") == (want, 1, []), (p, src)
        assert rv("Olivia", src, scope="all") == [] and rv("Olivia", src, scope="questions") == []     # 종전 범위에서는 건드리지 않는다(공용 안내 본문 보호)
    assert is_formal_statement("그렇게 정했습니다.") and not is_formal_statement("그렇게 정했어요.") and not is_formal_statement("그건 아니다.")
    # 합쇼체 코치: strict 에서는 '~군요/~네요' 면제 없음(여는 문장·다리 자리), 받는 문장 자리(all·questions)는 그대로 자유
    assert ar("Jessica", "이번에는 일을 맡기는 쪽 이야기예요.", scope="strict")[0] == "이번에는 일을 맡기는 쪽 이야기입니다."
    assert rv("Jessica", "그 일을 맡기셨군요.", scope="strict") and rv("Jessica", "그 일을 맡기셨군요.", scope="all") == []
    assert rv("Lucas", "이번에는 일을 맡기는 쪽 이야기입니다.", scope="strict") == []                    # 혼용 코치는 검사하지 않는다
    assert "해요체" in register_hint("Olivia") and "합쇼체" in register_hint("Daniel")
    src = _route_src()
    assert src.count('scope="strict"') >= 4          # 여는 문장 · 다리 · 범위 문장(LLM·폴백)
    assert 'return fallback_q, "bare"' in src and '_areg_k(_pn_k, _sk[-1], scope="strict")' in src      # (P12-6) 여는 문장은 질문만(사전 질문, 이미 코치 어미)
    # (확인) p9 에서 범위를 줄일 때 여는 문장은 빠지지 않았다 — 빠져 있던 것은 해요체 코치의 평서문 검사였다
    from diag_project.services.anchor_render import render_opener
    assert 'scope="strict"' in inspect.getsource(render_opener)


# ── P10-5 ────────────────────────────────────────────────────────────────────────────────────────
def test_p10_5_no_fixed_receive_lines_and_quote_fallback():
    from diag_project.services import persona_voice as V
    from diag_project.services.receive_check import quote_receive, receive_has_content
    assert not hasattr(V, "PERSONA_TAILS") and not hasattr(V, "tails_for")
    src = _route_src()
    assert "tails_for" not in src and "quote_receive as _qrcv_w2" in src and '_tm["receive_fallback"] = "quote"' in src
    ans = "지난달 주간 회의에서 박선임과 김책임 두 분이 일정 문제로 부딪혔어요. 제가 따로 불러서 분담표를 다시 짰습니다."
    # (2026-11-11 검토 반영) 문장 전체가 아니라 핵심 구절만 — 평서 꼴로 줄여 받는다
    assert quote_receive(ans) == "'따로 불러서 분담표를 다시 짰다'는 말씀이셨군요."
    assert quote_receive("김선임이 '지금도 잘 돌아가는데 왜 바꾸냐'고 반대했습니다") == "'김선임이 지금도 잘 돌아가는데 왜 바꾸냐고 반대했다'는 말씀이셨군요."
    for empty in ("네 그랬어요", "글쎄요, 특별히 없었어요.", "", None):
        assert quote_receive(empty) == "", empty                   # 받을 절이 없으면 받기 없이 내보낸다(고정 문구로 메우지 않음)
    assert receive_has_content("분담표를 다시 짜셨군요.", ans) and not receive_has_content("흥미로운 지점이에요.", ans)


def test_p10_5_last_receive_requires_quote():
    import asyncio
    from diag_project.services.close_render import last_receive_ok, render_last_receive
    ans = "그 뒤로는 분기마다 강사 두 분과 일정표를 같이 봅니다."
    assert last_receive_ok("분기마다 강사 두 분과 일정표를 같이 보고 계시군요.", ans) == (True, "")
    assert last_receive_ok("흥미로운 지점이에요.", ans) == (False, "no_quote")
    assert last_receive_ok("그 선택이 궤도를 바꿨군요.", ans) == (False, "no_quote")
    assert last_receive_ok("일정표를 같이 보신다니, 다음에는 어떻게 하실 건가요?", ans)[0] is False
    # LLM 없음(스텁·실패): 리더 절 인용, 받을 내용이 없으면 받기 없이 종료
    assert asyncio.run(render_last_receive(None, user_text=ans, persona_name="Olivia")) == ("'분기마다 강사 두 분과 일정표를 같이 본다'는 말씀이셨군요.", "quote")
    assert asyncio.run(render_last_receive(None, user_text="네", persona_name="Olivia")) == ("", "none")
    assert asyncio.run(render_last_receive(None, user_text="글쎄요, 특별히 없었어요.", persona_name="Olivia")) == ("", "none")


# ── P10-6 ────────────────────────────────────────────────────────────────────────────────────────
def test_p10_6_request_statement_leak_before_opener():
    from diag_project.services.output_guard import (
        clean_close_side, close_side_violation, drop_request_statements, is_request_statement, is_statement_with_question_mark,
    )
    # 원인: 닫는 쪽 금지 꼴에 '듣고 싶' 이 없었고, 요청형 삭제는 탐침 턴에만 걸려 있었다
    assert close_side_violation("그 이야기를 조금 더 듣고 싶어요.") and is_request_statement("그 이야기를 조금 더 듣고 싶어요.")
    assert clean_close_side("분담표를 다시 짜셨군요. 그 이야기를 조금 더 듣고 싶어요.", max_statements=1) == ("분담표를 다시 짜셨군요.", 1)
    opener = "일을 나누는 방식을 듣고 싶어요. 최근에 일을 새로 나눠 보신 적 있으셨어요?"
    body = f"분담표를 다시 짜셨군요. 그 장면을 조금 더 듣고 싶어요. {opener}"
    keep = {re.sub(r"\s+", "", "일을 나누는 방식을 듣고 싶어요.")}
    assert drop_request_statements(body, keep=keep) == (f"분담표를 다시 짜셨군요. {opener}", 1)       # 시스템 여는 문장의 '듣고 싶어요'는 남긴다
    # 평서문에 물음표만 붙인 꼴
    assert is_statement_with_question_mark("두 분 표정이 궁금해요?") and is_statement_with_question_mark("그 뒤가 어떻게 됐는지 듣고 싶어요?")
    assert not is_statement_with_question_mark("두 분은 어떻게 하셨어요?")
    assert drop_request_statements("두 분 표정이 궁금해요? 그때 두 분은 뭐라고 하셨어요?") == ("그때 두 분은 뭐라고 하셨어요?", 1)
    src = _route_src()
    assert "if _is_probe or _is_open:" in src and "_drs_y(clean_reply, keep=_keep_rq_y)" in src


def test_p10_6_comma_joined_wh_questions_count_as_many():
    from diag_project.services.output_guard import count_question_markers as c, split_compound_question, wh_clause_count
    assert c("언제, 누구와 그 이야기를 하셨고, 무엇이 달라졌나요?") == 3 and wh_clause_count("언제, 누구와 그 이야기를 하셨고, 무엇이 달라졌나요?") == 3
    assert c("언제, 누구와 그 이야기를 하셨나요?") == 2
    assert split_compound_question("언제, 누구와 그 이야기를 하셨고, 무엇이 달라졌나요?") == ("무엇이 달라졌나요?", 1)
    # 한 질문으로 두는 꼴
    for one in ("있었다면 언제였고, 어떤 장면이었나요?", "그때 누가 언제 무엇을 했는지 기억나세요?", "두 분에게 뭐라고 말씀하셨어요?",
                "월별 계획을 보여드리기로 하셨을 때, 어떤 선택지들을 버리고 그 방법을 고르셨나요?", "'언제, 누구와 할지' 정하신 건 어떤 계기였어요?"):
        assert c(one) == 1, one


# ── P10-7 ────────────────────────────────────────────────────────────────────────────────────────
def test_p10_7_first_chapter_bridge_fixed_per_coach():
    assert IM.first_chapter_bridge("조직관리", "Olivia (올리비아)") == "그럼 첫 영역인 조직관리부터 볼게요."
    got = {p: IM.first_chapter_bridge("조직관리", p) for p in PERSONAS}
    assert all("조직관리부터" in v and "?" not in v for v in got.values())
    assert got["Jessica"].endswith("보겠습니다.") and got["Daniel"].endswith("여쭙겠습니다.") and got["Lucas"] == "첫 영역, 조직관리부터 갑니다."
    from diag_project.services.persona_register import register_violations
    for p in ("Ella", "Olivia", "Michael", "Jessica", "Daniel"):
        assert register_violations(p, got[p], scope="strict") == [], p
    src = _route_src()
    assert "first_chapter_bridge as _fcb_k" in src and '_first_ch_k = instruction_used == "DIAGNOSIS_CONFIRM"' in src
    # 지시문: LLM 은 범위 1문장만 — 진입 문장은 시스템이 붙인다
    from diag_project.prompts.phase3a.layer3_state import _build_confirm_guide
    guide = _build_confirm_guide({"chapter": "organization_management"})
    assert "범위 1문장만" in guide and "그럼 첫 영역인" not in guide


# ── 린트 P10 열 ──────────────────────────────────────────────────────────────────────────────────
def test_p10_lint_columns():
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from tools import transcript_lint as tl
    lex = tl.cached_lexicon() if hasattr(tl, "cached_lexicon") else __import__("diag_project.services.leak_lexicon", fromlist=["x"]).cached_lexicon()
    CH = "organization_management"

    def row(t, role, content, instr=None, **g):
        return {"t": t, "role": role, "chapter": CH, "probe": None, "instr": instr, "content": content,
                "guard": ({"t": t, "ch": CH, "instr": instr, **g} if role == "model" else None)}
    rows = [
        row(1, "user", "작년 하반기에 리더십 과정을 개편하면서 두 과정만 먼저 시범 운영을 해보자고 했어요."),
        row(2, "model", "흥미로운 지점이에요. 그때 강사들이 어떤 말을 했는지 궁금해요.", "EPISODE_PROBE", episode=1, ep_kind="episode", ep_turn=1),
        row(3, "user", "강사들은 전면 도입을 원했고 팀원들도 일정이 밀린다고 반발했죠."),
        row(4, "model", "흥미로운 지점이에요. 그 뒤가 어떻게 됐는지 궁금해요.", "EPISODE_PROBE", episode=1, ep_kind="episode", ep_turn=2),
        row(5, "user", "제가 주간 회의에서 일정표를 다시 짜서 공유했어요."),
        row(6, "model", "일정표를 다시 짜셨군요. 언제, 누구와 그 이야기를 하셨고, 무엇이 달라졌나요?", "EPISODE_PROBE", episode=1, ep_kind="episode", ep_turn=3),
        row(7, "user", "그 주 금요일에 강사 두 분과 했어요."),
        row(8, "model", "금요일에 강사 두 분과 하셨군요. 반대로 하셨다면 어떻게 됐을까요?", "EPISODE_PROBE", episode=1, ep_kind="episode", ep_turn=4,
            slot="Olivia", slot_kind="counterfactual", slot_text="반대로 하셨다면 어떻게 됐을까요?"),
        row(9, "user", "일정이 더 밀렸겠죠."),
        row(10, "model", "일정이 더 밀렸겠다고 보시는군요. 일을 나누는 방식은 팀마다, 사람마다 다릅니다. 최근에 일을 새로 나눠 보신 적 있으셨어요?", "EPISODE_OPEN",
            episode=2, ep_kind="episode", ep_turn=0, closed="episode1:turns", opener="llm"),
    ]
    data = {"session": "s", "coach": "3", "provider": "claude", "rows": rows, "ledger": {}}
    r = tl.analyze(data, lex)
    assert r["phrase_over"] == {"gunggeum": 1, "side_story": 0, "filler": 1}          # 궁금 2회째 · 채움 문장
    assert r["multi_q_turns"] == 1 and r["multi_q_issues"][0]["t"] == 6               # 의문사 나열
    assert r["fixed_receive"] == 1 and r["fixed_receive_issues"][0]["t"] == 4         # 같은 받는 문장 반복
    assert r["slot_generic"] == 1 and r["slot_issues"][0]["why"] == "no_case_words"   # 사례 낱말 없는 슬롯 문장
    assert r["register_mix_open"] >= 1                                                 # 해요체 코치의 '…다릅니다'(여는 문장 자리)
    md = tl.render_markdown([r], tl.cross_anchor_pairs([r]), lex)
    assert "입버릇 초과(궁금/쪽 이야기/채움)" in md and "[P10 질문 2개+]" in md and "[P10 고정 받기(반복)]" in md and "[P10 슬롯 일반문]" in md


# ── 확인 시뮬 p10a(Olivia 조직·성과관리)에서 본 것 — 시뮬 뒤 결정론 수정 ───────────────────────────────────────
def test_p10a_followups_from_confirm_sim():
    from diag_project.services.anchor_render import opener_frame_for
    from diag_project.services.output_guard import (
        close_side_violation, count_question_markers, drop_request_statements, drop_summary_noise, is_request_statement, split_compound_question,
    )
    from diag_project.services.persona_voice import voice_question
    from diag_project.services.receive_check import leader_nouns
    src = _route_src()
    # 1) 세션 첫 사례가 '이번에는 ~ 이야기예요' 로 열렸다 — 틀 순번은 '앞서 연 사례 수'(이번 것 제외)
    # (P11-F) 틀은 순번표가 아니라 세션 원장(opener_frames)을 보고 고른다 — 첫 사례는 여전히 0번 틀
    from diag_project.services.anchor_render import pick_opener_frame
    assert 'return fallback_q, "bare"' in src and pick_opener_frame([]) == 0 and opener_frame_for(0) == 0      # (P12-6) 틀은 더 고르지 않는다 — 질문만
    # 2) 받을 낱말이 없는 답('네, 맞아요') 뒤의 여는 턴에 "그럼 이 사례를 조금 더 펼쳐 볼게요." 가 붙었다 — 받기가 아니다
    assert leader_nouns("네, 맞아요.") == [] and close_side_violation("그럼 이 사례를 조금 더 펼쳐 볼게요.")
    assert '_tm["receive_dropped"] = 1' in src and "_recv_optional = _is_open and not _ln_w(_llm_user_text)" in src
    # 3) 종료 요약의 총평 문장
    summ = ("두 분을 따로 불러 먼저 이유를 들으셨습니다. 김선임 강사와 박선임 강사의 이야기를 따로 듣고 파일럿 설계 초안을 직접 쓰셨다는 점에서, "
            "저희는 리더가 실행의 첫 장면을 스스로 만드는 힘을 봐요.")
    assert drop_summary_noise(summ) == ("두 분을 따로 불러 먼저 이유를 들으셨습니다.", 1)
    assert drop_summary_noise("그 뒤로 외부 강사 과정에서는 교안을 먼저 문서로 받는 것이 규칙이 됐습니다.")[1] == 0
    # 4) 평서문 꼴로 먼저 묻고 다시 묻는 턴 — "한 가지 짚고 싶은 건, …는지예요. …기억나시나요?"
    two = '한 가지 짚고 싶은 건, 그 "규칙"이 누가 먼저 꺼냈고 어떤 과정으로 팀에 자리 잡았는지예요. 리더님이 교안 문서화를 제안하셨을 때 박선임 선임은 어떤 반응을 보였는지 기억나시나요?'
    assert is_request_statement(two.split(". ")[0] + ".") and drop_request_statements(two)[1] == 1
    assert not is_request_statement("그 뒤로 규칙이 됐는지요?")                       # Daniel 의 '~는지요?' 질문은 요청형 평서문이 아니다
    # 5) 간접 질문 절 두 개는 질문 두 개
    q2 = "그렇게 고르신 뒤 두 분이 실제로 어떻게 움직였는지, 가장 먼저 눈에 띈 변화가 무엇이었는지 들려주실 수 있을까요?"
    assert count_question_markers(q2) == 2 and split_compound_question(q2)[0] == "가장 먼저 눈에 띈 변화가 무엇이었는지 들려주실 수 있을까요?"
    assert count_question_markers("그 설명을 들으신 뒤 두 분의 반응이 실제로 어떻게 달라졌는지, 그 변화가 눈에 보였던 장면을 들려주실 수 있을까요?") == 1
    # 6) Olivia 사전 앵커의 '~을지요?' 폐기
    v = voice_question("Olivia", "예전 방향이 통하지 않아서 팀 목표를 다시 세우신 적이 근래에 있었다면 어떤 일이었을까요?")
    assert "을지요" not in v and v.endswith("어떤 일이었는지 들려주실래요?")
    # 7) 전환 영역의 정의 턴: LLM 이 다시 쓴 진입 문장("그럼 '성과관리' 쪽으로 가볼게요.")은 걷어낸다 · 정의 턴의 평가 리드는 재생성 없이 뗀다
    assert "_mv_k.search(x)" in src and 'set(_v) & _REGEN_KEYS <= {"praise"}' in src
    # 8) 한 문장 틀에서는 리더의 직전 말을 프롬프트에 주지 않는다(직전 답을 되묻는 여는 문장 방지)
    from diag_project.services import anchor_render
    assert "if (lead and not one_sentence)" in inspect.getsource(anchor_render.render_opener)


# ── 확인 시뮬 p10b(고친 코드로 한 번 더)에서 본 것 — 결정론 수정 ──────────────────────────────────────────────
def test_p10b_followups_from_second_confirm_sim():
    from diag_project.services.align_render import receive_sentences
    from diag_project.services.anchor_render import OPENER_FRAMES, opener_shape_ok
    from diag_project.services.output_guard import attach_referent, key_person, strip_suggestion_statements
    from diag_project.services.slot_render import _pick_sentence, slot_sentence_ok
    # 1) 여는 문장이 틀 설명을 되읊었다
    echo = ("무엇을 듣고 싶은지 말씀해 주세요: 문제가 생겼을 때 원인을 어떻게 짚고 어떤 해결 방법들을 비교해 보셨는지 듣고 싶어요. "
            "최근에 일이 진행되다가 예상과 다르게 막히는 일이 있으셨어요?")
    assert opener_shape_ok(echo) == (False, "instruction_echo")
    assert opener_shape_ok("문제가 생겼을 때 원인을 어떻게 짚으시는지 듣고 싶어요. 최근에 일이 진행되다가 예상과 다르게 막히는 일이 있으셨어요?") == (True, "")
    assert not any("무엇을 듣고 싶은지" in f for f in OPENER_FRAMES)
    # 2) 슬롯 문장에서 고른 쪽과 버린 쪽이 뒤섞였다 — "2명 먼저 쓰자고 버리셨다면"
    ans = ["제가 대표님께 올해는 운영팀 2명만 먼저 써 보고 전면 도입은 내년으로 미루자는 안을 숫자와 함께 가져갔어요. "
           "그리고 운영 보고서를 그 도구로 자동으로 만드는 방법을 제가 먼저 만들어서 보여드렸고, 매주 한 시간씩 사용법을 직접 가르쳤습니다."]
    bad = "대표님께 전면 도입 대신 2명 먼저 쓰자고 버리셨다면, 운영팀 사람들은 매주 한 시간씩 직접 배우는 자리에 나왔을까요?"
    assert slot_sentence_ok("counterfactual", bad, ans, persona_name="Olivia") == (False, "garbled_choice")
    good = "운영팀 2명 먼저 대신 바로 전면 도입을 하셨다면, 운영팀 사람들은 매주 한 시간씩 배우는 자리에 어떻게 나왔을까요?"
    assert slot_sentence_ok("counterfactual", good, ans, persona_name="Olivia") == (True, "")
    assert _pick_sentence(f"고른 쪽: 운영팀 2명 먼저\n고르지 않은 쪽: 전면 도입\n문장: {good}") == good and _pick_sentence("그 선택, 응원해요.") == "그 선택, 응원해요."
    # 3) "그리고 운영의 말이나 표정" — 앞 어절까지 삼킨 인물 판정
    assert key_person(ans[0]) == "대표님" and key_person("운영 보고서를 만들었어요") == "" and key_person("최운영 씨가 바꿨어요") == "최운영 씨"
    assert key_person("박선임과 김책임 두 분이 부딪혔어요") == "두 분" and key_person("이기획에게 낮은 등급을 줬어요") == "이기획"
    assert attach_referent("그리고 말이나 표정, 혹은 쓰는 태도가 달라진 게 눈에 띄셨는지 궁금해요.", ans[0]).startswith("대표님의 말이나 표정")
    # 4) ALIGN 받기의 평가 말투(뒤 단계 재생성이 다시 들여온 것)는 버린다 — 정의 구절 인용 폴백으로 간다
    assert receive_sentences("목표를 함께 정하고 중간에 점검하면서 끝까지 가게 한다는 말씀이 인상적이네요.", chapter="performance_management", sub_names=[],
                             user_text="성과관리는 목표를 같이 정하고 중간에 점검해서 끝까지 가게 하는 일이라고 봐요.") == []
    # 5) 질문 뒤에 붙는 범위 안내 — "…달라진 태도 같은 것도 괜찮아요."
    t = "표를 보여 주셨군요. 그때 이기획님이 어떤 반응을 보였는지 떠오르는 장면이 있으셨어요? 말씀이나 표정, 혹은 목표를 같이 쓰는 과정에서 달라진 태도 같은 것도 괜찮아요."
    assert strip_suggestion_statements(t) == ("표를 보여 주셨군요. 그때 이기획님이 어떤 반응을 보였는지 떠오르는 장면이 있으셨어요?", 1)
    # 6) 전환 영역의 진입 문장 꼴 보강 + 8-y 에서 권유문 한 번 더
    src = _route_src()
    assert "시작해|시작하|볼게요|보겠" in src and "strip_suggestion_statements as _sss_y" in src


# ── (2026-11-11 검토 반영) 받기 폴백은 핵심 구절만 — 문장 전체 인용은 기계적으로 읽힌다 ─────────────────────────────
def test_quote_receive_keeps_only_key_clause():
    from diag_project.services.receive_check import QUOTE_RECEIVE_MAX, key_clause, quote_receive as q
    # p10b 에서 나간 문장: "'지시로 시작하면 반대부터 나온다는 걸 그때 배웠습니다'라고 하셨군요." → 안은 내용 절만
    a = "다시 한다면 본부 지시가 내려오기 전에 제가 먼저 개편 이야기를 꺼냈을 것 같아요. 지시로 시작하면 반대부터 나온다는 걸 그때 배웠습니다."
    assert q(a) == "'지시로 시작하면 반대부터 나온다'는 말씀이셨군요."
    cases = {
        "시범 운영을 먼저 해보자고 했어요": "시범 운영을 먼저 해보자고 했다",
        "그래서 두 과정만 먼저 돌려 보자고 했고, 강사 두 분이 일정이 밀린다고 반대해서 제가 주간 회의에서 일정표를 다시 짜서 공유했어요.": "주간 회의에서 일정표를 다시 짜서 공유했다",
        "운영팀만 먼저 붙이다 보니, 강사 쪽은 한참 뒤에야 그 변화를 따라잡았거든요.": "강사 쪽은 한참 뒤에야 그 변화를 따라잡았다",
        "애초에 교안을 문서로 안 받아둔 게 제 실수였죠. 지금은 계약할 때 같이 받습니다.": "지금은 계약할 때 같이 받는다",
        "이번 분기는 팀 분위기가 꽤 좋습니다.": "이번 분기는 팀 분위기가 꽤 좋다",
        "파일럿 만족도가 기존 과정보다 높게 나와서 하반기에 전체 개편으로 넘어갔어요.": "하반기에 전체 개편으로 넘어갔다",
    }
    for src, core in cases.items():
        assert key_clause(src) == core and q(src) == f"'{core}'는 말씀이셨군요.", src
        assert len(core) <= QUOTE_RECEIVE_MAX and core.endswith("다") and "습니다" not in core and "어요" not in core
    for none in ("네 그랬어요", "글쎄요, 특별히 없었어요.", "저는 그 방식을 좋아하지 않습니다.", "", None):
        assert q(none) == "", none                    # 받을 구절이 없거나 꼴을 정할 수 없으면 폴백을 쓰지 않는다
    assert "라고 하셨군요" not in q(a)


# ── (2026-11-11 지연 단축 b) 두 질문은 재생성 없이 마지막 질문만 ────────────────────────────────────────────────
def test_latency_b_two_questions_trimmed_without_regen():
    from diag_project.services.output_guard import count_question_markers as c, keep_last_question, split_compound_question
    src = _route_src()
    i = src.index("def _trim_two(txt: str)")
    j = src.index("while _iss and _rounds < 1 and not", i)
    pre = src[i:j]
    assert 'if _q_expected and "two_questions" in _iss:' in pre and "_timed_regen" not in pre            # 루프 앞에서 바로 자른다(LLM 호출 없음)
    assert '_tm["two_q_trim"] = 1' in pre and "_issues_for_regen(clean_reply)" in pre
    loop = src[j: src.index('_tm["format_regen"] = _rounds', j)]
    assert "_cand, _n_tq2 = _trim_two(_cand)" in loop and "_iss2 = _issues_for_regen(_cand)" in loop    # 재생성 본문이 두 질문이어도 다시 돌리지 않는다
    # P9-5(대상 없는 질문 보정)는 그대로 — 자른 턴(one_q)은 8-w3 의 대상 검사를 받는다
    assert '_trimmed_w3' not in src and src.index("# 8-w3.") > j      # (P12e-5) 8-w3 수선은 삭제(자리 표시만 남음)
    # 자르는 규칙: 문장이 둘이면 마지막 질문, 한 문장 안의 복합 질문은 뒤 질문
    def trim(t):
        t, _ = split_compound_question(t)
        return keep_last_question(t)[0]
    t1 = "분담표를 다시 짜셨군요. 그때 두 분은 뭐라고 하셨어요? 그 뒤에 일정은 어떻게 됐나요?"
    assert trim(t1) == "분담표를 다시 짜셨군요. 그 뒤에 일정은 어떻게 됐나요?" and c(trim(t1)) == 1
    t2 = "분담표를 다시 짜셨군요. 두 분이 어떻게 받아들였는지, 그리고 그 뒤 일정은 어떻게 됐나요?"
    assert trim(t2) == "분담표를 다시 짜셨군요. 그 뒤 일정은 어떻게 됐나요?" and c(trim(t2)) == 1
    t3 = "분담표를 다시 짜셨군요. 그런 일이 또 있었나요? 있었다면 언제였고, 어떤 장면이었나요?"
    assert trim(t3) == t3                                                                                  # 조건절로 잇는 한 쌍은 한 질문으로 둔다


# ── 지연 단축 b 시뮬(lb1)에서 본 부작용 — 결정론 수정 ────────────────────────────────────────────────────────
def test_latency_b_followups_from_sim():
    from diag_project.services.output_guard import count_question_markers as c, is_aid_sentence, keep_main_question, split_compound_question
    from diag_project.services.receive_check import check_receive
    # 1) 질문 뒤 도움말이 '마지막 질문'으로 남고 진짜 질문이 지워졌다
    t = ("한꺼번에 밀어붙이면 강사들이 떠날 수 있다고 보셨고, 속도 대신 두 분이 남을 수 있는 쪽을 택하셨군요. "
         "그 결정을 하실 때 리더님이 직접 두 분께 건네신 말이나 행동이 있었을까요? 예를 들어 어떤 식으로 설득하거나, 일정을 어떻게 조정하셨는지 떠올려 주시면 돼요.")
    assert is_aid_sentence("예를 들어 어떤 식으로 설득하거나, 일정을 어떻게 조정하셨는지 떠올려 주시면 돼요.")
    assert is_aid_sentence("팀 앞에서 방향을 설명하셨는지, 두 분을 따로 만나셨는지 편하게 떠올려 주시면 돼요.") and not is_aid_sentence("그때 두 분은 뭐라고 하셨어요?")
    out, n = keep_main_question(t)
    assert out.endswith("건네신 말이나 행동이 있었을까요?") and n == 1 and c(out) == 1
    # 직접 묻는 문장이 없으면 도움말이 그 턴의 질문이다 — 지우지 않는다
    only_aid = "작년 3월에 지시가 내려왔군요. 팀 앞에서 방향을 설명하셨는지, 두 분을 따로 만나셨는지 편하게 떠올려 주시면 돼요."
    assert keep_main_question(only_aid) == (only_aid, 0)
    # 직접 질문이 둘이면 종전대로 마지막 질문
    two = "분담표를 다시 짜셨군요. 그때 두 분은 뭐라고 하셨어요? 그 뒤에 일정은 어떻게 됐나요?"
    assert keep_main_question(two)[0] == "분담표를 다시 짜셨군요. 그 뒤에 일정은 어떻게 됐나요?"
    assert split_compound_question(keep_main_question(two)[0])[1] == 0
    # 2) 명사가 아니어도 리더 말을 담은 받기는 인용으로 본다(따옴표로 옮긴 구절 · 리더 어절 2개 이상) — 내용 없는 받기는 여전히 미인용
    u = "한꺼번에 밀어붙이면 강사들이 떠날 수 있다고 봤어요. 그래서 속도보다는 두 사람이 남을 수 있는 쪽을 골랐습니다."
    assert check_receive('리더님이 "떠날 수 있다"는 쪽을 먼저 떠올리셨다는 게, 사람을 지키는 방향으로 무게를 두신 것처럼 들려요. 그럼 무엇을 먼저 확인하셨어요?', u) == (True, True)
    assert check_receive("흥미로운 지점이에요. 그 뒤에는요?", "제가 따로 불러서 분담표를 다시 짰습니다.") == (True, False)
    assert check_receive("그 판단이 지금 돌아보니 가장 분명하게 남으셨군요. 무엇이 달라졌을까요?", "강사들도 처음부터 같이 배우게 했으면 더 빨랐을 것 같아요.") == (True, False)
    # 3) 범위 문장 자리의 예고 문장("먼저 여쭤볼게요.")은 범위 문장이 아니다
    src = _route_src()
    assert "여쭤볼게요|여쭙겠습니다" in src[src.index("# (lb1) 범위 문장 자리에 예고 문장"):][:400] and "keep_main_question as _kmq_t" in src


# ── (2026-11-11) 재생성 예산 · 질문 꼴 받기 살리기 · 호출 순서 · 단계 표시 ──────────────────────────────────────
def test_regen_budget_one_per_turn_then_deterministic_repair():
    src = _route_src()
    # 재생성 래퍼: 예산을 썼으면 LLM 을 부르지 않는다. 집중 호출(여는 문장·슬롯·요약·마지막 받기)의 다시 쓰기도 같은 예산
    i = src.index("async def _timed_regen(**kw):")
    wrap = src[i: i + 1200]
    assert 'if _tm.get("no_regen") or _tm.get("budget_used"):' in wrap and '_tm["budget_used"] = 1' in wrap
    assert src.count('rounds=(1 if _tm.get("budget_used") else 2)') >= 2      # (P12-6) 여는 문장 렌더 호출이 빠졌다 · (P12b-1) 페르소나 슬롯은 1회만 쓴다
    # 8-w: 재생성 1회, 그 뒤는 결정론 수선(긴 받기 자르기 · 질문 없으면 후속 질문 · 받기 없으면 구절 인용 받기)
    j = src.index("while _iss and _rounds < 1 and not (_tm.get(\"budget_used\")")
    after = src[j: src.index("# 8-w2.", j)]
    assert '"long_receive" in _iss' in after and "followup_from_user as _ffu_w" in after and "quote_receive as _qrcv_w" in after
    assert '_tm["format_repaired"] = _fixed_iss' in after
    # 종료 턴: 본 호출 재생성 루프 없음, 본문은 뒤 단계가 재생성으로 덮지 않는다
    k = src.index("# 8-d. CHAPTER_READY_TO_END")
    close = src[k: src.index("# 8-f.", k)]
    assert "_timed_regen" not in close and '_tm["no_regen"] = 1' in close


def test_question_shaped_receive_is_revived_as_statement():
    from diag_project.services.output_guard import count_question_markers as c, keep_main_question, question_to_statement as q2s, revive_question_receive as rv
    assert q2s("처음의 반대가 거리를 둔 게 아니라 조건부였다는 뜻이었을까요?") == "처음의 반대가 거리를 둔 게 아니라 조건부였다는 뜻이었군요."
    assert q2s("그 뒤로 두 분이 먼저 자료를 가져오셨나요?") == "그 뒤로 두 분이 먼저 자료를 가져오셨군요."
    assert q2s("두 분이 남는 쪽을 고르신 거죠?") == "두 분이 남는 쪽을 고르신 거군요."
    assert q2s("그때 무엇을 먼저 확인하셨어요?") == "그때 무엇을 먼저 확인하셨군요."     # 어미표는 꼴만 본다 — 진짜 질문인지는 revive 의 내용 검사가 거른다
    assert q2s("분담표를 다시 짜셨군요.") is None and q2s("그 뒤에는 어떻게 하실 건가요?") is not None
    u = "처음엔 그래도 결국 바꿀 거잖아요 하던 김선임 선임이 파일럿 2주차부터 본인 과정 자료를 먼저 가져왔어요."
    t = ("파일럿 2주차에 김선임이 먼저 자료를 가져왔다는 건, 처음의 반대가 거리를 둔 게 아니라 조건부였다는 뜻이었을까요? "
         "그 2주 사이에 어떤 신호를 보고 움직였다고 느끼셨어요?")
    out, n = rv(t, u)
    assert n == 1 and out.startswith("파일럿 2주차에 김선임이 먼저 자료를 가져왔다는 건, 처음의 반대가 거리를 둔 게 아니라 조건부였다는 뜻이었군요.")
    assert c(out) == 1 and keep_main_question(out)[0] == out                      # 받기가 살아서 질문은 하나만 남는다
    # 리더 말을 담지 않은 첫 질문은 받기가 아니다 — 바꾸지 않는다(종전대로 마지막 질문만 남는다)
    t2 = "그때 기분이 어떠셨나요? 그 뒤에는 무엇을 하셨어요?"
    assert rv(t2, u) == (t2, 0)
    # 평서문 받기가 이미 있으면 건드리지 않는다
    t3 = "자료를 먼저 가져왔군요. 그게 조건부였다는 뜻이었을까요? 그때 무엇을 보셨어요?"
    assert rv(t3, u) == (t3, 0)
    assert "revive_question_receive as _rqr_t" in _route_src()


def test_call_order_opener_parallel_and_close_turn_skips_main_call():
    src = _route_src()
    # 사례를 닫고 새로 여는 턴: 여는 문장 렌더는 코치 본 호출과 병렬(태스크) — 본 호출 뒤에 합친다
    assert "_opener_task = _aio_op.ensure_future(_opener_for(current_target_sub, _bei_anchor_text))" in src
    assert src.index("_opener_task = _aio_op.ensure_future") < src.index("llm_output = await llm.generate_phase3a_interaction(") < src.index("_opener_result = await _opener_task")
    assert "_opener_task.cancel()" in src                                                       # 본 호출 실패 시 정리
    # 챕터 종료 턴: 본 호출 생략(출력을 쓰지 않았다)
    i = src.index('if instruction_used == "CHAPTER_READY_TO_END":\n            # (2026-11-11 호출 순서)')
    assert 'llm_output = {"reply": ""}' in src[i: i + 700]
    from diag_project.services.anchor_render import render_opener
    assert "rounds: int = 2" in inspect.getsource(render_opener)


def test_turn_stage_progress_and_endpoint():
    from diag_project.routes import diagnoses as D
    from diag_project.services import turn_progress as tp
    sid = "s-1"
    assert tp.get_stage(sid)["stage"] == "idle"
    tp.start(sid)
    assert tp.get_stage(sid) == {"stage": "reading", "label": "답변을 읽고 있어요", "elapsed_s": tp.get_stage(sid)["elapsed_s"]}
    tp.set_stage(sid, "polishing"); tp.set_stage(sid, "thinking")                 # 단계는 뒤로 가지 않는다
    assert tp.get_stage(sid)["stage"] == "polishing" and tp.get_stage(sid)["label"] == "문장을 다듬고 있어요"
    tp.set_stage(sid, "없는단계"); tp.set_stage("모르는세션", "thinking")          # 무시
    tp.clear(sid)
    assert tp.get_stage(sid) == {"stage": "idle", "label": "", "elapsed_s": 0.0}
    assert "/{session_id}/turn_stage" in {getattr(r, "path", "") for r in D.router.routes}
    src = inspect.getsource(D.get_turn_stage)
    assert "assert_can_access_session" in src                                                  # 남의 세션 단계는 볼 수 없다
    sub = inspect.getsource(D.submit_message)
    assert "_tp.start(" in sub and "finally:" in sub and "_tp.clear(" in sub                    # 어떤 경로로 끝나도 지운다


def test_lc1_followup_gunggeum_comma_joined_two_questions():
    """측정 시뮬 lc1: "…오갔는지 궁금해요, 이 파일럿 말고 다른 방식도 검토하셨을까요?" — 쉼표로 이은 두 질문은 뒤 질문만 남긴다."""
    from diag_project.services.output_guard import count_question_markers as c, split_compound_question as sp
    t = "그 판단이 이탈을 먼저 내다본 데서 나왔군요. 머릿속에서 어떤 선택지들이 오갔는지 궁금해요, 이 파일럿 말고 다른 방식도 검토하셨을까요?"
    assert c(t) == 2 and sp(t) == ("그 판단이 이탈을 먼저 내다본 데서 나왔군요. 이 파일럿 말고 다른 방식도 검토하셨을까요?", 1)
    assert c("두 분의 태도가 어떻게 달라졌는지 궁금해요.") == 1
