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
    assert src.index("# 8-h.") < src.index("# 8-w.") < src.index("# 8-x.") < src.index("# 8-x2.") < src.index("# 8-y.")
    w = src[src.index("# 8-w."): src.index("# 8-x.")]
    assert "RECEIVE_REQUIRED_INSTRUCTIONS" in src and "check_receive as _chk_r" in w and "receive_fallback as _rfb" in w and "splice_receive as _spl_r" in w
    assert '_tm["receive_fix"] = 1' in w and '_tm["receive_fix"] = 2' in w and "keep_fixed=_fixed_w" in w
    # 되받기 상한은 리더 답 길이(150자)로
    assert "_clp(clean_reply, _lcf(_llm_user_text), _llm_user_text)" in src
    # 전환 턴: 되받기 1문장 + 페르소나 고정 다리 + 앵커
    j = src[src.index("# 8-j."): src.index("# 8-j.") + 6000]
    assert '"target_bridge")' in j and '_tm["target_bridge"] = 1' in j and "transition_bridge as _tbr)" not in j
    # 느낌표 챕터 상한
    h = src[src.index("# 8-h."): src.index("# 8-w.")]
    assert "EXCLAMATION_PER_CHAPTER as _epc" in h and '_tm["excl_chapter_cap"] = 1' in h
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
