"""(2026-11-04 P3) 대화 품질 — 되받기 필수(8-w)·슬롯 재배치(P3-2)·전환 다리(P3-3)·Michael 어미 구어체(P3-4)·인사 시각(P3-5)."""
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GEMINI_API_KEYS", "dummy")

from diag_project.services import receive_check as RC  # noqa: E402

LEADER = "신입 교육을 온라인 사전학습으로 바꾸고, 한 과정 시범 운영 뒤 현업 활용 설문으로 효과를 확인했습니다."




def test_splice_receive_keeps_question_part_and_fixed_lines():
    # 질문부(사다리·슬롯 질문)는 그대로, 되받기만 교체. 고정 문장(응원·관찰·다리)은 새 되받기 뒤에 보존.
    out = RC.splice_receive("그러셨군요. 그 선택, 응원합니다. 다음에 비슷한 상황이 오면 어떻게 하실 생각이세요?",
                            "'현업 활용'까지 말씀해 주셨네요.", 1, keep_fixed=["그 선택, 응원합니다."])
    assert out == "'현업 활용'까지 말씀해 주셨네요. 그 선택, 응원합니다. 다음에 비슷한 상황이 오면 어떻게 하실 생각이세요?"
    out = RC.splice_receive("그 뒤에는 어떻게 됐어요?", "온라인으로 바꾸셨군요. 설문도 하셨고요. 질문은요?", 2)
    assert out == "온라인으로 바꾸셨군요. 설문도 하셨고요. 그 뒤에는 어떻게 됐어요?"
    out = RC.splice_receive("네. 있었다면 어떻게 설득하셨습니까? 결과는요?", "'현업 활용'까지 말씀해 주셨습니다.", 1)
    assert out.startswith("'현업 활용'까지 말씀해 주셨습니다.") and out.endswith("결과는요?")






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
    assert src.count("variant=_vv_total()") >= 1 and "def _vv_total()" in src          # 어미 변주는 세션 누적
    # (2026-11-04 BEI) 사례 단계 배선: 슬롯 판정 → 종료·매핑 → 카드. 전환 다리·사다리·일반화·결과 폴백은 없다.
    assert "_judge_slots(llm, transcript=" in src and "_map_episode(llm, transcript=" in src and 'state["bei_card"] = _bec(' in src
    assert "_bei.restore(_pst, _ledger_snapshot)" in src
    # (s2a 교정) 사례 경계에서 Michael 실행 의지 대기 해제 · 슬롯이 겨냥하는 슬롯이 찼으면 슬롯 생략 · SWEEP 앵커는 여는 질문과 다른 문안
    assert '_mqp_o.pop(chapter, None)' in src and '_slot_target.get(_pn_s) not in _filled_s' in src and 'alt=(instruction_used == "SWEEP_ANCHOR"' in src
    for gone in ("target_bridge_line", "force_ladder_probe", "result_fallback_question", "receive_fallback(", "cap_leads_persona"):
        assert gone not in src, gone
    # 깨진 문장 재생성(8-i 칭찬 분기)·권유문 제거는 유지
    assert "replace_broken_statements" in src and "strip_suggestion_statements" in src
    # 순서: 8-i → 8-n → 8-w(턴 형식) → 8-s(슬롯) → 8-p → 8-h → 8-x2 → 8-y → 8-z → 9
    assert (src.index("# 8-i.") < src.index("# 8-n.") < src.index("# 8-w.") < src.index("# 8-s.") < src.index("# 8-p.")
            < src.index("# 8-h.") < src.index("# 8-x2.") < src.index("# 8-y.") < src.index("# 8-z.") < src.index("# 9. 사례 행"))