"""(2026-11-04 P3) 대화 품질 — 되받기 필수(8-w)·슬롯 재배치(P3-2)·전환 다리(P3-3)·Michael 어미 구어체(P3-4)·인사 시각(P3-5)."""
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GEMINI_API_KEYS", "dummy")

from diag_project.services import receive_check as RC  # noqa: E402

LEADER = "신입 교육을 온라인 사전학습으로 바꾸고, 한 과정 시범 운영 뒤 현업 활용 설문으로 효과를 확인했습니다."


def test_receive_check_statements_and_quotes():
    assert RC.lead_cap_for("짧은 답") == 1 and RC.lead_cap_for("가" * 150) == 2 and RC.lead_cap_for(None) == 1
    assert RC.receive_statements("그 뒤에는 어떻게 됐어요?") == []
    assert RC.receive_statements("온라인으로 바꾸셨군요. 설문까지 하셨고요. 그 뒤에는요? 그리고요?") == ["온라인으로 바꾸셨군요.", "설문까지 하셨고요."]
    assert "현업" in RC.leader_nouns(LEADER) and "사전학습" in RC.leader_nouns(LEADER) and "저희" not in RC.leader_nouns("저희 팀은요")
    assert RC.check_receive("그 뒤에는 어떻게 됐어요?", LEADER) == (False, False)
    assert RC.check_receive("그러셨군요. 그 뒤에는요?", LEADER) == (True, False)
    assert RC.check_receive("온라인 사전학습으로 먼저 바꾸셨군요. 그 뒤에는 어떻게 됐어요?", LEADER) == (True, True)
    assert RC.check_receive("그러셨군요. 그 뒤에는요?", "네") == (True, True)            # 리더 답에 명사가 없으면 인용 요건 면제
    assert RC.quote_phrase(LEADER) == "현업 활용"                                          # 마지막 2어절 명사구 우선
    # (2차) 부사·접속사·활용형은 명사가 아니다 — p3q 1차 인용구 '아니라 교육'·'특히 교육'·'구성해야 하니'
    u8 = "만족도뿐 아니라 교육 후 현업에서 얼마나 활용하는지도 목표에 포함하도록 바꿨습니다. 단순히 교육을 잘 마치는 것보다 실제 업무에 도움이 되는 교육을 만드는 쪽으로 방향을 다시 잡았어요."
    ns = RC.leader_nouns(u8)
    assert not ({"아니라", "특히", "다른", "구성해야", "하니", "얼마나", "단순히", "실제", "예전에", "처음에", "되는", "점이", "중에", "질문하", "마치", "만드"} & set(ns)), ns
    assert not ({"더해져", "느낀", "줄일", "나눠"} & set(RC.leader_nouns("기존 교육 준비에 새로운 업무까지 더해져 팀원들이 부담을 느낀 적이 있어요. 줄일 수 있는 부분은 줄이고 업무를 나눠 맡았어요.")))
    assert "현업" in ns and "목표" in ns and RC.quote_phrase(u8) not in (None, "아니라 교육")
    assert "다른" not in RC.leader_nouns("다른 교육에도 적용할 수 있는지 검토해 보자고 제안했어요.")
    assert RC.leader_nouns("기존 교육 자료를 온라인 사전학습용 자료까지 별도로 구성해야 하니 업무가 늘어난다는 점이었어요.")[:3] == ["기존", "교육", "자료"]
    assert RC.quote_phrase("설문을 돌렸습니다") == "설문" and RC.quote_phrase("네") is None
    assert RC.receive_fallback("Michael", "현업 활용") == "'현업 활용'까지 말씀해 주셨네요."
    assert RC.receive_fallback("Jessica", "현업 활용") == "'현업 활용'까지 말씀해 주셨습니다."
    assert RC.receive_fallback("Lucas", None) == "알겠습니다." and RC.receive_fallback("Ella (엘라)", None).endswith("들었어요.")


def test_splice_receive_keeps_question_part_and_fixed_lines():
    # 질문부(사다리·슬롯 질문)는 그대로, 되받기만 교체. 고정 문장(응원·관찰·다리)은 새 되받기 뒤에 보존.
    out = RC.splice_receive("그러셨군요. 그 선택, 응원합니다. 다음에 비슷한 상황이 오면 어떻게 하실 생각이세요?",
                            "'현업 활용'까지 말씀해 주셨네요.", 1, keep_fixed=["그 선택, 응원합니다."])
    assert out == "'현업 활용'까지 말씀해 주셨네요. 그 선택, 응원합니다. 다음에 비슷한 상황이 오면 어떻게 하실 생각이세요?"
    out = RC.splice_receive("그 뒤에는 어떻게 됐어요?", "온라인으로 바꾸셨군요. 설문도 하셨고요. 질문은요?", 2)
    assert out == "온라인으로 바꾸셨군요. 설문도 하셨고요. 그 뒤에는 어떻게 됐어요?"
    out = RC.splice_receive("네. 있었다면 어떻게 설득하셨습니까? 결과는요?", "'현업 활용'까지 말씀해 주셨습니다.", 1)
    assert out.startswith("'현업 활용'까지 말씀해 주셨습니다.") and out.endswith("결과는요?")


def test_pipeline_wiring_receive_required_slot_bridge_exclamation():
    from diag_project.routes import diagnoses as d
    src = inspect.getsource(d._submit_message_phase3a)
    # (2차) 8-w 는 8-o 한 질문 뒤·8-p 좋습니다 가드 앞 — 재생성 되받기도 좋습니다·느낌표 가드를 거친다
    assert src.index("# 8-o.") < src.index("# 8-w.") < src.index("# 8-p.") < src.index("# 8-h.") < src.index("# 8-x.") < src.index("# 8-x2.") < src.index("# 8-y.")
    w = src[src.index("# 8-w."): src.index("# 8-p.")]
    assert "RECEIVE_REQUIRED_INSTRUCTIONS" in src and "check_receive as _chk_r" in w and "receive_fallback as _rfb" in w and "splice_receive as _spl_r" in w
    assert '_tm["receive_fix"] = 1' in w and '_tm["receive_fix"] = 2' in w and "keep_fixed=_fixed_w" in w
    # 되받기 상한은 리더 답 길이(150자)로
    assert "_clp(clean_reply, _lcf(_llm_user_text), _llm_user_text)" in src
    # 전환 턴: 되받기 1문장 + 페르소나 고정 다리 + 앵커
    j = src[src.index("# 8-j."): src.index("# 8-j.") + 6000]
    assert "target_bridge_line as _tbl_j" in j and '_tm["target_bridge"] = 1' in j and "transition_bridge as _tbr)" not in j
    # 느낌표 챕터 상한
    h = src[src.index("# 8-h."): src.index("# 8-x.")]
    assert "EXCLAMATION_PER_CHAPTER as _epc" in h and '_tm["excl_chapter_cap"] = 1' in h
    # (2차) 옛 리드 1문장 상한은 P3-1 상한으로, 전환 다리·슬롯 턴 제외; 8-n 재삽입은 고정 다리
    assert 'if _is_probe and not _tm.get("target_bridge") and not _tm.get("slot"):' in src and "cap_lead_sentences(clean_reply)" not in src
    assert "transition_bridge as _tbr_n" not in src and "_tbl_n((state.get('coach_persona') or {}).get('name'), _bridge_idx())" in src
    # (2차) 8-n 입버릇: 고정 문장은 집계에서 빼고, 앵커·사다리·슬롯 턴의 재생성은 되받기만 교체
    assert "_sans_fixed(txt)" in src and "_spl_n(clean_reply, _t_txt, _lcf_n(_llm_user_text), keep_fixed=_fixed_n) if _keep_q_n else _t_txt" in src
    assert src.index("_sans_fixed(txt)") < src.index("# 8-w.")
    # 원장: Michael 실행 의지 질문 대기·해제, 느낌표 챕터 누적, guard_log 키
    assert '_gl_store["michael_q_pending"] = _mqp' in src and '_gl_store["excl_by_chapter"] = _exc' in src
    assert '"receive_fix": _tm.get("receive_fix")' in src and '"excl_chapter_cap"' in src
    from diag_project.services.style_tracker import EXCLAMATION_PER_CHAPTER
    assert EXCLAMATION_PER_CHAPTER == 2
    assert RC.RECEIVE_REQUIRED_INSTRUCTIONS >= {"STAR_INCOMPLETE", "CONTINUE_NORMAL", "CONTRARY_NEEDED", "STAR_COMPLETE_NEW_EVENT"}


def test_michael_endings_colloquial_no_recall_form_and_bridges():
    from diag_project.services import persona_voice as V
    from diag_project.services.intro_messages import PERSONA_LINES
    for tbl in (V._MICHAEL_ENDINGS, V._OLIVIA_ENDINGS, V._LUCAS_CUTS):
        assert not any("던가요" in r for _, r in tbl)
    assert not any("던가요" in j or "던가요" in dn for _, j, dn in V._ENDINGS)
    # (2026-11-04 P3-4 2차) 요청형 — 사용자 지정 4형
    assert V.voice_question("Michael", "그때 어떤 일이었나요?") == "그때 어떤 일이었는지 들려주세요."
    assert V.voice_question("Michael", "어떻게 하셨어요?") == "그때 어떻게 하셨는지 들려주세요."
    assert V.voice_question("Michael", "그 일은 어떻게 하셨습니까?") == "그 일은 어떻게 하셨는지 들려주세요."
    assert V.voice_question("Michael", "그 뒤에는 어떻게 됐어요?") == "그 뒤 어떻게 됐는지도요."
    assert V.voice_question("Michael", "비슷한 장면이 최근에 있으셨나요?") == "비슷한 장면이 최근에 있으셨는지 들려주세요."
    assert V.voice_question("Michael", "팀 목표를 다시 세우신 뒤 팀원들과 같이 하신 적이 있었어요?") == "팀 목표를 다시 세우신 뒤 팀원들과 같이 직접 하셨던 일, 하나만 들려주세요."
    assert V.voice_question("Michael", "팀원 둘 사이 갈등을 중재하신 경험이 최근에 있으실까요?") == "최근에 팀원 둘 사이 갈등을 중재하셨던 경험, 하나만 들려주세요."
    from diag_project.services.output_guard import is_question, keep_last_question
    assert is_question("그 뒤 어떻게 됐는지도요.") and is_question("맞추셨던 일, 하나만 들려주세요.")
    assert keep_last_question("A 하셨군요. 어떤 일이었는지 들려주세요. 그 뒤 어떻게 됐는지도요.")[1] == 1
    bridges = {k: v["target_bridge"] for k, v in PERSONA_LINES.items()}
    assert len(bridges) == 6 and all(bridges.values()) and len(set(bridges.values())) == 6
    assert bridges["Michael"] == "자, 다음은 다른 쪽이에요." and bridges["Ella"].startswith("이번엔")


def test_name_extraction_allows_space_before_ending():
    from diag_project.services.instruction_decider import _extract_user_name as X
    assert X("안녕하세요 박기진 입니다.") == "박기진" and X("안녕하세요 박기진입니다") == "박기진" and X("박기진이라고 합니다") == "박기진"
    assert X("안녕하세요") is None and X("안녕하세요 입니다") is None


def test_greeting_question_by_daypart():
    from datetime import datetime, timedelta, timezone
    from diag_project.services.time_greeting import build_rapport_first_turn_response, get_time_greeting
    KST = timezone(timedelta(hours=9))
    g = get_time_greeting(datetime(2026, 11, 4, 11, 30, tzinfo=KST))
    assert g["ampm_phrase"] == "오전 마무리" and g["greeting_question"] == "오전 마무리는 어떠세요?"
    assert get_time_greeting(datetime(2026, 11, 4, 12, 10, tzinfo=KST))["greeting_question"] == "오늘 점심 시간은 어떻게 보내고 계세요?"
    assert get_time_greeting(datetime(2026, 11, 4, 13, 35, tzinfo=KST))["ampm_phrase"] == "오후"
    assert build_rapport_first_turn_response("박기진", g["ampm_phrase"], greeting_question=g["greeting_question"]).endswith("오전 마무리는 어떠세요?")
    assert build_rapport_first_turn_response("박기진", "오후").endswith("오늘 오후 시간은 어떻게 보내고 계세요?")
    from diag_project.services import instruction_decider as ID
    assert 'state["current_greeting_question"]' in inspect.getsource(ID)


# ── (2026-11-04 P3 3차) 반복 분산 · 깨진 문장 · 권유문 ─────────────────────────────────

def test_anchor_tail_three_variants_per_persona():
    from diag_project.services import persona_voice as V
    from diag_project.services.output_guard import count_questions, is_question
    anchors = ["새로운 방향에 확신이 서지 않던 팀원들과 뜻을 맞추신 일, 최근에 있으셨어요?",
               "그 방향을 팀과 같이 앉아 구체적인 계획으로 만든 적이 있었어요?",
               "팀원 둘 사이 갈등을 중재하신 경험이 최근에 있으실까요?"]
    for p in ["Ella", "Jessica", "Olivia", "Daniel", "Michael", "Lucas"]:
        for q in anchors:
            outs = [V.voice_question(p, q, variant=v) for v in (0, 1, 2)]
            assert len(set(outs)) == 3, (p, outs)
            assert all(is_question(o) and count_questions(o) == 1 for o in outs), (p, outs)
            assert V.voice_question(p, q, variant=3) == outs[0]
    m = [V.voice_question("Michael", anchors[0], variant=v) for v in (0, 1, 2)]
    assert m[0].endswith("맞추셨던 일, 하나만 들려주세요.") and m[1].endswith("맞추셨던 일, 떠오르는 게 있으세요?")
    assert m[2].endswith("맞추신 적, 기억나는 일 있으면 얘기해 주세요.")
    b = [V.voice_question("Michael", "최근에 정보가 부족한데도 중요한 결정을 내려야 했을 때, 어떻게 하셨어요?", variant=v) for v in (0, 1, 2)]
    assert b[0].endswith("하셨는지 들려주세요.") and b[1].endswith("하셨는지 떠오르는 대로 말씀해 주세요.") and b[2].endswith("하셨는지 기억나는 대로 얘기해 주세요.")
    assert V.voice_question("Lucas", anchors[0], variant=1).endswith("맞추신 일, 최근 떠오르는 게 있나요?")


def test_target_bridges_three_per_persona_and_rotation():
    from diag_project.services.intro_messages import PERSONA_LINES, target_bridge_line, target_bridge_lines
    allb = []
    for p, v in PERSONA_LINES.items():
        tb = target_bridge_lines(p)
        assert len(tb) == 3 and tb[0] == v["target_bridge"], p
        allb += tb
    assert len(set(allb)) == 18
    assert target_bridge_lines("Michael (마이클)") == ["자, 다음은 다른 쪽이에요.", "이번엔 방향을 바꿔볼게요.", "다른 장면으로 넘어가요."]
    assert [target_bridge_line("Michael", i) for i in (0, 1, 2, 3)] == target_bridge_lines("Michael") + ["자, 다음은 다른 쪽이에요."]


def test_broken_sentence_and_suggestion_strip():
    from diag_project.services.output_guard import (broken_statements, count_questions, is_broken_sentence, is_question,
                                                    replace_broken_statements, strip_suggestion_statements)
    assert is_broken_sentence("네, 교육생 참여 변화와 운영 부담을 함께 보셨다는 점이 이에요.")
    assert is_broken_sentence("그 방향을 팀에.") and is_broken_sentence("결국 팀원들이 입니다.")
    assert not is_broken_sentence("그 선택, 응원합니다.") and not is_broken_sentence("팀원들과 계획을 세우셨군요.")
    assert not is_broken_sentence("그 뒤에는 어떻게 됐어요?") and not is_broken_sentence("이제 '성과관리'로 바로 가 보겠습니다.")
    txt = "네, 함께 보셨다는 점이 이에요. 이제 '성과관리'로 바로 가 보겠습니다."
    assert broken_statements(txt) == ["네, 함께 보셨다는 점이 이에요."]
    assert replace_broken_statements(txt, "교육 효과와 운영 부담을 함께 보셨군요. 질문인가요?") == "교육 효과와 운영 부담을 함께 보셨군요. 이제 '성과관리'로 바로 가 보겠습니다."
    assert replace_broken_statements(txt, "") == "이제 '성과관리'로 바로 가 보겠습니다."
    out, n = strip_suggestion_statements("그 판단 기준이 흥미롭네요. 현업 활용이 기대만큼 안 나오는 장면을 떠올려 주셔도 좋아요. 그 방향을 계획으로 만든 적이 있었는지 들려주세요.")
    assert n == 1 and out == "그 판단 기준이 흥미롭네요. 그 방향을 계획으로 만든 적이 있었는지 들려주세요."
    assert strip_suggestion_statements("편하게 떠올려 보셔도 돼요?")[1] == 0   # 질문은 보존
    assert is_question("기억나는 일 있으면 얘기해 주세요.") and count_questions("기억나는 일 있으면 얘기해 주세요.") == 1
    assert is_question("기억나는 일이 있으면 말씀해 주십시오.") and is_question("기억나는 일 있으면요?")
    # splice 도 권유문을 되받기로 세지 않는다
    assert RC.splice_receive("그 뒤에는요?", "온라인으로 바꾸셨군요. 장면을 떠올려 주셔도 좋아요. 설문도 하셨고요.", 2) == "온라인으로 바꾸셨군요. 설문도 하셨고요. 그 뒤에는요?"


def test_pipeline_wiring_rotation_broken_suggestion():
    from diag_project.routes import diagnoses as d
    src = inspect.getsource(d._submit_message_phase3a)
    assert src.count("variant=_vv_total()") == 4 and "def _vv_total()" in src
    assert "_tbl_j((state.get(\"coach_persona\") or {}).get(\"name\"), _bridge_idx())" in src and '_gl_store["bridge_idx"] = (int(_gl_store.get("bridge_idx") or 0) + 1) % 3' in src
    assert "*_tbls_w(_pn_w)" in src and "*_tbls_n(_pn_n)" in src
    assert "if _bks(clean_reply):" in src and '_tm["broken_fix"] = 1 if _bk_new else 2' in src and '"broken_fix": _tm.get("broken_fix")' in src
    assert "clean_reply, _n_sug = _sss_c(clean_reply)" in src and src.index("# 8-j.") < src.index("_sss_c(clean_reply)") < src.index("# 8-n.")
