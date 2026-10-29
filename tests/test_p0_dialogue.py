"""2026-10-28 P0(파일럿 차단 버그) 회귀 테스트 — ALIGN 결정론 조립·입력 이상·앵커 어미·질문 잘림·시간 인사."""
import itertools
import re
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from diag_project.data.competencies import COMPETENCY_FRAMEWORK, SUBCOMPETENCY_ANCHOR_QUESTIONS
from diag_project.services import input_anomaly as IA
from diag_project.services.align_render import align_shape_ok, receive_sentences, render_align
from diag_project.services.intro_messages import PERSONA_LINES
from diag_project.services.output_guard import cap_lead_sentences, is_question, starts_without_main_clause
from diag_project.services.persona_voice import voice_question
from diag_project.services.time_greeting import daypart, get_time_greeting, get_time_phrase

NAMES = ["Ella", "Jessica", "Olivia", "Daniel", "Michael", "Lucas"]
KST = ZoneInfo("Asia/Seoul")


def _subs(chapter):
    return [i["name"] for i in COMPETENCY_FRAMEWORK[chapter]["indicators"].values()]


# ── P0-1 ALIGN 결정론 조립 ────────────────────────────────────────────────────

@pytest.mark.parametrize("chapter", list(COMPETENCY_FRAMEWORK.keys()))
@pytest.mark.parametrize("persona", NAMES)
def test_render_align_shape_every_chapter_every_persona(chapter, persona):
    """챕터 크기(3~9개)와 무관하게 목록 전부·질문 1개·확인 질문 없음."""
    llm = ("리더님 말씀처럼 방향을 함께 세우는 게 핵심이죠. 그 결을 저희도 같이 봅니다. 크게 다르지 않죠? "
           "구체적으로는 네 가지를 살펴볼게요.\n· 엉뚱한 목록\n먼저 어느 쪽부터 볼까요?")
    out = render_align(llm_text=llm, chapter=chapter, sub_names=_subs(chapter), persona_name=persona,
                       bridge_sub_key=None, bridge_sub_name=_subs(chapter)[0],
                       anchor=voice_question(persona, "최근에 방향을 새로 잡으신 적이 있었어요?"))
    ok, why = align_shape_ok(out, _subs(chapter))
    assert ok, (out, why)
    assert "크게 다르지 않" not in out and "엉뚱한 목록" not in out and "어느 쪽" not in out
    assert out.count("?") == 1
    assert COMPETENCY_FRAMEWORK[chapter]["description"].rstrip(".")[:12] in out    # 고정 정의 1문장


def test_render_align_blocks_other_chapter_guide_and_choice_handing():
    """Lucas 일관리에 유입된 '조직을 효과적으로…' 류와 Daniel 의 '가장 자주 쓰시는 쪽부터' 류는 되받기에서 제거."""
    recv = receive_sentences(
        "조직관리에서 보셨듯 비전과 전략을 세우는 일이 중요하죠. 일정 관리가 늘 고민이라고 하셨죠. "
        "가장 자주 쓰시는 쪽부터 함께 들여다보겠습니다. 업무계획 및 조직력, 자원 및 시간관리를 보겠습니다.",
        chapter="work_management", sub_names=_subs("work_management"))
    assert recv == ["일정 관리가 늘 고민이라고 하셨죠."]


def test_render_align_fallback_when_llm_gave_only_questions():
    out = render_align(llm_text="정말요? 어떻게요?", chapter="self_management", sub_names=_subs("self_management"),
                       persona_name="Daniel", bridge_sub_key=None, bridge_sub_name="자기인식", anchor="그런 순간이 있었습니까?")
    assert out.startswith(PERSONA_LINES["Daniel"]["align_receive_fallback"])
    assert align_shape_ok(out, _subs("self_management"))[0]


def test_persona_lines_have_all_new_keys():
    keys = ["align_definition", "align_guide", "align_receive_fallback", "reask_anchor", "same_input", "repeat_event",
            "question_returned", "confirm_reask", "definition_reask", "continue_ack", "align_bridge"]
    for p in NAMES:
        assert all(k in PERSONA_LINES[p] for k in keys), p
        assert "{phrase}부터" in PERSONA_LINES[p]["align_bridge"]
        assert "{n}" in PERSONA_LINES[p]["align_guide"]


# ── P0-3 페르소나 어미: 6명 간 동일 앵커 0 ──────────────────────────────────────

def test_all_dictionary_anchors_differ_across_six_personas():
    qs = [q for lst in SUBCOMPETENCY_ANCHOR_QUESTIONS.values() for q in (lst if isinstance(lst, list) else [lst])]
    norm = lambda s: re.sub(r"[\s.,!?…'\"()]", "", s)  # noqa: E731
    same = [(a, b, q) for q in qs for a, b in itertools.combinations(NAMES, 2) if norm(voice_question(a, q)) == norm(voice_question(b, q))]
    assert same == [], same[:5]
    for q in qs:
        for n in NAMES:
            assert voice_question(n, q).count("?") == 1


# ── P0-4·P0-7 입력 이상 판정 ────────────────────────────────────────────────────

COACH = "들어 보니 그 상황이 그려지네요.\n\n먼저 방향 쪽부터요.\n\n최근에 팀 목표를 다시 세우신 적이 있었어요?"


def _detect(user, prev_user="", earlier=(), prev_instr="STAR_INCOMPLETE", coach=COACH, events=(), **kw):
    base = dict(user_text=user, prev_user_text=prev_user, earlier_user_texts=list(earlier), prev_coach_text=coach,
                prev_instruction=prev_instr, event_texts=list(events), pause_pending=False, awaiting_choice=False,
                definition_reasked=False)
    base.update(kw)
    return IA.detect(**base)


def test_ack_after_anchor_reasks_anchor():
    for u in ("네", "넵", "네?", "??", "sp", "ㅇㅇ"):
        a = _detect(u, prev_instr="COMPETENCY_ALIGN")
        assert a and a.kind == "ack_reask" and a.question.endswith("있었어요?"), u


def test_ack_is_not_reasked_where_consent_is_expected():
    assert _detect("네", prev_instr="CHAPTER_READY_TO_END") is None
    assert _detect("네", prev_instr="AWAIT_NEXT_CHAPTER_CHOICE") is None
    assert _detect("네", prev_instr="COMPETENCY_ALIGN", awaiting_choice=True) is None


def test_repeat_previous_and_session_duplicate():
    ans = "지난달에 신규 프로젝트 일정을 다시 짜면서 팀원들과 우선순위를 조정했습니다."
    assert _detect(ans, prev_user=ans).kind == "repeat_prev"
    assert _detect(ans + " ", prev_user=ans).kind == "repeat_prev"
    assert _detect(ans, prev_user="다른 답", earlier=["무관", ans]).kind == "repeat_any"       # 세션 앞 답변 복사(P0-7)
    ev = "신규 프로젝트 일정을 다시 짜면서 팀원들과 우선순위를 조정했습니다 결과 일정 준수"
    assert _detect(ans, prev_user="다른 답", events=[ev]).kind == "repeat_any"               # 기존 사건과 중복
    assert _detect("완전히 다른 이야기입니다. 작년에 신입 두 명을 멘토링했어요.", prev_user=ans) is None


def test_returned_question_and_pause_phrase():
    assert _detect("최근에 팀 목표를 다시 세우신 적이 있었어요?").kind == "returned_q"
    assert _detect("괜찮아요, 계속 진행할게요.").kind == "pause_phrase"
    assert _detect("괜찮아요, 계속 진행할게요.", pause_pending=True) is None


def test_confirm_and_definition_reask():
    a = _detect("sp", prev_instr="DIAGNOSIS_INTRO", coach="안내입니다. 시작해볼까요?")
    assert a and a.kind == "confirm_reask"
    assert _detect("네", prev_instr="DIAGNOSIS_INTRO", coach="안내입니다. 시작해볼까요?") is None   # '네' 는 정상 동의
    d = _detect("?", prev_instr="COMPETENCY_ASK", coach="리더님께서는 조직관리를 무엇이라고 생각하시나요?")
    assert d and d.kind == "def_reask"
    assert _detect("?", prev_instr="COMPETENCY_ASK", coach="정의요?", definition_reasked=True) is None
    assert _detect("구성원이 같은 방향을 보게 하는 것", prev_instr="COMPETENCY_ASK", coach="정의요?") is None


# ── P0-5 질문 잘림 ─────────────────────────────────────────────────────────────

def test_lead_cap_keeps_dependent_clause_of_compound_question():
    t = "성과 이야기를 하셨네요. 관련해서 지표를 쓰셨는지요. 있었다면 어떤 지표였는지 궁금합니다."
    assert cap_lead_sentences(t) == (t, 0)
    t2 = "리드1. 반대 의견이 있었을 텐데요. 있었다면 어떻게 설득하셨는지 궁금해요."
    assert cap_lead_sentences(t2) == (t2, 0)
    assert cap_lead_sentences("리드1. 리드2. 리드3. 그때 어떻게 하셨어요?") == ("리드1. 그때 어떻게 하셨어요?", 2)
    from diag_project.services.output_guard import keep_last_question
    kept, n = keep_last_question("확인해 보고 싶습니다. 그 팀원이 위험 신호를 먼저 알려온 적이 있었나요? 있었다면 언제였고, 그때 어떻게 대응하셨습니까?")
    assert "알려온 적이 있었나요?" in kept and kept.endswith("대응하셨습니까?") and n == 0     # 조건절 질문은 앞 질문과 한 쌍
    assert starts_without_main_clause("있었다면 어떻게 설득하셨는지 궁금해요.")
    assert starts_without_main_clause("이유였는지, 다음 차수라는 시점이었는지 궁금합니다.")
    assert not starts_without_main_clause("그때 어떻게 하셨어요?")
    assert is_question("지표를 쓰셨는지요.")


# ── P0-6 시간 인사 ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("hour,part", [(4, "늦은 시간"), (5, "오전"), (10, "오전"), (11, "점심"), (12, "점심"),
                                       (13, "오후"), (14, "오후"), (17, "오후"), (18, "저녁"), (22, "저녁"), (23, "늦은 시간")])
def test_daypart_boundaries_kst(hour, part):
    now = datetime(2026, 10, 28, hour, 49, tzinfo=KST)
    assert daypart(hour) == part
    assert get_time_greeting(now)["ampm_phrase"] == part
    assert ("점심" in get_time_phrase(now)) == (part == "점심")


def test_lucas_1349_is_afternoon_not_lunch():
    now = datetime(2026, 10, 28, 13, 49, tzinfo=KST)
    assert daypart(now.hour) == "오후"   # (2026-10-29 P1) 13:49 는 13~18 오후 구간
    now2 = datetime(2026, 10, 28, 14, 5, tzinfo=KST)
    assert get_time_phrase(now2).startswith("오후") and "점심" not in get_time_greeting(now2)["ampm_phrase"]


# ── P0-2 내부 어휘 누설 사전·가드 ───────────────────────────────────────────────

def test_leak_lexicon_contains_internal_words_and_excludes_coach_speech():
    from diag_project.services.leak_lexicon import cached_lexicon, find_leaks, strip_leak_sentences
    lex = cached_lexicon()
    # '가이드' 는 사다리 질문("가이드로 만드신 적")에 코치 발화로 쓰여 사전에서 빠진다(코치 어휘 우선)
    for w in ("되받기", "다리", "탐침", "턴", "사건", "태그", "지시", "오버라이드", "앵커"):   # (2026-10-29 P1) 반례·발화는 프롬프트에서 뺐다
        assert w in lex["korean"], w
    for w in ("star", "probe", "instruction"):
        assert w in lex["english"], w
    for w in ("자기인식", "회복탄력성", "갈등관리", "리더님", "팀원", "사례", "경험", "결과"):
        assert w not in lex["korean"], w
    t = "이번 턴은 되받기만 하고 탐침은 다음에요. 사례를 들려주셨네요. 그때 어떤 지시를 하셨어요?"
    assert {"턴", "되받기", "탐침", "지시"} <= set(find_leaks(t, strict=False))      # 린트(전체 사전)
    hits = find_leaks(t)                                                              # 가드(엄격 사전): 리더 일상어 '지시' 제외
    assert {"턴", "되받기", "탐침"} <= set(hits) and "지시" not in hits
    out, n = strip_leak_sentences(t, hits)
    assert "되받기" not in out and "탐침" not in out and out.endswith("하셨어요?") and n >= 2
    from diag_project.services.leak_lexicon import guard_lexicon
    assert "직전" in guard_lexicon()["everyday_excluded"] and "되받기" in guard_lexicon()["korean"]
    assert find_leaks("리더님께서는 조직관리를 무엇이라고 생각하시나요? 그때 팀원들과 어떻게 이야기하셨어요?") == []
    # 리더가 먼저 쓴 어절을 되받은 것은 누설이 아니다
    assert "태그" not in find_leaks("태그 작업을 직접 하셨군요. 그 뒤에는 어떻게 됐어요?", ["제가 태그 작업을 정리했어요"])


def test_route_has_leak_guard_wired():
    import os
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "diag_project", "routes", "diagnoses.py"), encoding="utf-8").read()
    assert 'v["leak"] = lk' in src and '"leak"}' in src and "strip_leak_sentences as _sls" in src
    assert "_anomaly_override_text" in src and "render_align as _ra" in src and "_voiced_q(template_anchor" in src


# ── 2026-10-29 재생(s281) 후속 ─────────────────────────────────────────────────

def test_last_question_keeps_main_clause_of_compound_question():
    from diag_project.services.input_anomaly import last_question_of
    q = last_question_of("상황 하나를 떠올려 주시면 됩니다. 팀원 한 명을 따로 만나 이야기를 나눠본 적이 있으셨습니까? 있었다면 언제쯤이었는지부터 알려주시면 됩니다.")
    assert q.startswith("팀원 한 명을") and q.endswith("알려주시면 됩니다.")


def test_transition_bridges_are_not_state_reports():
    from diag_project.services.intro_messages import TRANSITION_BRIDGES
    from diag_project.services.leak_lexicon import find_state_report
    for name, pool in TRANSITION_BRIDGES.items():
        for b in pool:
            assert find_state_report(b) == [], (name, b)


def test_definition_answer_mentioning_rest_is_not_pause_request():
    from diag_project.services.avoidance_detector import detect_pause_request
    ans = "저는 자기관리라고 하면 일이 몰려도 감정적으로 흔들리지 않고 우선순위를 정해 처리하는 모습이 먼저 떠올라요. 컨디션을 챙기고 잠깐 쉬어가는 것도 중요하게 봅니다."
    # 감지기 자체는 '쉬어'에 반응할 수 있다 — decider 가 정의 답변 턴(30자 이상)에서는 이 판정을 쓰지 않는다
    import inspect
    from diag_project.services import instruction_decider as D
    src = inspect.getsource(D)
    assert "_is_definition_answer" in src and "not _is_definition_answer" in src
    assert isinstance(detect_pause_request(ans), bool)


def test_strict_lexicon_excludes_leader_vocabulary_but_keeps_internal_words():
    from diag_project.services.leak_lexicon import guard_lexicon
    g = guard_lexicon()
    for w in ("턴", "탐침", "되받기", "앵커", "태그", "페르소나", "라포", "재생성"):   # (2026-10-29 P1) 반례·발화는 템플릿에서 사라져 자동 사전에서도 빠짐
        assert w in g["korean"], w          # '태그'는 GUARD_KEEP 수동 복원(2026-10-29 승인)
    for w in ("전환", "응답", "요약", "안내", "직전", "현재", "메시지"):
        assert w not in g["korean"], w      # 운영 세션 리더 입력에 한 번이라도 나온 말
        assert w in g["leader_excluded"], w
    assert "태그" in g["kept_manually"] and "태그" not in g["leader_excluded"]


def test_tail_guard_runs_on_align_receive_before_assembly():
    """8-n(입버릇)은 ALIGN 되받기에도 적용되고, 조립(8-z)은 그 뒤에 온다 — 조립 후 문장은 건드리지 않는다."""
    import inspect
    from diag_project.routes import diagnoses as d
    src = inspect.getsource(d._submit_message_phase3a)
    tail = src.index("_TAIL_EXEMPT = {")
    assert '"COMPETENCY_ALIGN"' not in src[tail: src.index("\n", tail)]
    assert src.index("# 8-n.") < src.index("# 8-h.") < src.index("# 8-z.") < src.index("# 9. 사건 생명주기")
    from diag_project.services.align_render import render_align, align_shape_ok
    from diag_project.services.output_guard import strip_lead_sentences, lead_tails
    out = render_align(llm_text="말씀 잘 들었어요. 그 결이 선명하게 들어왔어요.", chapter="self_management",
                       sub_names=["자기인식", "회복탄력성", "중심성"], persona_name="Ella", bridge_sub_key=None,
                       bridge_sub_name="자기인식", anchor="그런 순간이 최근에 있었어요?")
    assert align_shape_ok(out, ["자기인식", "회복탄력성", "중심성"])[0]
    # 조립 결과에 입버릇 삭제를 걸어도(실제 파이프라인에서는 걸리지 않음) 목록·앵커는 그대로다
    out2, _ = strip_lead_sentences(out, set(lead_tails(out)))
    assert "· 자기인식" in out2 and out2.rstrip().endswith("있었어요?")


def test_definition_answer_with_rest_word_is_not_pause_at_h4():
    """s291 Lucas: 자기관리 정의 답의 '잠깐 쉬면서'가 H4(챕터 중 일시정지 감지)에서 USER_REQUESTS_PAUSE 로 새지 않는다."""
    from diag_project.services.instruction_decider import detect_pause_request, _is_substantive_definition_answer
    txt = ("저는 자기관리라고 하면 일이 몰리거나 예상치 못한 문제가 생겨도 감정적으로 흔들리지 않고, 우선순위를 정해 차분하게 처리하는 "
           "모습이 먼저 떠올라요. 그래서 업무 일정뿐 아니라 제 컨디션을 챙기고, 필요할 때는 잠깐 쉬면서 다시 집중하는 것도 중요하게 보고 있어요.")
    assert detect_pause_request(txt)       # 낱말 감지 자체는 그대로(전제)
    assert _is_substantive_definition_answer({"last_instruction": "COMPETENCY_ASK", "last_user_response": txt})
    assert _is_substantive_definition_answer({"last_instruction": "STAR_INCOMPLETE", "last_user_response": txt})   # 60자 이상 실질 답은 어디서든 예외
    assert not _is_substantive_definition_answer({"last_instruction": "STAR_INCOMPLETE", "last_user_response": "오늘은 좀 지쳐서 잠깐 쉬었다가 다시 이어가도 될까요?"})
    assert not _is_substantive_definition_answer({"last_instruction": "COMPETENCY_ASK", "last_user_response": "잠깐 쉬었다 할게요"})
    import inspect
    from diag_project.services import instruction_decider as d
    src = inspect.getsource(d.decide_instruction) if hasattr(d, "decide_instruction") else inspect.getsource(d)
    h4 = src.index("H4: 휴식·미루기 요청")
    assert "_pause_req(state)" in src[h4: h4 + 900]   # (p13) 단일 입구 _pause_req 가 실질 답변 예외를 품는다


def test_final_leak_sweep_runs_after_tail_regen_and_before_align_assembly():
    """8-n 재생성 출력이 '되받기 한 문장 + 다리 한 문장으로 답하겠습니다.'로 시작해도 8-y 가 지운다(질문 보존)."""
    import inspect
    from diag_project.routes import diagnoses as d
    src = inspect.getsource(d._submit_message_phase3a)
    assert src.index("# 8-n.") < src.index("# 8-y.") < src.index("# 8-z.")
    from diag_project.services.leak_lexicon import find_leaks, strip_leak_sentences
    t = ("되받기 한 문장 + 다리 한 문장으로 답하겠습니다.\n\n앞선 질문이 어렵게 들리셨다면 제 쪽 잘못입니다. "
         "최근에 방향을 바꾸는 결정을 내리셨을 때, 팀원들이 처음 들었던 순간이 어땠는지 떠올려 주실 수 있을까요?")
    lk = find_leaks(t, [])
    assert "되받기" in lk
    out, n = strip_leak_sentences(t, lk)
    assert n == 1 and "되받기" not in out and out.endswith("있을까요?")


def test_state_report_catches_coach_self_reference_and_question_announcement():
    """s30 Daniel 전환 턴: 'Daniel 코치로서 자기관리 영역의 첫 질문을 드리겠습니다.' 는 상태 보고문이다(8-y 가 지운다)."""
    from diag_project.services.leak_lexicon import find_state_report
    assert find_state_report("Daniel 코치로서 자기관리 영역의 첫 질문을 드리겠습니다. 이제 '자기관리'로 이어가겠습니다.")
    assert not find_state_report("그 결정을 내리셨군요. 하나 여쭙겠습니다. 그때 팀원들 반응은 어땠습니까?")


# ── P1 (2026-10-29) ─────────────────────────────────────────────────────────────
def test_apply_probe_turn_anchors_volunteered_sub_when_all_asked():
    """P1-5: asked 는 전부지만 앵커를 못 받은(자발적 사례) 하위역량이 남았으면 그것을 다음 타겟으로."""
    from diag_project.services.traversal import apply_probe_turn, MAX_TURNS_PER_SUB
    subs = ["자기인식", "회복탄력성", "중심성"]
    store = {"asked_subs": {"self_management": subs}, "anchored_subs": {"self_management": ["자기인식", "중심성"]},
             "current_target": {"self_management": "중심성"}, "turns_on_target": {"self_management": MAX_TURNS_PER_SUB}}
    store2, cur = apply_probe_turn(store, "self_management", subs, event_done=False)
    assert cur == "회복탄력성" and "회복탄력성" in store2["anchored_subs"]["self_management"]
    assert store2["turns_on_target"]["self_management"] == 1
    # 전부 앵커까지 끝났으면 현재 타겟 유지(turns 만 증가하지 않음 — 기존 동작)
    store3, cur3 = apply_probe_turn(store2 | {"turns_on_target": {"self_management": MAX_TURNS_PER_SUB}}, "self_management", subs, event_done=False)
    assert cur3 == "회복탄력성"


def test_ladder_question_prefers_unused_step():
    from diag_project.data.ladder_questions import ladder_question, LADDER_QUESTIONS
    assert ladder_question("vision_sharing", 2)[1] == "2_3"
    assert ladder_question("vision_sharing", 2, avoid=["2_3"])[1] == "3_4"
    assert ladder_question("vision_sharing", 3, avoid=["3_4"])[1] == "2_3"
    assert ladder_question("vision_sharing", 2, avoid=["2_3", "3_4"])[1] == "2_3"
    assert ladder_question("vision_sharing", 2, avoid=["2_3"])[0] == LADDER_QUESTIONS["vision_sharing"]["3_4"]


def test_ladder_turn_trigger_and_precedence_wired():
    import inspect
    from diag_project.routes import diagnoses as d
    from diag_project.services import instruction_decider as dec
    src = inspect.getsource(d._submit_message_phase3a)
    i = src.index("사다리 탐침(턴 조건)")
    assert "turns_on_target" in src[i - 1500: i] and ">= 3" in src[i - 1500: i]
    j = src.index("사다리 턴 → R/A/일반화 강제 해제")
    assert i < j < src.index("if _force_r:\n            from diag_project.services.output_guard import needs_quantify_probe")
    assert 'return "CROSS_CHAPTER_OPPORTUNITY"' not in inspect.getsource(dec.decide_instruction)
    assert '"이 영역에서 들려주신 이야기는 여기서 정리하겠습니다."' not in src


def test_direct_action_question_detector_and_soft_lines():
    from diag_project.services.output_guard import is_direct_action_question
    from diag_project.services.intro_messages import PERSONA_LINES
    from diag_project.services.traversal import is_action_probe_text, ACTION_FALLBACK_QUESTION
    assert is_direct_action_question("그때 리더님이 직접 하신 일은 무엇이었어요?")
    assert not is_direct_action_question("그 자리에서 리더님 몫은 어디까지였어요?")
    assert is_action_probe_text(ACTION_FALLBACK_QUESTION)
    for p, d in PERSONA_LINES.items():
        assert is_action_probe_text(d["action"]), (p, d["action"])     # 완화 문안도 행동 질문으로 인식(A 원장)
        assert "—" not in d["generalize"]
        assert d["reask_anchor_2"].startswith("비슷한 다른 장면이라도") and "여기까지 듣고 넘어" in d["skip_item"]


def test_generalized_answer_rule_time_marker_alone():
    from diag_project.services.avoidance_detector import is_generalized_answer as G
    assert G("저는 팀원들과 먼저 이야기를 나누고 역할을 나눈 뒤에 일정을 다시 잡는 식으로 진행합니다.")   # 시점 없음·습관 표지 없음·20자 이상
    assert not G("지난달에 팀원들과 먼저 이야기를 나누고 역할을 나눈 뒤에 일정을 다시 잡았습니다.")       # 시점 표지
    assert not G("기존 대면교육 일부를 온라인 사전학습으로 바꾸자고 했을 때 팀원들이 효과를 의심했어요. 한 과정에만 시범 적용해 보자고 했습니다.")  # 시점 없어도 서술된 사건(과거형 2+)
    assert G("보통 제가 먼저 정리해서 공유하는 편입니다.")                                            # 짧아도 습관 표지
    assert not G("네, 그렇게 했습니다.")                                                            # 짧고 표지 없음 → 보류


def test_p1_anomaly_escalation_and_direct_cap_wired():
    import inspect
    from diag_project.routes import diagnoses as d
    src = inspect.getsource(d._submit_message_phase3a)
    a = src.index("anomaly_counts"); assert "_ac_n >= 3" in src[a: a + 2500] and "skip_bridge" in src[a: a + 2500]
    assert "'reask_anchor_2' if _ac_n == 2 else 'reask_anchor'" in src
    j = src.index("# 8-j."); assert 'state.get("skip_bridge")' in src[j: j + 1500]
    c = src.index("'리더님이 직접 하신 일' 질문 상한"); assert "direct_q_count" in src[c: c + 1500] and "a_present" in src[c: c + 1500]
    g = src.index("generalize_pending"); assert '"generalized"' in src[g: g + 1200]


def test_anchor_rotation_second_session_first_questions_all_differ():
    """P1-4: 같은 참가자의 두 번째 세션(variant 1)은 26개 하위역량의 첫 질문이 전부 달라진다. 대상화 표현 0."""
    from diag_project.data.competencies import COMPETENCY_FRAMEWORK, get_anchor_questions
    from diag_project.services.anchor_render import dict_anchor
    from diag_project.services.intro_messages import build_chapter_opening_with_user_def
    keys = [k for ch, fw in COMPETENCY_FRAMEWORK.items() if ch != "supplementary" for k in fw["indicators"]]
    assert len(keys) == 26
    allq = [q for k in keys for q in get_anchor_questions(k)]
    assert len(allq) == 52 and len(set(allq)) == 52
    assert all(dict_anchor(k, 0) != dict_anchor(k, 1) for k in keys)
    bad = ("키우신", "봐주며", "손을 놓은", "서툰 팀원", "방어적인", "반신반의", "수긍 못", "경계하는", "개성 강한", "안 도와주던", "떠날 것 같은", "끼어들어")
    for q in allq:
        assert not any(b in q for b in bad), q
    for ch in ("organization_management", "people_management", "self_management"):
        a = build_chapter_opening_with_user_def(ch, "정의", "", variant=0)
        b = build_chapter_opening_with_user_def(ch, "정의", "", variant=1)
        assert a != b


def test_michael_voice_does_not_split_verb_before_hasin_jeok():
    from diag_project.services.persona_voice import voice_question
    out = voice_question("Michael", "성과가 기대와 달랐던 팀원에게 솔직한 피드백을 전하신 적이 최근에 있었다면 어떤 상황이었을까요?")
    assert "전직접" not in out and "전하신 적" in out
    out2 = voice_question("Michael", "경험이 적은 팀원에게 일부러 비중 있는 일을 맡기신 적, 근래에 있으세요?")
    assert "직접" in out2 or "맡기신" in out2
    out3 = voice_question("Michael", "팀 목표를 다시 세우신 뒤 팀원들과 같이 하신 적이 있었어요?")
    assert "같이 직접 하신 적" in out3


def test_ladder_duplicate_guard_wired():
    import inspect
    from diag_project.routes import diagnoses as d
    from diag_project.services import llm_judge as j
    src = inspect.getsource(d._submit_message_phase3a)
    assert src.count("await _choose_ladder(") == 2 and src.count("_mark_ladder_answered(_store") == 2
    assert "ladder_already_answered" in inspect.getsource(j)
    h = src.index("async def _choose_ladder"); body = src[h: h + 1400]
    assert '"swapped"' in body and '"answered"' in body and "ladder_skip" in body


def test_indirect_question_with_yeojjwo_bolgeyo_pairs_conditional_followup():
    """p121_6 Lucas: '…있었는지 여쭤볼게요. 있었다면 그때 무엇을 바꾸셨는지 한 줄로 알려주세요.' 는 한 쌍 — 잘림이 아니다."""
    from diag_project.services.output_guard import is_question
    assert is_question("그 기준으로 최근에 본인 방식이 팀에서 예상과 다르게 받아들여졌던 일이 있었는지 여쭤볼게요.")
    assert not is_question("하나 여쭤볼게요.")


def test_strip_praise_keeps_question_sentence_and_pause_single_entry():
    from diag_project.services.output_guard import strip_praise
    out, n = strip_praise("역할을 정리하셔서 조정까지 이어졌네요. 정말 인상적이네요, 혹시 반발은 없었나요? 있었다면 어떻게 뚫고 나가셨는지 궁금합니다.")
    assert "반발은 없었나요?" in out and "인상적" not in out and out.endswith("궁금합니다.")
    import inspect
    from diag_project.services import instruction_decider as d
    src = inspect.getsource(d.decide_instruction)
    assert "detect_pause_request(" not in src and src.count("_pause_req(") >= 6
    st = {"last_user_response": "저는 자기관리라고 하면 일이 몰리거나 예상치 못한 문제가 생겨도 감정적으로 흔들리지 않고 우선순위를 정해 차분하게 처리하는 모습이 먼저 떠올라요. 필요할 때는 잠깐 쉬면서 다시 집중하는 것도 중요하게 보고 있어요.",
          "last_instruction": "COMPETENCY_ALIGN"}
    assert not d._pause_req(st) and d._pause_req({"last_user_response": "잠깐 쉬었다 할게요", "last_instruction": "STAR_INCOMPLETE"})
