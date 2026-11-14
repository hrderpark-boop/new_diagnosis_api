"""(2026-11-15 P13) 11/14 운영 Lucas 세션 검토 — 고정 문구 세 가지.

A. (지시 8) 세션 첫 인사 턴과 이름을 받은 뒤 첫 스몰톡 질문 턴이 코치 말투로 나간다(여섯 코치).
   종전: 틀이 해요체 한 벌뿐이었고, 뒤에서 거는 말투 교정은 Lucas(mixed)를 건너뛰어 Lucas 만 해요체로 나갔다.
B. (지시 2) Lucas 의 질문 끝맺음이 서술어 없는 생략형이 아니다(훑는 질문 꼬리 · 고정 질문).
C. (지시 5) 같은 답이 다시 들어왔을 때의 짧은 안내 1문장(repeat_notice) — 다른 장면을 청하지 않는다.

LLM·DB 없음.
"""
import os
import re
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.data.coaches_persona import COACHES_PERSONA  # noqa: E402
from diag_project.data.competencies import SUBCOMPETENCY_ANCHOR_QUESTIONS  # noqa: E402
from diag_project.services import intro_messages as IM  # noqa: E402
from diag_project.services import persona_voice as V  # noqa: E402
from diag_project.services import time_greeting as T  # noqa: E402

KST = ZoneInfo("Asia/Seoul")
FULL_NAME = {v["name"].split(" ")[0]: v["name"] for v in COACHES_PERSONA.values()}   # 'Lucas' → 'Lucas (루카스)'
POLITE = ("Ella", "Olivia", "Michael")          # 해요체
FORMAL = ("Jessica", "Daniel", "Lucas")         # 합쇼체(Lucas 의 질문·고정 문장은 합쇼체 쪽)
ALL = POLITE + FORMAL

_AFTERNOON = datetime(2026, 11, 16, 15, 0, tzinfo=KST)


def _sentences(text: str) -> list[str]:
    """문장부호·줄바꿈으로 자른 문장 목록(이 파일 안에서만 쓰는 단순 분리)."""
    out = []
    for block in re.split(r"\n+", text or ""):
        out.extend(x.strip() for x in re.split(r"(?<=[.?!…])\s+", block) if x.strip())
    return out


def _body(sentence: str) -> str:
    return sentence.rstrip(".?!…~\"'”’ ")


def _ends_polite(sentence: str) -> bool:
    """해요체로 끝난 문장 — '…요.' / '…요?' / '…죠?'"""
    return _body(sentence).endswith(("요", "죠"))


def _ends_formal(sentence: str) -> bool:
    """합쇼체로 끝난 문장 — '…습니다/…ㅂ니다' · '…습니까/…십니까' · '…십시오'"""
    return _body(sentence).endswith(("니다", "니까", "십시오", "시오"))


def _first_turn(coach: str) -> str:
    return T.build_rapport_greeting(FULL_NAME[coach])


def _name_turn(coach: str, *, user_name: str | None = "김하늘", when: datetime = _AFTERNOON, hostile: bool = False) -> str:
    g = T.get_time_greeting(when)      # 운영 경로와 같게: state 에 들어가는 시간대 이름과 해요체 판 안부 질문을 그대로 넘긴다
    return T.build_rapport_first_turn_response(user_name, g["ampm_phrase"], is_hostile=hostile,
                                               greeting_question=g["greeting_question"], persona_name=FULL_NAME[coach])


# ── A. 첫 두 턴이 코치 말투 ────────────────────────────────────────────────────

@pytest.mark.parametrize("coach", FORMAL)
def test_a_formal_coaches_first_two_turns_have_no_haeyo_ending(coach):
    for text in (_first_turn(coach), _name_turn(coach)):
        sents = _sentences(text)
        assert sents and not [s for s in sents if _ends_polite(s)], (coach, text)
        # 호칭으로 끝나는 인사 조각('반갑습니다, 리더님.' · '반갑습니다, 김하늘 리더님.') 말고는 전부 합쇼체 어미
        assert all(_ends_formal(s) or _body(s).endswith("리더님") for s in sents), (coach, sents)
    assert _first_turn(coach).rstrip().endswith("니까?")            # 이름을 묻는 질문
    assert _name_turn(coach).rstrip().endswith("계십니까?")          # 안부 질문
    assert FULL_NAME[coach] in _first_turn(coach) and "김하늘 리더님" in _name_turn(coach)


@pytest.mark.parametrize("coach", FORMAL)
def test_a_formal_coaches_every_branch_and_daypart(coach):
    """이름 없음·불만 분기와 여섯 시간대 모두에서 해요체 어미가 없다."""
    whens = [datetime(2026, 11, 16, h, m, tzinfo=KST) for h, m in ((9, 0), (11, 30), (12, 10), (15, 0), (19, 0), (23, 40))]
    for when in whens:
        for user_name, hostile in (("김하늘", False), (None, False), ("리더", False), ("김하늘", True)):
            text = _name_turn(coach, user_name=user_name, when=when, hostile=hostile)
            assert not [s for s in _sentences(text) if _ends_polite(s)], (coach, when, text)
            assert text.rstrip().endswith("니까?"), (coach, when, text)
            assert "오늘 늦은 시간 시간" not in text and "오늘 오늘" not in text
    # 안부 질문만 따로 — 시간대 이름을 모를 때도 합쇼체
    for part in ("오전", "오전 마무리", "점심", "오후", "저녁", "늦은 시간", "오늘", None):
        assert T.greeting_question_for(part, FULL_NAME[coach]).endswith("니까?"), (coach, part)


def test_a_lucas_regression_1114():
    """11/14 운영 Lucas 에 나간 해요체 구절이 더는 나가지 않는다."""
    both = _first_turn("Lucas") + "\n" + _name_turn("Lucas")
    for gone in ("여정이에요", "찾아가 봐요", "알려주시겠어요", "나눠볼게요", "계세요?"):
        assert gone not in both, gone


@pytest.mark.parametrize("coach", POLITE)
def test_a_polite_coaches_first_two_turns_stay_haeyo(coach):
    first, name = _first_turn(coach), _name_turn(coach)
    # 질문은 해요체 — '…습니까/…십니까'로 끝나는 문장이 없다
    for text in (first, name):
        assert not [s for s in _sentences(text) if _body(s).endswith("니까")], (coach, text)
        assert text.rstrip().endswith("요?"), (coach, text)
    # 합쇼체 평서문 예외 — 첫 인사의 자기소개('… 코치 ○○입니다.')와 환영('… 환영합니다.') 두 문장뿐.
    #   이 두 문장은 종전 틀부터 합쇼체였고(지시: 해요체 코치는 지금처럼), 턴 끝의 말투 교정(apply_register scope="all")도 해요체 코치의
    #   합쇼체 평서문은 건드리지 않는다. '반갑습니다, 리더님.' 은 호칭으로 끝나므로 어미 검사 대상이 아니다.
    formal_in_first = [s for s in _sentences(first) if _ends_formal(s)]
    assert len(formal_in_first) == 2, (coach, formal_in_first)
    assert formal_in_first[0].endswith(f"코치 {FULL_NAME[coach]}입니다.") and formal_in_first[1].endswith("환영합니다."), formal_in_first
    assert not [s for s in _sentences(name) if _ends_formal(s)], (coach, name)        # 이름 확인 뒤 턴에는 합쇼체 문장이 없다
    # 본문(평가가 아니라는 안내 · 편하게 이야기하자는 문장)은 해요체
    assert sum(1 for s in _sentences(first) if _ends_polite(s)) >= 3 and sum(1 for s in _sentences(name) if _ends_polite(s)) >= 2


def test_a_default_without_persona_is_unchanged():
    """persona_name 을 넘기지 않는 호출은 종전 문장 그대로(해요체 판)."""
    assert T.build_rapport_first_turn_response("박기진", "오후") == (
        "반갑습니다, 박기진 리더님! 본격적으로 시작하기 전에 잠깐 편하게 이야기 나눠볼게요. 오늘 오후 시간은 어떻게 보내고 계세요?")
    assert T.build_rapport_first_turn_response(None, "오후", is_hostile=True).endswith("편하게 이야기 나누는 시간이에요. 오늘 오후 시간은 어떻게 보내고 계세요?")
    # 해요체 코치는 persona_name 을 넘겨도 같은 문장
    for coach in POLITE:
        assert _name_turn(coach) == T.build_rapport_first_turn_response("김하늘", "오후")
    # state 에 들어가는 안부 질문(get_time_greeting)은 종전대로 해요체 판
    assert T.get_time_greeting(_AFTERNOON)["greeting_question"] == "오늘 오후 시간은 어떻게 보내고 계세요?"
    assert T.get_time_greeting(datetime(2026, 11, 16, 11, 30, tzinfo=KST))["greeting_question"] == "오전 마무리는 어떠세요?"
    assert T.get_time_greeting(datetime(2026, 11, 16, 23, 40, tzinfo=KST))["greeting_question"] == "오늘 하루는 어떻게 보내셨어요?"
    # 모르는 코치 이름은 해요체 판
    assert T.build_rapport_greeting("Zoe") == T.build_rapport_greeting("Zoe", persona_name="Ella")


def test_a_formal_lines_survive_register_correction():
    """턴 끝 말투 교정(어미표)이 새 문장을 다시 바꾸지 않는다 — 사전에 둔 문장이 그대로 나간다."""
    from diag_project.services.persona_register import apply_register
    for coach in ALL:
        for text in (_first_turn(coach), _name_turn(coach)):
            out, n_fixed, left = apply_register(FULL_NAME[coach], text, scope="all")
            assert out == text and n_fixed == 0 and left == [], (coach, text, out)


# ── B. Lucas 질문 끝맺음 ───────────────────────────────────────────────────────

# 서술어 없는 생략형 — 명사·조사 바로 뒤에 '요'가 붙어 끝나는 꼴('일은요?' · '건요?' · '있으면요?' · '하나만요.')
_ELLIPSIS_RE = re.compile(r"(?:은|는|건|면|만|도|부터|까지)요[.?!…]*$")
# Lucas 질문의 서술어 끝맺음
_LUCAS_Q_END_RE = re.compile(r"(?:나요|습니까|십니까|입니까)\?$")
_ANCHORS = [q for lst in SUBCOMPETENCY_ANCHOR_QUESTIONS.values() for q in (lst if isinstance(lst, list) else [lst])]


def _ending(question: str) -> str:
    return " ".join(_body(question).split()[-2:])       # 끝 두 어절


def test_b_ellipsis_detector_knows_the_1114_forms():
    for bad in ("평소 맡고 계신 일은요?", "이번 진단에서 기대하시는 건요?", "기억나는 일 있으면요?", "다른 장면 하나만요.", "한 문장만요?"):
        assert _ELLIPSIS_RE.search(bad), bad
    for ok in ("평소 어떤 일을 맡고 계십니까?", "떠오르는 게 있나요?", "그렇군요.", "어땠어요?"):
        assert not _ELLIPSIS_RE.search(ok), ok


def test_b_lucas_voice_question_three_variants_are_full_sentences():
    varied = 0
    for q in _ANCHORS:
        outs = [V.voice_question("Lucas", q, variant=v) for v in range(3)]
        for o in outs:
            assert o.count("?") == 1 and o.endswith("?"), (q, o)
            assert not _ELLIPSIS_RE.search(o), (q, o)
            assert _LUCAS_Q_END_RE.search(o), (q, o)                # 서술어로 끝난다
            assert "있으면요" not in o and " 최근 있" not in o, (q, o)   # 꼬리 생략형 · 조사를 뗀 '…일 최근 있었나요?'
        if len(set(outs)) == 3:
            varied += 1
            assert len({_ending(o) for o in outs}) == 3, (q, outs)  # 세 변형은 끝맺음이 서로 다르다
        assert V.voice_question("Lucas", q, variant=3) == outs[0]   # 3종 순환
    assert varied >= 40, varied        # 꼬리 변형은 있었는지를 묻는 문안에 걸린다(사전 52개 가운데 46개)


def test_b_lucas_exist_tails_sample():
    q = "새로운 방향에 확신이 서지 않던 팀원들과 뜻을 맞추신 일, 최근에 있으셨어요?"
    v0, v1, v2 = (V.voice_question("Lucas", q, variant=v) for v in range(3))
    assert v0.endswith("맞추신 일, 최근에 있었나요?")
    assert v1.endswith("맞추신 일, 최근에 떠오르는 게 있나요?")
    assert v2.endswith("맞추신 일, 최근에 기억나는 것이 있습니까?")
    # 조사를 떼지 않는다 — '…만든 적이 있었어요?' 의 '이'
    assert V.voice_question("Lucas", "그 방향을 팀과 같이 앉아 구체적인 계획으로 만든 적이 있었어요?").endswith("만든 적이 있었나요?")
    # 다른 코치의 꼬리는 그대로
    assert V.voice_question("Jessica", q, variant=2).endswith("기억나는 일이 있으면 말씀해 주십시오.")


def test_b_lucas_fixed_lines_have_no_ellipsis():
    lines = dict(IM.PERSONA_LINES["Lucas"])
    for key, value in lines.items():
        for s in _sentences(value):
            assert not _ELLIPSIS_RE.search(s), (key, s)
    # 그 밖의 Lucas 고정 질문 묶음
    pools = [IM.DEFINITION_VARIANTS["Lucas"], *IM.SMALLTALK_RESERVE["Lucas"].values()]
    for pool in pools:
        for value in pool:
            assert not _ELLIPSIS_RE.search(value) and value.endswith("?"), value
    # 고정 질문 두 개는 서술어로 끝나는 질문
    assert _LUCAS_Q_END_RE.search(_sentences(lines["role_q"])[0]) and _LUCAS_Q_END_RE.search(lines["expect_q"])
    assert lines["definition_reask"].endswith("니까?")
    assert IM.persona_line("Lucas (루카스)", "role_q").endswith("팀 규모와 주요 업무 정도면 됩니다.")


def test_b_lucas_prompt_wording_short_applies_to_receive_only():
    """'짧게'는 받는 말·잇는 말에만 — 질문 문장은 줄이지 않는다는 뜻이 지시문에 있다. 예시 문장·금지 표현은 따옴표로 적지 않는다."""
    pref = V.PROBE_PREFERENCE["Lucas"]
    profile = COACHES_PERSONA["6"]["system_prompt"].split("【말투 프로필】", 1)[1]
    for text in (pref, profile):
        assert "받는 말과 잇는 말" in text and "질문 문장은 줄이지 않는다" in text and "온전한 문장" in text, text
    assert not re.search(r"['\"‘’“”]", pref), pref                               # 탐침 선호에는 따옴표 인용이 없다
    added = profile[profile.index("받는 말과 잇는 말"): profile.index("온전한 문장으로 끝낸다.")]
    assert not re.search(r"['\"‘’“”]", added), added                             # 새로 넣은 대목에도 없다
    assert "한 문장은 짧게" not in profile and not pref.startswith("최단문.")       # 종전 문구(질문에까지 걸리던 '짧게')
    assert "[🎭 탐침 선호 — Lucas]" in V.persona_guide_block("Lucas (루카스)")


# ── C. 같은 답 안내 1문장 ──────────────────────────────────────────────────────

_NOTICE_BANNED = ("다른 장면", "다른 일", "그 일 말고", "사례")


@pytest.mark.parametrize("coach", ALL)
def test_c_repeat_notice_line(coach):
    line = IM.repeat_notice_line(FULL_NAME[coach])
    assert line == IM.persona_line(coach, "repeat_notice") == IM.PERSONA_LINES[coach]["repeat_notice"]
    assert len(_sentences(line)) == 1 and line.endswith(".") and line.count(".") == 1, line   # 한 문장
    assert "?" not in line, line                                                             # 질문 아님
    assert not [w for w in _NOTICE_BANNED if w in line], line
    assert len(line.split()) <= 16, (len(line.split()), line)
    assert "답" in line and "질문" in line and ("다시" in line or "한 번 더" in line), line   # 뜻: 같은 답 → 질문을 다시
    # 코치 말투
    assert _ends_formal(line) if coach in FORMAL else _ends_polite(line), (coach, line)


def test_c_repeat_notice_all_six_and_old_lines_kept():
    lines = [IM.repeat_notice_line(c) for c in ALL]
    assert len(set(lines)) == 6
    assert IM.repeat_notice_line(None) == IM.PERSONA_LINES["Ella"]["repeat_notice"]      # 이름 없음·모르는 이름은 Ella
    # 기존 문구는 지우지 않았다(호출부 정리는 따로)
    for c in ALL:
        assert IM.PERSONA_LINES[c]["repeat_event"] and IM.PERSONA_LINES[c]["repeat_heard"]
        assert IM.duplicate_answer_line(c, 1)[1] is False and IM.duplicate_answer_line(c, 2)[1] is True
    assert len(IM.DUPLICATE_LINES["polite"]["angle"]) == len(IM.DUPLICATE_LINES["formal"]["angle"]) == 3
