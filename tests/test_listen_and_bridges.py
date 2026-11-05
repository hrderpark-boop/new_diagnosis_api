"""2026-09-29 자기관리 재주행 4+1건: 지시어 허공·억지 다리·태도 진술·듣기·마무리·정의→앵커 다리."""
from diag_project.services.output_guard import (bare_demonstrative_questions, find_praise, strip_frame_lead)






def test_bare_demonstrative_detection():
    u = "저는 뒷끝이 없기에 그런것에 대해서 신경을 쓰지 않아요"
    assert bare_demonstrative_questions("네, 노력하시는 모습이 느껴집니다. 그럴 때는 어떠셨습니까?", u)
    assert bare_demonstrative_questions("팀원들은 그것을 어떻게 받아들였나요?", "강요는 서로 스트레스에요")
    assert not bare_demonstrative_questions("그 서운함을 팀원들에게 내비치셨나요?", "서운했죠. 근데 요즘은 다들 그러니까")
    assert not bare_demonstrative_questions("'회식'을 그렇게 하시니 팀원들은 어땠나요?", "회식을 안 했어요")






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




def test_demonstrative_with_own_referent_is_not_bare():
    q = "근래에 예상보다 크게 실패한 뒤 다시 무엇인가 해보려고 하셨을 때, 그때는 어떻게 하셨습니까?"
    assert not bare_demonstrative_questions(q, "알겠다고 하고 회식을 안했죠 뭐")
    assert bare_demonstrative_questions("그럴 때는 어떠셨습니까?", "없어요")


def test_contracted_demonstrative_is_bare():
    assert bare_demonstrative_questions("뒷끝이 없으시다는 말씀이시군요. 그럴 땐 어떠셨습니까?", "저는 뒷끝이 없기에 그런것에 대해서 신경을 쓰지 않아요")




def test_followup_from_user_is_specific():
    from diag_project.services.output_guard import followup_from_user
    q = followup_from_user("저는 뒷끝이 없기에 그런것에 대해서 신경을 쓰지 않아요")
    assert q.endswith("?") and not bare_demonstrative_questions(q, "저는 뒷끝이 없기에 그런것에 대해서 신경을 쓰지 않아요")
    assert followup_from_user("").endswith("?")




def test_strip_praise_keeps_paragraphs():
    from diag_project.services.output_guard import strip_praise
    t = "말씀 참 인상적입니다. 저희는 이렇게 봅니다.\n· 자기인식\n· 회복탄력성\n\n'일관성'이 시험받았던 장면부터 여쭤볼게요."
    out, n = strip_praise(t)
    assert n == 1 and "인상적" not in out and "\n· 자기인식\n· 회복탄력성\n\n" in out




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
