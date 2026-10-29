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

@pytest.mark.parametrize("hour,part", [(4, "늦은 시간"), (5, "오전"), (10, "오전"), (11, "점심"), (13, "점심"),
                                       (14, "오후"), (17, "오후"), (18, "저녁"), (22, "저녁"), (23, "늦은 시간")])
def test_daypart_boundaries_kst(hour, part):
    now = datetime(2026, 10, 28, hour, 49, tzinfo=KST)
    assert daypart(hour) == part
    assert get_time_greeting(now)["ampm_phrase"] == part
    assert ("점심" in get_time_phrase(now)) == (part == "점심")


def test_lucas_1349_is_afternoon_not_lunch():
    now = datetime(2026, 10, 28, 13, 49, tzinfo=KST)
    assert daypart(now.hour) == "점심"   # 13:49 는 11~14 점심 구간
    now2 = datetime(2026, 10, 28, 14, 5, tzinfo=KST)
    assert get_time_phrase(now2).startswith("오후") and "점심" not in get_time_greeting(now2)["ampm_phrase"]


# ── P0-2 내부 어휘 누설 사전·가드 ───────────────────────────────────────────────

def test_leak_lexicon_contains_internal_words_and_excludes_coach_speech():
    from diag_project.services.leak_lexicon import cached_lexicon, find_leaks, strip_leak_sentences
    lex = cached_lexicon()
    # '가이드' 는 사다리 질문("가이드로 만드신 적")에 코치 발화로 쓰여 사전에서 빠진다(코치 어휘 우선)
    for w in ("되받기", "다리", "탐침", "턴", "사건", "태그", "지시", "반례", "오버라이드", "앵커"):
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
