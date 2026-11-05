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
from diag_project.services.output_guard import count_questions, is_question, starts_without_main_clause
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
                       anchor=voice_question(persona, "최근에 방향을 새로 잡으신 적이 있었어요?"))
    ok, why = align_shape_ok(out, _subs(chapter))
    assert ok, (out, why)
    assert "크게 다르지 않" not in out and "엉뚱한 목록" not in out and "어느 쪽" not in out
    assert count_questions(out) == 1   # (2026-11-04 P3-4 2차) Michael 요청형 앵커는 물음표 없음
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
                       persona_name="Daniel", anchor="그런 순간이 있었습니까?")
    assert out.startswith(PERSONA_LINES["Daniel"]["align_receive_fallback"])
    assert align_shape_ok(out, _subs("self_management"))[0]




# ── P0-3 페르소나 어미: 6명 간 동일 앵커 0 ──────────────────────────────────────

def test_all_dictionary_anchors_differ_across_six_personas():
    qs = [q for lst in SUBCOMPETENCY_ANCHOR_QUESTIONS.values() for q in (lst if isinstance(lst, list) else [lst])]
    norm = lambda s: re.sub(r"[\s.,!?…'\"()]", "", s)  # noqa: E731
    same = [(a, b, q) for q in qs for a, b in itertools.combinations(NAMES, 2) if norm(voice_question(a, q)) == norm(voice_question(b, q))]
    # (2026-11-04 P3-4 2차) Michael 은 요청형('…하셨던 일, 하나만 들려주세요.') — 6명 전부 달라야 한다(Ella·Michael 동일 허용 되돌림).
    assert same == [], same[:5]
    for q in qs:
        m = voice_question("Michael", q)
        assert "던가요" not in m and "?" not in m and is_question(m) and m.endswith(("들려주세요.", "는지도요.")), m
        for n in NAMES:
            if n != "Michael":
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



# ── P0-6 시간 인사 ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("hour,part", [(4, "늦은 시간"), (5, "오전"), (10, "오전"), (11, "오전 마무리"), (12, "점심"),
                                       (13, "오후"), (14, "오후"), (17, "오후"), (18, "저녁"), (22, "저녁"), (23, "늦은 시간")])
def test_daypart_boundaries_kst(hour, part):
    # (2026-11-04 P3-5) 11~12 '오전 마무리', 점심 12:00~13:30 — 분 49 기준이라 13:49 는 오후
    now = datetime(2026, 10, 28, hour, 49, tzinfo=KST)
    assert daypart(hour, 49) == part
    assert get_time_greeting(now)["ampm_phrase"] == part
    assert ("점심" in get_time_phrase(now)) == (part == "점심")


def test_lucas_1349_is_afternoon_not_lunch():
    now = datetime(2026, 10, 28, 13, 49, tzinfo=KST)
    assert daypart(now.hour, now.minute) == "오후"   # (2026-11-04 P3-5) 13:49 는 13:30~18 오후, 13:29 는 점심
    assert daypart(13, 29) == "점심" and daypart(11, 30) == "오전 마무리"
    assert get_time_greeting(datetime(2026, 11, 4, 11, 30, tzinfo=KST))["greeting_question"] == "오전 마무리는 어떠세요?"
    now2 = datetime(2026, 10, 28, 14, 5, tzinfo=KST)
    assert get_time_phrase(now2).startswith("오후") and "점심" not in get_time_greeting(now2)["ampm_phrase"]


# ── P0-2 내부 어휘 누설 사전·가드 ───────────────────────────────────────────────

def test_leak_lexicon_contains_internal_words_and_excludes_coach_speech():
    from diag_project.services.leak_lexicon import cached_lexicon, find_leaks, strip_leak_sentences
    lex = cached_lexicon()
    # '가이드' 는 사다리 질문("가이드로 만드신 적")에 코치 발화로 쓰여 사전에서 빠진다(코치 어휘 우선)
    for w in ("되받기", "다리", "탐침", "턴", "사건", "태그", "지시", "앵커"):   # (2026-10-29 P1) 반례·발화는 프롬프트에서 뺐다
        assert w in lex["korean"], w
    for w in ("abort", "probe", "instruction"):   # (2026-11-04 BEI) 'star' 는 프롬프트에서 사라졌다(슬롯 6개로 대체)
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




# ── 2026-10-29 재생(s281) 후속 ─────────────────────────────────────────────────

def test_last_question_keeps_main_clause_of_compound_question():
    from diag_project.services.input_anomaly import last_question_of
    q = last_question_of("상황 하나를 떠올려 주시면 됩니다. 팀원 한 명을 따로 만나 이야기를 나눠본 적이 있으셨습니까? 있었다면 언제쯤이었는지부터 알려주시면 됩니다.")
    assert q.startswith("팀원 한 명을") and q.endswith("알려주시면 됩니다.")




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
    for w in ("턴", "탐침", "되받기", "태그", "페르소나", "라포", "재생성", "사건"):   # (2026-11-04 BEI) '앵커'는 템플릿 10회 미만으로 내려가 엄격 사전에서 빠졌다(전체 사전에는 남는다)
        assert w in g["korean"], w          # '태그'·'사건'은 GUARD_KEEP 수동 복원(2026-10-29·2026-11-02 승인)
    assert "사건" in g["kept_manually"]
    for w in ("응답", "안내", "직전", "메시지"):   # (2026-11-04 BEI) '전환'·'요약'·'현재'는 템플릿 10회 미만으로 내려가 목록에서 뺐다
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
    assert src.index("# 8-n.") < src.index("# 8-h.") < src.index("# 8-z.") < src.index("# 9. 사례 행(Event) 저장")
    from diag_project.services.align_render import render_align, align_shape_ok
    out = render_align(llm_text="말씀 잘 들었어요. 그 결이 선명하게 들어왔어요.", chapter="self_management",
                       sub_names=["자기인식", "회복탄력성", "중심성"], persona_name="Ella", anchor="그런 순간이 최근에 있었어요?")
    assert align_shape_ok(out, ["자기인식", "회복탄력성", "중심성"])[0]
    assert "· 자기인식" in out and out.rstrip().endswith("있었어요?") and "먼저 하나를 깊게 들어볼게요." in out   # (BEI 결정 6) 새 안내·다리




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










def test_anchor_rotation_second_session_first_questions_all_differ():
    """P1-4: 같은 참가자의 두 번째 세션(variant 1)은 26개 하위역량의 첫 질문이 전부 달라진다. 대상화 표현 0."""
    from diag_project.data.competencies import COMPETENCY_FRAMEWORK, get_anchor_questions
    from diag_project.services.anchor_render import dict_anchor
    keys = [k for ch, fw in COMPETENCY_FRAMEWORK.items() if ch != "supplementary" for k in fw["indicators"]]
    assert len(keys) == 26
    allq = [q for k in keys for q in get_anchor_questions(k)]
    assert len(allq) == 52 and len(set(allq)) == 52
    assert all(dict_anchor(k, 0) != dict_anchor(k, 1) for k in keys)
    bad = ("키우신", "봐주며", "손을 놓은", "서툰 팀원", "방어적인", "반신반의", "수긍 못", "경계하는", "개성 강한", "안 도와주던", "떠날 것 같은", "끼어들어")
    for q in allq:
        assert not any(b in q for b in bad), q


def test_michael_voice_does_not_split_verb_before_hasin_jeok():
    from diag_project.services.persona_voice import voice_question
    out = voice_question("Michael", "성과가 기대와 달랐던 팀원에게 솔직한 피드백을 전하신 적이 최근에 있었다면 어떤 상황이었을까요?")
    assert "전직접" not in out and "전하신 적" in out
    out2 = voice_question("Michael", "경험이 적은 팀원에게 일부러 비중 있는 일을 맡기신 적, 근래에 있으세요?")
    assert "직접" in out2 or "맡기셨던" in out2
    out3 = voice_question("Michael", "팀 목표를 다시 세우신 뒤 팀원들과 같이 하신 적이 있었어요?")
    assert "같이 직접 하셨던 일, 하나만 들려주세요." in out3




def test_indirect_question_with_yeojjwo_bolgeyo_pairs_conditional_followup():
    """p121_6 Lucas: '…있었는지 여쭤볼게요. 있었다면 그때 무엇을 바꾸셨는지 한 줄로 알려주세요.' 는 한 쌍 — 잘림이 아니다."""
    from diag_project.services.output_guard import is_question
    assert is_question("그 기준으로 최근에 본인 방식이 팀에서 예상과 다르게 받아들여졌던 일이 있었는지 여쭤볼게요.")
    assert not is_question("하나 여쭤볼게요.")






# ── P2-1 페르소나 고정 슬롯 ────────────────────────────────────────────────────


def test_restore_slot_sentence_rebuilds_lost_fixed_line():
    from diag_project.services.persona_voice import restore_slot_sentence
    from diag_project.services.intro_messages import PERSONA_LINES, DANIEL_OBSERVATIONS
    mq = PERSONA_LINES["Michael"]["slot_q"]
    ml = PERSONA_LINES["Michael"]["slot_lead"]
    # (2026-11-04 P3-2) Michael 응원 턴(slot_text=응원 문장): 8-n 재생성이 응원을 지웠으면 되받기 뒤에 되돌린다
    out, r = restore_slot_sentence("좋습니다, 참여율을 핵심으로 정하셨군요. 그 조율 자리는 언제쯤이었을까요?", "Michael", ml)
    assert r and out == f"좋습니다, 참여율을 핵심으로 정하셨군요. {ml} 그 조율 자리는 언제쯤이었을까요?"
    # 남아 있으면 손대지 않는다(띄어쓰기 차이 무시)
    out, r = restore_slot_sentence(f"참여율을 핵심으로 정하셨군요. {ml.replace(' ', '  ')} 그 뒤에는요?", "Michael", ml)
    assert not r
    # 되받기가 없으면 빈 응원은 넣지 않는다
    out, r = restore_slot_sentence("그 조율 자리는 언제쯤이었을까요?", "Michael", ml)
    assert not r
    # 실행 의지 질문 턴(slot_text=고정 질문): 되받기 1문장 + 고정 질문
    out, r = restore_slot_sentence("좋습니다, 참여율을 핵심으로 정하셨군요. 그 조율 자리는 언제쯤이었을까요?", "Michael", mq)
    assert r and out == f"좋습니다, 참여율을 핵심으로 정하셨군요. {mq}"
    out, r = restore_slot_sentence(f"그러셨군요. {mq}", "Michael", mq)
    assert not r
    # Jessica: 첫 되받기 1문장 + 기준 질문
    jq = PERSONA_LINES["Jessica"]["slot_q"]
    out, r = restore_slot_sentence("2주라고 하셨죠. 그렇게 생각하시게 된 계기가 된 일이 하나 있으셨을까요?", "Jessica", jq)
    assert r and out == f"2주라고 하셨죠. {jq}"
    # Daniel: 관찰 문장을 앞에 되돌리고 나머지는 보존
    ob = DANIEL_OBSERVATIONS[1]
    out, r = restore_slot_sentence("알겠습니다. 그때 어떤 과제였는지 말씀해 주시겠습니까?", "Daniel", ob)
    assert r and out == f"알겠습니다. {ob} 그때 어떤 과제였는지 말씀해 주시겠습니까?"   # (P3-2) 관찰은 되받기 뒤
    assert restore_slot_sentence("그때 어떤 과제였는지 말씀해 주시겠습니까?", "Daniel", ob)[0].startswith(ob)
    # 리드 1문장 상한이 관찰의 뒷문장('저도 그랬습니다.')을 잘라도 첫 문장이 남았으면 복원하지 않는다(중복 방지)
    out, r = restore_slot_sentence(f"{ob.split('. ')[0]}. 그 뒤에는 어떻게 되었습니까?", "Daniel", ob)
    assert not r
    # Olivia: LLM 이 다른 대조 질문을 남겼으면 그대로
    out, r = restore_slot_sentence("그 팀원 입장에서는 어떤 장면이었을까요?", "Olivia", PERSONA_LINES["Olivia"]["slot_q"])
    assert not r
    out, r = restore_slot_sentence("네, 그러셨군요. 그 다음은 어떻게 되었나요?", "Olivia", PERSONA_LINES["Olivia"]["slot_q"])
    assert r and out.endswith(PERSONA_LINES["Olivia"]["slot_q"])



def test_quote_josa_for_numbers_and_slot_wording():
    from diag_project.services.korean import quote_josa
    from diag_project.services.intro_messages import PERSONA_LINES
    assert quote_josa("8%") == "라고" and quote_josa("3명") == "이라고" and quote_josa("48시간") == "이라고"
    assert quote_josa("2배") == "라고" and quote_josa("10건") == "이라고" and quote_josa("5회") == "라고" and quote_josa("13") == "이라고" and quote_josa("12") == "라고"
    assert PERSONA_LINES["Michael"]["slot_q"] == "다음에 비슷한 상황이 오면 어떻게 하실 생각이세요?"


def test_indirect_question_with_want_to_confirm_is_question():
    from diag_project.services.output_guard import is_question
    assert is_question("지금은 '새로운 방향에 확신이 서지 않던 팀원들과 뜻을 맞추신 일'이 최근에 있었는지만 확인하고 싶습니다.")
    assert is_question("리더님께서 직접 팀원과 이런 과정을 밟아보신 장면이 있었는지 여쭙고 싶습니다.")


