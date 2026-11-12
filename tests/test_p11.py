"""P11 — 11/12 운영 Daniel 세션(반말·초단답 리더) 검토 반영.

A 짧은 답·반말 입력(동의·거절 사전, 되묻기, 고정 받기, 고정 문장 말투) · B 슬롯 문장(끝맺음·문형 반복, 1인칭) · C 질문 완결성 ·
D 예고·하지 않은 말 귀속·때 이른 감사 · F 여는 문장 틀 · H 받는 문장 · I 같은 답 안내. 전부 LLM 없이 본다.
"""
import os
import uuid

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COACHES = ("Ella", "Jessica", "Olivia", "Daniel", "Michael", "Lucas")


def _src(rel):
    return open(os.path.join(ROOT, rel), encoding="utf-8").read()


# ── A2: 동의·거절 사전 ──────────────────────────────────────────────────────
def test_a2_consent_and_decline_lexicon():
    from diag_project.services.short_input import is_consent_word, is_decline_word
    for w in ("ㅇㅋ", "ㅇㅇ", "넵", "넹", "응", "어", "그래", "콜", "ok", "OKAY", "계속", "고", "네네", "ㅇㅋ!"):
        assert is_consent_word(w), w
    for w in ("놉", "ㄴㄴ", "아니", "싫어", "no", "아니요."):
        assert is_decline_word(w), w
    for w in ("고객이 화를 냈어", "어제 회의에서", "아니요, 그때는 달랐어요", "계속 미뤘어요", ""):
        assert not is_consent_word(w) and not is_decline_word(w), w


def test_a2_every_consent_judge_reads_the_lexicon():
    from diag_project.prompts.phase3a.layer3_state import is_consent_only
    from diag_project.services.avoidance_detector import is_invalid_input
    from diag_project.services.bei_engine import is_no_case_text
    from diag_project.services.input_anomaly import is_consent
    from diag_project.services.instruction_decider import is_next_chapter_consent, is_user_consent
    for w in ("ㅇㅋ", "콜", "고", "넹"):
        assert is_consent(w) and is_user_consent(w) and is_consent_only(w) and is_next_chapter_consent(w), w
        assert not is_invalid_input(w), w                      # 자모로 쓴 동의는 의미 없는 입력이 아니다
    assert not is_invalid_input("ㄴㄴ") and is_invalid_input("ㅁㅁ")
    assert not is_next_chapter_consent("놉") and is_no_case_text("놉") and is_no_case_text("ㄴㄴ")


def _detect(text, prev_instr="EPISODE_PROBE", coach="그 회의에서 처음 하신 말은 무엇이었습니까?", **kw):
    from diag_project.services import input_anomaly as IA
    base = dict(user_text=text, prev_user_text="작년 3월 일입니다.", earlier_user_texts=[], prev_coach_text=coach, prev_instruction=prev_instr,
                event_texts=[], pause_pending=False, awaiting_choice=False, definition_reasked=False)
    base.update(kw)
    return IA.detect(**base)


def test_a2_intro_confirm_reask_only_when_undecidable():
    intro = "안내입니다. 그러면 시작해도 되겠습니까?"
    assert _detect("ㅇㅋ", prev_instr="DIAGNOSIS_INTRO", coach=intro) is None            # 동의 — 재요청 없음
    assert _detect("콜", prev_instr="DIAGNOSIS_INTRO", coach=intro) is None
    assert _detect("놉", prev_instr="DIAGNOSIS_INTRO", coach=intro).kind == "decline_confirm"   # 거절 — "'네'라고 답해 주십시오" 가 아니다
    assert _detect("sp", prev_instr="DIAGNOSIS_INTRO", coach=intro).kind == "confirm_reask"     # 판정 불가일 때만
    from diag_project.services.intro_messages import persona_line
    for c in COACHES:
        assert "'네'라고" not in persona_line(c, "confirm_decline")


# ── A3: 되묻기 ──────────────────────────────────────────────────────────────
def test_a3_clarify_request_is_not_ignored():
    from diag_project.services.short_input import is_clarify_request
    for w in ("뭔소리야", "무슨 말이야", "뭐라고", "?", "??", "이해 안 돼", "네?", "다시 말해줘"):
        assert is_clarify_request(w), w
        assert _detect(w).kind == "clarify", w
    assert not is_clarify_request("팀원이 뭐라고 했는지 정확히는 기억이 안 나지만 대체로 수긍했습니다")
    assert _detect("뭔소리야", awaiting_choice=True) is None and _detect("뭔소리야", pause_pending=True) is None
    # 정의 질문 뒤의 되묻기는 정의 재요청 1회가 받는다(되풀이하지 않는다)
    assert _detect("뭔소리야", prev_instr="COMPETENCY_ASK", coach="'조직관리'를 리더님께서는 어떤 일이라고 생각하십니까?").kind == "def_reask"
    assert _detect("뭔소리야", prev_instr="COMPETENCY_ASK", coach="'조직관리'를 어떤 일이라고 생각하십니까?", definition_reasked=True) is None


def test_a3_h_reask_turn_wiring_keeps_ledger():
    src = _src("diag_project/routes/diagnoses.py")
    assert '_reask_kind = "clarify" if _anomaly.kind == "clarify" else "contentless"' in src
    assert 'elif state.get("bei_reask_only"):' in src and '_tm["bei"] = "reask"' in src
    i = src.index('elif state.get("bei_reask_only"):')
    assert "record_leader_turn" not in src[i: src.index("else:", i)]            # 다시 묻기 턴은 리더 턴·슬롯 판정을 쓰지 않는다
    assert "and not _reask_kind):" in src and '"CLARIFY_REASK"' in src
    from diag_project.services.event_tracker import INPUT_ANOMALY_INSTRUCTIONS
    assert "CLARIFY_REASK" in INPUT_ANOMALY_INSTRUCTIONS
    from diag_project.services.intro_messages import persona_line
    from diag_project.services.persona_register import register_violations
    for c in COACHES:
        assert persona_line(c, "clarify_sorry") and register_violations(c, persona_line(c, "clarify_sorry"), scope="strict") == [], c


# ── A1·A4·H: 받는 문장 ──────────────────────────────────────────────────────
def test_a1_h_contentless_and_receive_bans():
    from diag_project.services.input_anomaly import is_ack_only, is_contentless_smalltalk
    from diag_project.services.short_input import is_contentless_answer
    from diag_project.services.turn_checks import drop_banned_receives, receive_ban_reason
    assert is_contentless_smalltalk("밥") and is_contentless_smalltalk("그냥 그래")
    for w in ("네", "맞아요", "그냥 그럼", "네, 맞아요", "ㅇㅋ"):
        assert is_contentless_answer(w) and is_ack_only(w), w
    assert not is_contentless_answer("네, 그날 회의에서 먼저 말했어요")
    assert receive_ban_reason("밥은 드셨는지 여쭤봐 주신 셈이네요, 편하게 말씀해 주셔서 고맙습니다.") == "asked_by_leader"
    assert receive_ban_reason("편하게 말씀해 주셔서 고맙습니다.") == "speech_style"
    assert receive_ban_reason("그 말씀이 배움처럼 들리네요.") == "interpretive" and receive_ban_reason("그 대목이 흥미롭습니다.") == "interpretive"
    assert receive_ban_reason("두 강사가 반대했군요.") is None and receive_ban_reason("그 뒤에 무엇이 달라졌습니까?") is None
    out, why = drop_banned_receives("기다려 준 것으로 들리네요. 그 뒤에 김대리는 뭐라고 했습니까?")
    assert out == "그 뒤에 김대리는 뭐라고 했습니까?" and why == ["interpretive"]
    src = _src("diag_project/routes/diagnoses.py")
    assert 'state.get("rapport_turn_count", 0) == 2 and system_override_text is None' in src and '_tm["smalltalk"] = "fixed2"' in src
    assert "if _n_st > (1 if _q_expected else 3):" in src                         # 탐침 턴의 받는 문장은 1문장
    from diag_project.prompts.phase3a.episode_card import BEI_GUIDES, TURN_FORMAT_RULES
    assert "되받기 1문장 + 질문 1개" in BEI_GUIDES["EPISODE_PROBE"] and "되받기 1문장 + 질문 1개" in TURN_FORMAT_RULES
    assert "말씨는 그대로" in TURN_FORMAT_RULES                                    # A4 반말에도 코치 말투 유지


def test_h_receive_overlap_measures_parroting():
    from diag_project.services.turn_checks import receive_overlap
    u = "작년에 평가 등급이 팀원 기대와 달라서 따로 불러 이야기했어요."
    whole = receive_overlap("작년에 평가 등급이 팀원 기대와 달라서 따로 불러 이야기하셨군요.", u)
    brief = receive_overlap("'평가 등급'을 두고 따로 부르셨군요.", u)
    assert whole[1] >= 0.8 and brief[1] <= 0.4 and whole[2] > brief[2]


# ── A5: 고정 문장 말투 ──────────────────────────────────────────────────────
def test_a5_fixed_lines_follow_coach_register():
    from diag_project.services.intro_messages import build_intro_anchor_section, duplicate_answer_line, finish_choice_line, line_register
    from diag_project.services.system_lines import SYSTEM_LINES, system_line
    from tools.transcript_lint import mixed_register_sentences
    for c in COACHES:
        body = build_intro_anchor_section(c)
        pol, frm = mixed_register_sentences(body)
        assert not (pol and frm), (c, pol[:1], frm[:1])                           # 안내 본문 안에서 말투가 섞이지 않는다
        if line_register(c) == "formal":
            assert "안내드릴게요" not in body and "이루어져 있어요" not in body and "시작해볼까요" not in body and body.endswith("시작해도 되겠습니까?")
        for key in SYSTEM_LINES:
            pol, frm = mixed_register_sentences(system_line(key, c, nm="성과관리") if "{nm}" in SYSTEM_LINES[key]["polite"] else system_line(key, c))
            assert not (pol and frm), (c, key)
        pol, frm = mixed_register_sentences(finish_choice_line(c))
        assert not (pol and frm), c
    assert "5개 영역" in build_intro_anchor_section("Daniel") and "150분" in build_intro_anchor_section("Ella")
    # 원인: 말투 교정이 시스템 고정 턴에서 지역 import 때문에 건너뛰었다 — 턴 핸들러 안에서 split_sentences 를 다시 지역 import 하지 않는다
    src = _src("diag_project/routes/diagnoses.py")
    body_src = src[src.index("async def _submit_message_phase3a("):]
    import re
    assert not re.search(r"import[^\n]*\bsplit_sentences(?!\s+as\b)(?!_)", body_src) and not re.search(r"import is_question as is_question_sentence", body_src)
    assert duplicate_answer_line("Daniel", 1) == ("앞서 말씀하신 내용과 같습니다.", False)


def test_a5_lint_flags_mixed_register_turn_but_keeps_receive_exception():
    from tools.transcript_lint import mixed_register_sentences
    pol, frm = mixed_register_sentences("그럼 오늘 흐름을 안내드릴게요. 진단은 다섯 영역으로 이루어져 있습니다.")
    assert pol and frm
    pol, frm = mixed_register_sentences("두 분을 따로 부르셨군요. 그 자리에서 처음 하신 말은 무엇이었습니까?")
    assert not pol and frm                                                        # 받는 문장의 '~군요/~네요' 는 예외
    pol, frm = mixed_register_sentences("그 일이 있었는지요? 말씀해 주시겠습니까?")
    assert not pol


# ── B: 슬롯 문장 ────────────────────────────────────────────────────────────
def test_b_slot_sentence_no_repeated_ending_no_first_person():
    from diag_project.services.slot_render import _OBSERVATION_EXAMPLES, has_leader_first_person, repeats_used_shape, slot_sentence_ok
    u = ["교육 체계 개편을 두고 김선임과 박선임 사이에서 제가 먼저 따로 이야기를 꺼내야 했습니다", "본부 지시라 미룰 수가 없었어요"]
    used = ["두 선임 사이에서 개편을 밀어야 했던 자리, 가볍지 않으셨겠습니다."]
    assert slot_sentence_ok("observation", "김선임과 박선임 사이에서 제가 먼저 따로 이야기를 꺼내야 했던 자리, 가볍지 않으셨겠습니다.", u, persona_name="Daniel") == (False, "first_person")
    assert slot_sentence_ok("observation", "본부 지시와 두 선임의 반대 사이에 서야 했던 자리, 가볍지 않으셨겠습니다.", u, persona_name="Daniel", used=used) == (False, "same_ending")
    assert slot_sentence_ok("observation", "본부 지시와 두 선임 사이에 서야 했던 자리, 오래 망설이셨겠습니다.", u, persona_name="Daniel", used=used) == (False, "same_shape")
    assert slot_sentence_ok("observation", "개편을 미룰 수 없는 처지에서 두 선임을 따로 만나기까지 오래 망설이셨겠습니다.", u, persona_name="Daniel", used=used) == (True, "")
    assert has_leader_first_person("저희 팀이 먼저 나섰던 일") and not has_leader_first_person("문제가 커진 뒤였습니다")
    # 다른 코치의 슬롯에도 같은 규칙
    u2 = ["올해는 운영팀 두 명만 먼저 쓰게 하고 전면 도입은 내년으로 미뤘어요"]
    used2 = ["운영팀 두 명 없이 바로 전면 도입을 하셨다면 팀원들은 어떻게 움직였을까요?"]
    assert slot_sentence_ok("counterfactual", "전면 도입을 내년으로 미루지 않으셨다면 운영팀 두 명은 어떻게 움직였을까요?", u2, persona_name="Olivia", used=used2)[1] == "same_ending"
    assert repeats_used_shape("전면 도입을 미루지 않으셨다면 운영팀은 무엇부터 막혔을까요?", used2) is None
    assert len(_OBSERVATION_EXAMPLES) == 5 and len({x.split()[-1] for x in _OBSERVATION_EXAMPLES}) == 5   # 예시 끝맺음이 전부 다르다
    src = _src("diag_project/services/slot_render.py")
    assert "이번 세션에서 이미 쓴 문장" in src and 'return None, "miss:first_person"' in src


# ── C: 질문 완결성 ──────────────────────────────────────────────────────────
def test_c_question_completeness_real_cases():
    from diag_project.services.output_guard import count_question_markers, split_compound_question
    from diag_project.services.turn_checks import dangling_references, default_slot_question, question_issues, strip_question_start
    assert "dangling_start" in question_issues("있었다면 누가 어떤 이야기를 하셨는지 짚어 주십시오", "네")
    assert strip_question_start("있었다면 누가 어떤 이야기를 하셨는지 짚어 주십시오") == "누가 어떤 이야기를 하셨는지 짚어 주십시오"
    assert "fragment" in question_issues("팀원들이 그 과정에서 보인 태도였는지 궁금합니다", "평가 결과를 메일로 보냈어요")
    q2 = "어떤 장면이 떠오르셨는지, 혹시 기억나는 장면은 언제였습니까?"
    assert count_question_markers(q2) == 2 and "two_questions" in question_issues(q2, "작년 일이에요")
    assert split_compound_question(q2)[0] == "혹시 기억나는 장면은 언제였습니까?"
    assert dangling_references("그 변화를 팀원들은 어떻게 받아들였습니까?", "평가 결과를 메일로 보냈어요") == ["그 변화"]
    assert dangling_references("그 변화를 팀원들은 어떻게 받아들였습니까?", "회의 방식을 바꿨어요") == []
    assert dangling_references("그때 김과장은 뭐라고 했습니까?", "네") == ["그때"]
    assert question_issues("김과장은 그 회의에서 처음에 뭐라고 했습니까?", "주간 회의에서 김과장이 반대했습니다") == []
    for slot in ("context", "action", "reaction", "result", "criterion", "reflection"):
        for formal in (True, False):
            q = default_slot_question(slot, formal=formal, topic_text="작년 3월에 교육 체계를 전면 개편하라고 했을 때 두 강사가 반대했습니다")
            assert q.endswith("?") and count_question_markers(q) == 1 and q.startswith("말씀하신 '"), q
    src = _src("diag_project/routes/diagnoses.py")
    i = src.index("# 8-w4. (2026-11-12 P11-C)")
    blk = src[i: src.index("# 8-s.", i)]
    assert blk.index('_tm["q_complete"] = "repaired"') < blk.index("_timed_regen(") < blk.index('_tm["q_complete"] = f"default:{_slot_c}"')   # 수선 → 재생성 1회 → 기본 질문


# ── D: 예고·귀속·감사 ───────────────────────────────────────────────────────
def test_d_announcement_unsaid_attribution_thanks():
    from diag_project.services.turn_checks import drop_announcements, drop_premature_thanks, strip_unsaid_attribution, unsaid_spans
    out, cut = drop_announcements("그 면담을 조금 더 듣고 싶습니다. 그 자리에서 처음 하신 말은 무엇이었습니까?")
    assert out == "그 자리에서 처음 하신 말은 무엇이었습니까?" and len(cut) == 1
    assert drop_announcements("이제 결과 쪽을 여쭤보겠습니다.")[1] == []                 # 질문이 따로 없으면 지우지 않는다
    keep = {"이제'성과관리'로이어가겠습니다."}
    assert drop_announcements("이제 '성과관리'로 이어가겠습니다. 최근에 목표를 다시 정하신 일이 있으셨습니까?", keep=keep)[1] == []   # 고정 다리는 그대로
    L = ["작년에 평가 등급이 팀원 기대와 달라서 따로 불러 이야기했어요.", "밥"]
    out, hits, lost = strip_unsaid_attribution("방금 말씀하신 '인정'과도 이어지는 부분입니다만, 최근에 팀원의 성과를 따로 짚어 주신 일이 있으셨습니까?", L)
    assert out == "최근에 팀원의 성과를 따로 짚어 주신 일이 있으셨습니까?" and hits == ["인정"] and lost is False
    out, hits, lost = strip_unsaid_attribution("'평가 등급' 이야기를 하셨군요. 앞서 말씀하신 신뢰가 여기서도 보입니다. 그 뒤에 무엇이 달라졌습니까?", L)
    assert "신뢰" not in out and "'평가 등급'" in out and hits == ["신뢰"]
    assert unsaid_spans("앞서 말씀하신 내용과 같습니다.", L) == [] and unsaid_spans("'조직관리'를 어떻게 보십니까?", L, ["조직관리"]) == []
    _, hits, lost = strip_unsaid_attribution("방금 말씀하신 '보상' 이야기는 어떻게 끝났습니까?", L)
    assert hits == ["보상"] and lost is True                                       # 질문 몸통 안의 귀속 — 질문을 잃었다고 알린다(호출자가 기본 질문으로)
    assert drop_premature_thanks("사례를 들려주셔서 감사합니다. 그 뒤에 무엇이 달라졌습니까?")[0] == "그 뒤에 무엇이 달라졌습니까?"
    src = _src("diag_project/routes/diagnoses.py")
    assert 'if not _tm.get("closed"):\n                    _c_d, _r_d = _dpt_d(' in src    # 감사는 사례를 닫는 턴에서만 남긴다


# ── F: 여는 문장 틀 ─────────────────────────────────────────────────────────
def test_f_opener_frames_rotate_without_adjacent_repeat():
    from collections import Counter
    from diag_project.services.anchor_render import OPENER_FRAME_EXAMPLES_FORMAL, OPENER_FRAMES, _frame_example, pick_opener_frame
    from diag_project.services.persona_register import register_violations
    seq: list[int] = []
    for _ in range(10):
        seq.append(pick_opener_frame(seq))
    assert max(Counter(seq).values()) == 2 and all(a != b for a, b in zip(seq, seq[1:])) and seq[0] not in (1, 4)
    for _ in range(6):
        seq.append(pick_opener_frame(seq))
    assert all(a != b for a, b in zip(seq, seq[1:]))                               # 10번을 넘겨도 직전 틀은 쓰지 않는다
    assert pick_opener_frame([2, 2, 0]) != 0 and pick_opener_frame([2, 2, 0]) != 2
    assert not any("듣고 싶" in f for f in OPENER_FRAMES) and len(OPENER_FRAME_EXAMPLES_FORMAL) == len(OPENER_FRAMES)
    for i in range(len(OPENER_FRAMES)):
        assert register_violations("Daniel", _frame_example("Daniel", i), scope="strict") == [], i
        assert register_violations("Olivia", _frame_example("Olivia", i), scope="strict") == [], i
    src = _src("diag_project/routes/diagnoses.py")
    assert '_gl_store["opener_frames"]' in src and '_tm["opener_frame"] = _frame_op' in src


# ── I: 같은 답 안내 ─────────────────────────────────────────────────────────
def test_i_duplicate_answer_lines_rotate_and_change_angle():
    from diag_project.services.intro_messages import DUPLICATE_LINES, duplicate_answer_line
    for c in COACHES:
        first, has_q = duplicate_answer_line(c, 1)
        assert not has_q and first.endswith(("같네요.", "같습니다."))
        later = [duplicate_answer_line(c, n) for n in (2, 3, 4, 5)]
        assert all(q for _, q in later) and all("다른" in s for s, _ in later)        # 2회째부터는 다른 장면을 청한다
        assert len({s for s, _ in later[:3]}) == 3 and later[3][0] == later[0][0]   # 3종을 돌려 쓴다
    assert all(len(v["first"]) == 3 and len(v["angle"]) == 3 for v in DUPLICATE_LINES.values())


# ── 시뮬 프로필 ─────────────────────────────────────────────────────────────
def test_sim_profile_banmal_short_lead():
    import asyncio
    from tools.sim_leader import Leader, _load_profile
    p = _load_profile(os.path.join(ROOT, "tools/sim_profiles/banmal_short_lead.json"))
    assert p["onboarding"]["smalltalk_more"] == "밥" and p["onboarding"]["intro_reply"] == "ㅇㅋ" and p["episodes"]     # 사례는 물려받는다
    texts = {it.get("text") for it in p["injections"]}
    assert {"뭔소리야", "ㅇㅋ", "놉"} <= texts and any(it.get("paste") for it in p["injections"])
    leader = Leader(p, stub=True, provider="claude")
    assert asyncio.run(leader.answer("시작해도 되겠습니까?", chapter=None, instr="DIAGNOSIS_INTRO", target_sub=None, bei_state=None)) == "ㅇㅋ"
    leader.history.append(("user", "작년 3월에 본부에서 교육 체계를 전면 개편하라고 했을 때 두 강사가 반대했어."))
    outs = [asyncio.run(leader.answer("그 뒤에 무엇이 달라졌습니까?", chapter="organization_management", instr="EPISODE_PROBE", target_sub=None, bei_state="episode"))
            for _ in range(9)]
    assert outs[1] == "뭔소리야" and outs[4] == "ㅇㅋ" and outs[8] == leader.history[0][1]   # 9번째 탐침 = 같은 답 붙여넣기


@pytest.mark.parametrize("coach_key", ["4"])
def test_stub_route_short_banmal_inputs(client, seed_data, monkeypatch, coach_key):
    """실제 라우트(스텁): 스몰톡 '밥' 고정 받기 · 합쇼체 안내 본문 · 'ㅇㅋ' 동의 · '뭔소리야' 다시 묻기(리더 턴 불변)."""
    monkeypatch.setenv("FM_LLM_STUB", "1")
    monkeypatch.setenv("FM_PREWARM", "0")
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    from diag_project.routes.diagnoses import COACH_UUID_TO_KEY
    coach_uuid = {v: k for k, v in COACH_UUID_TO_KEY.items()}[coach_key]
    login = client.post("/api/v1/participants/token", json={
        "email": f"p11-{uuid.uuid4().hex[:6]}@example.com", "password": "password", "name": "박기진", "group_code": "G-TEST"})
    assert login.status_code == 200, login.text
    hdr = {"Authorization": f"Bearer {login.json()['access_token']}"}
    start = client.post("/api/v1/diagnoses/start", json={"coach_id": coach_uuid, "participant_id": login.json()["participant_id"],
                                                         "template_id": "10000000-0000-0000-0000-000000000008", "force_new": True}, headers=hdr)
    assert start.status_code == 201, start.text
    sid = start.json()["session_id"]

    def say(text):
        r = client.post("/api/v1/diagnoses/submit_message", json={"session_id": sid, "diagnosis_id": sid, "content": text}, headers=hdr)
        assert r.status_code in (200, 201), r.text[:300]
        return r.json().get("coach_response_message") or "", (r.json().get("_phase3a_metadata") or {})

    say("안녕하세요, 박기진입니다.")
    t1, _ = say("그냥 그래")
    t2, m2 = say("밥")
    assert "여쭤봐 주신" not in t2 and "편하게 말씀" not in t2 and t2.startswith("알겠습니다.") and m2.get("probe_type_used") == "ROLE_ASK"
    assert t1.split()[0] != t2.split()[0]                                          # 두 턴의 고정 받기가 같은 한마디가 아니다
    say("교육팀장. 팀원 넷.")
    intro, mi = say("딱히 없어")
    assert mi.get("instruction_used") == "DIAGNOSIS_INTRO" and "안내드릴게요" not in intro and "이루어져 있습니다" in intro and intro.endswith("시작해도 되겠습니까?")
    conf, mc = say("ㅇㅋ")
    assert mc.get("instruction_used") == "DIAGNOSIS_CONFIRM" and "'네'라고" not in conf
    say("방향을 세우고 팀원이 스스로 움직이게 하는 일.")
    q1, _ = say("작년 3월에 본부에서 교육 체계를 전면 개편하라고 했을 때 김선임, 박선임 두 강사가 왜 바꾸냐고 반대했어.")
    q2, m2b = say("뭔소리야")
    assert m2b.get("bei") == "reask" and q2.startswith("제 질문이 분명하지 않았습니다.") and q2.endswith("?")
    q3, m3 = say("ㅇㅋ")
    assert m3.get("bei") in ("reask", "probe", "reframe") and "'네'라고" not in q3


# ── 검증 시뮬 p11a(Daniel × 반말·초단답, 2026-11-12) 전문에서 읽어 찾은 결함 ─────────────────────────
def test_p11a_followups_from_sim_transcript():
    from diag_project.services import turn_checks as T
    from diag_project.services.output_guard import find_praise
    from diag_project.services.persona_register import apply_register
    from diag_project.services.receive_check import quote_receive
    # ① 어미 변환 — '떠오르시나요?' 가 '떠오르시습니까?' 로 깨졌다
    assert apply_register("Daniel", "그때 처음 꺼내신 말이 무엇이었는지 떠오르시나요?", scope="questions")[0].endswith("떠오르십니까?")
    assert apply_register("Jessica", "그 장면을 어떻게 보시나요?", scope="questions")[0].endswith("보십니까?")
    # ② 열린 질문 + 고르게 하는 질문 → 열린 질문을 남긴다(종전: '수긍하는 쪽이었는지 들려주시겠습니까?')
    a = ("면담 전에 지연 건을 표로 정리해 보여주셨군요. 그 자리에서 이기획님이 그 표와 새 목표를 어떻게 받아들였는지 궁금합니다. "
         "반발이 있었는지, 아니면 수긍하는 쪽이었는지 들려주시겠습니까?")
    out, n = T.prefer_open_question(a)
    assert n == 1 and out.endswith("어떻게 받아들였는지 궁금합니다.") and "수긍하는 쪽" not in out
    assert T.prefer_open_question("그 회의에서 무엇을 먼저 말씀하셨습니까?")[1] == 0
    # ③ 예고 꼴로 끝난 유일한 질문은 묻는 꼴로
    assert T.request_to_question("이 상황에서 리더님께서 직접 하신 첫 행동이 무엇이었는지 여쭙고 싶습니다.", formal=True) == \
        "이 상황에서 리더님께서 직접 하신 첫 행동이 무엇이었는지 말씀해 주시겠습니까?"
    assert T.request_to_question("그날 어떤 말을 먼저 꺼냈는지 듣고 싶어요.", formal=False).endswith("꺼냈는지 들려주시겠어요?")
    assert T.request_to_question("두 분을 따로 부르셨군요.", formal=True) is None
    # ④ 다시 묻기 — 직전 질문을 뒤집어 고르게 하는 질문은 쓰지 않는다(직전 질문을 그대로 낸다)
    orig = "그 판단을 이기획님께 어떻게 전하셨는지 말씀해 주시겠습니까?"
    assert not T.reask_candidate_ok("이기획님이 판단을 알아들으셨는지, 아니면 그 자리에서는 말씀을 나누지 않으셨는지 들려주시겠습니까?", orig)
    assert not T.reask_candidate_ok("그 자리에서는 말씀을 나누지 않으셨는지 들려주시겠습니까?", orig)
    assert T.reask_candidate_ok("기록으로 보겠다는 판단을 이기획님께 어떤 말로 알려 주셨습니까?", orig)
    # ⑤ 짐작·감상 받기
    for s in ("팀 안에서도 그 결과를 함께 확인하는 순간이 있었을 것 같습니다.", "리더님께서 대표를 설득해 나가신 과정이 그려지네요.", "그 일로 고민이 있으셨을 것 같습니다."):
        assert T.receive_ban_reason(s) == "interpretive", s
    assert find_praise("그 표현이 와닿습니다.") and find_praise("규칙까지 만드셨다는 게 인상에 남습니다.")
    # ⑥ 반말 답도 구절로 받는다(여는 턴에 받기가 빠졌다)
    assert quote_receive("그날 저녁에 원인부터 쪼갰어. 다음 날 박선임이랑 교안부터 문서로 복원했어.") == "'박선임이랑 교안부터 문서로 복원했다'는 말씀이셨군요."
    assert quote_receive("운영 공수가 올해 안에 30% 정도 줄었고, 내년 전면 도입 예산도 그대로 승인됐어.").endswith("승인됐다'는 말씀이셨군요.")
    # ⑦ 기본 질문의 머리
    assert T.default_slot_question("criterion", formal=True, topic_text="작년 12월 평가 때 이기획한테 낮은 등급을 줘야 했어").startswith("말씀하신 '")
    src = _src("diag_project/routes/diagnoses.py")
    assert "_poq_t(txt)" in src and "_rco_rk(x, _orig_rk)" in src and '_tm["request_q"] = 1' in src
