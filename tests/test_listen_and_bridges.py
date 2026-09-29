"""2026-09-29 자기관리 재주행 4+1건: 지시어 허공·억지 다리·태도 진술·듣기·마무리·정의→앵커 다리."""
from diag_project.services.output_guard import (
    align_default_bridge, align_has_bridge, bare_demonstrative_questions, find_praise, key_noun_phrase,
    result_fallback_question, strip_frame_lead,
)
from diag_project.services.event_tracker import is_attitude_statement


def test_key_noun_phrase_from_real_utterances():
    assert key_noun_phrase("팀원들에게 회식하자고 했는데 아무도 안한대요") == "회식"
    assert key_noun_phrase("알겠다고 하고 회식을 안했죠 뭐") == "회식"
    assert key_noun_phrase("리더 자신이 중심을 잡는 것이고 일관성이 가장 중요해요") == "일관성"
    assert key_noun_phrase("그 뒤로는 오후 회의를 줄이고 집중 시간을 따로 잡았어요") == "집중 시간"


def test_result_fallback_has_no_bare_demonstrative():
    for u in ["알겠다고 하고 회식을 안했죠 뭐", "똑같이 생각하죠 뭐", "", "네"]:
        q = result_fallback_question(u)
        assert q.endswith("?")
        assert not bare_demonstrative_questions(q, u), q
        for pron in ("그것", "그럴 때", "그렇게"):
            assert pron not in q


def test_bare_demonstrative_detection():
    u = "저는 뒷끝이 없기에 그런것에 대해서 신경을 쓰지 않아요"
    assert bare_demonstrative_questions("네, 노력하시는 모습이 느껴집니다. 그럴 때는 어떠셨습니까?", u)
    assert bare_demonstrative_questions("팀원들은 그것을 어떻게 받아들였나요?", "강요는 서로 스트레스에요")
    assert not bare_demonstrative_questions("그 서운함을 팀원들에게 내비치셨나요?", "서운했죠. 근데 요즘은 다들 그러니까")
    assert not bare_demonstrative_questions("'회식'을 그렇게 하시니 팀원들은 어땠나요?", "회식을 안 했어요")


def test_attitude_statement():
    assert is_attitude_statement("저는 뒷끝이 없기에 그런것에 대해서 신경을 쓰지 않아요")
    assert is_attitude_statement("똑같이 생각하죠 뭐")
    assert not is_attitude_statement("알겠다고 하고 회식을 안했죠 뭐")          # 행동
    assert not is_attitude_statement("지난달 김대리에게 일정을 다시 짜 보라고 했어요")  # 시점·인물·행동
    assert not is_attitude_statement("팀원 세 명과 매주 1on1 을 하면서 우선순위를 다시 맞췄고, 그 뒤로 마감 지연이 절반으로 줄었습니다")


def test_align_bridge_and_frame_lead():
    llm = "'일관성'이 중요하다고 하셨군요.\n\n저희는 이렇게 봅니다. 세 가지를 살펴봅니다.\n· 자기인식\n· 회복탄력성\n· 중심성"
    assert not align_has_bridge(llm)
    br = align_default_bridge("Daniel (다니엘)", "리더 자신이 중심을 잡는 것이고 일관성이 가장 중요해요")
    assert "'일관성'" in br and not br.endswith("?")
    assert align_has_bridge(llm + "\n\n" + br)
    assert strip_frame_lead("먼저 하나 여쭤볼게요. 최근에 스스로를 돌아본 일이 있으셨어요?") == "최근에 스스로를 돌아본 일이 있으셨어요?"
    assert not bare_demonstrative_questions(br, "리더 자신이 중심을 잡는 것이고 일관성이 가장 중요해요")


def test_final_closing_distinct_and_no_praise():
    from diag_project.services.intro_messages import final_closing_message
    for p in ["Daniel (다니엘)", "Ella (엘라)", "Jessica (제시카)", "Olivia (올리비아)", "Michael (마이클)", "Lucas (루카스)", None]:
        m = final_closing_message(p)
        assert "리포트" in m and "진단 완료 및 결과 보기" in m
        assert "이어가 보겠습니다" not in m and not find_praise(m) and m.count("!") == 0


def test_layer1_heavy_has_listening_rule_and_budget():
    from diag_project.prompts.phase3a.layer1_system import LAYER1_SYSTEM_PROMPT, LAYER1_LIGHT
    assert "따라가기" in LAYER1_SYSTEM_PROMPT and "그 서운함을 팀원들에게" in LAYER1_SYSTEM_PROMPT
    assert "따라가기" not in LAYER1_LIGHT
    assert len(LAYER1_SYSTEM_PROMPT) < 4500


def test_layer3_force_result_uses_noun_phrase_not_pool_sentence():
    from diag_project.prompts.phase3a.layer3_state import format_turn_state_for_llm
    from diag_project.services.traversal import RESULT_PROBE_POOL
    st = {"chapter": "self_management", "turn_count": 3, "events_collected": 1, "events_with_star_70": 0,
          "current_event_id": None, "current_event_star_coverage": None, "has_contrary_probe": False,
          "avoidance_count_in_chapter": 0, "all_subcompetencies": [], "explored_subcompetencies": [],
          "unexplored_subcompetencies": [], "asked_in_chapter": [], "instruction_for_this_turn": "STAR_INCOMPLETE",
          "force_result_probe": True, "result_focus": "회식", "current_target_name": "자기인식"}
    txt = format_turn_state_for_llm(st)
    assert "'회식'" in txt
    assert not any(q in txt for q in RESULT_PROBE_POOL)


def test_demonstrative_with_own_referent_is_not_bare():
    q = "근래에 예상보다 크게 실패한 뒤 다시 무엇인가 해보려고 하셨을 때, 그때는 어떻게 하셨습니까?"
    assert not bare_demonstrative_questions(q, "알겠다고 하고 회식을 안했죠 뭐")
    assert bare_demonstrative_questions("그럴 때는 어떠셨습니까?", "없어요")


def test_contracted_demonstrative_is_bare():
    assert bare_demonstrative_questions("뒷끝이 없으시다는 말씀이시군요. 그럴 땐 어떠셨습니까?", "저는 뒷끝이 없기에 그런것에 대해서 신경을 쓰지 않아요")


def test_template_anchor_uses_transition_lead():
    from diag_project.services.output_guard import template_anchor
    assert template_anchor("최근에 그런 일이 있으셨어요?").startswith("다른 이야기를 하나 여쭤볼게요.")


def test_followup_from_user_is_specific():
    from diag_project.services.output_guard import followup_from_user
    q = followup_from_user("저는 뒷끝이 없기에 그런것에 대해서 신경을 쓰지 않아요")
    assert q.endswith("?") and not bare_demonstrative_questions(q, "저는 뒷끝이 없기에 그런것에 대해서 신경을 쓰지 않아요")
    assert followup_from_user("").endswith("?")


def test_filler_bridge_stripped_on_anchor_and_newlines_preserved():
    from diag_project.services.output_guard import strip_filler_bridge, strip_sub_name_mentions
    t = "네, 중재를 직접 주도하셨다고 하셨습니다. 그런 경험처럼, 혹시 비효율인 걸 알면서도 다들 하던 절차를 바꾸신 적은 없으셨습니까?"
    out, hit = strip_filler_bridge(t)
    assert hit and "그런 경험처럼" not in out and "다른 이야기를 하나 여쭤볼게요." in out and out.endswith("?")
    para = "정의 문장입니다.\n· 갈등관리\n· 신뢰형성\n\n'변화관리'와 관련하여, 그때 어떻게 하셨습니까?"
    out2, _ = strip_sub_name_mentions(para, ["변화관리(변화지향)"])
    assert "\n· 갈등관리\n· 신뢰형성\n\n" in out2


def test_strip_praise_keeps_paragraphs():
    from diag_project.services.output_guard import strip_praise
    t = "말씀 참 인상적입니다. 저희는 이렇게 봅니다.\n· 자기인식\n· 회복탄력성\n\n'일관성'이 시험받았던 장면부터 여쭤볼게요."
    out, n = strip_praise(t)
    assert n == 1 and "인상적" not in out and "\n· 자기인식\n· 회복탄력성\n\n" in out


def test_align_list_guarantee_and_no_keyword_bridge():
    from diag_project.services.output_guard import ensure_align_list, align_default_bridge, strip_filler_bridge
    t = "네, 좋습니다.\n\n저희는 성과관리를 이렇게 봅니다. 다섯 가지를 살펴봅니다."
    out, added = ensure_align_list(t, ["목표설정 및 공유", "실행력"])
    assert added and "\n· 목표설정 및 공유\n· 실행력" in out
    assert ensure_align_list(out, ["목표설정 및 공유"])[1] is False
    br = align_default_bridge("Daniel (다니엘)", "네")
    assert "말씀하신 '" not in br and br.endswith(".")
    out2, hit = strip_filler_bridge("장기적인 가치를 선택하셨군요. 이처럼 지쳐서 손을 놓은 팀원을 다시 움직이게 하신 적이 있으셨습니까?")
    assert hit and not out2.split(". ")[-1].startswith("이처럼")


def test_align_body_questions_removed_keep_layout():
    from diag_project.services.output_guard import drop_question_sentences
    t = "정의입니다.\n· 갈등관리\n· 신뢰형성\n말씀하신 것과 크게 다르지 않지요?\n\n'본질'에서 출발해 보겠습니다."
    out, n = drop_question_sentences(t)
    assert n == 1 and "?" not in out and "\n· 갈등관리\n· 신뢰형성" in out and out.endswith("보겠습니다.")


def test_prewarm_scheduled_after_commit_and_eta_in_final_closing():
    import inspect
    from diag_project.routes import diagnoses as d
    src = inspect.getsource(d._submit_message_phase3a)
    i_commit = src.index("await db.commit()\n    except Exception as _ce:")
    i_prewarm = src.index("schedule_chapter_prewarm(str(session.id), chapter)")
    assert i_commit < i_prewarm                                   # 커밋 뒤에 예약
    assert "estimate_label(_n_ready)" in src and "정도면 준비됩니다" in src
