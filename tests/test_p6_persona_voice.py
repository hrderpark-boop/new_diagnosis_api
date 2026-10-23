"""(2026-10-23, 6번 P4) 페르소나 어미 변환 계층 · 마무리 어구 풀 · 탐침 선호 · 배선(LLM·DB 없음)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.data.competencies import SUBCOMPETENCY_ANCHOR_QUESTIONS as A  # noqa: E402
from diag_project.data.ladder_questions import LADDER_QUESTIONS  # noqa: E402
from diag_project.services import persona_voice as V  # noqa: E402
from diag_project.services.output_guard import find_banned_tail, is_question  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PERSONAS = ["Ella", "Jessica", "Olivia", "Daniel", "Michael", "Lucas"]
ALL_Q = [q for qs in A.values() for q in qs] + [q[s] for q in LADDER_QUESTIONS.values() for s in ("2_3", "3_4")]


def test_tails_five_each_disjoint_and_not_banned():
    seen = set()
    for p in PERSONAS:
        t = V.PERSONA_TAILS[p]
        assert len(t) == 5 and len(set(t)) == 5
        assert not (set(t) & seen), p
        seen |= set(t)
        for x in t:
            assert not find_banned_tail(x), x


def test_voice_keeps_one_question_and_content():
    for q in ALL_Q:
        for p in PERSONAS:
            for v in (0, 1, 2):
                out = V.voice_question(p, q, variant=v)
                assert out.count("?") == 1 and is_question(out), (p, q, out)
    q = "그때 리더님은 직접 어떻게 하셨어요?"
    assert V.voice_question("Ella", q) == q and V.voice_question("Olivia", q) == q        # Olivia: 사전 질문에 도입구를 붙이지 않는다
    assert V.voice_question("Jessica", q).endswith("하셨습니까?")
    assert not V.voice_question("Michael", q).startswith("좋습니다")                       # '좋습니다' 는 턴 가드가 관리
    lucas = V.voice_question("Lucas", q)
    assert "리더님" not in lucas and len(lucas) < len(q)
    assert V.voice_question("Jessica", "결과까지 책임지게 맡기신 일이 있었어요?") == "결과까지 책임지게 맡기신 일이 있었습니까?"
    # Daniel 꼬리 3개 변주 — 서로 다르고, 0·1 은 격식 꼬리
    d = [V.voice_question("Daniel", "그 지표를 보고 실제로 뭘 고치셨어요?", variant=v) for v in (0, 1, 2)]
    assert d[0].endswith("고치셨는지 말씀해 주시겠습니까?") and d[1].endswith("고치셨는지요?") and d[2].endswith("고치셨습니까?")
    assert len(set(d)) == 3 and V.voice_question("Daniel", q, variant=3) == V.voice_question("Daniel", q, variant=0)
    # Jessica·Daniel·Lucas 는 Ella 와 달라야 한다(사전 전부에서)
    for q2 in ALL_Q:
        assert V.voice_question("Jessica", q2) != q2 and V.voice_question("Daniel", q2, variant=0) != q2, q2


def test_michael_lead_guard():
    t = "좋습니다! 좋습니다, 그 방향을 팀과 같이 앉아 구체적인 계획으로 만든 적이 있었어요?"
    out, used = V.michael_lead_guard(t, allow=True)
    assert used and out.count("좋습니다") == 1 and out.startswith("좋습니다, 그 방향을")
    out2, used2 = V.michael_lead_guard(t, allow=False)
    assert not used2 and "좋습니다" not in out2 and out2.startswith("그 방향을")
    out3, used3 = V.michael_lead_guard("그때 직접 뭘 하셨어요?", allow=True)
    assert used3 and out3 == "좋습니다, 그때 직접 뭘 하셨어요?"
    assert V.michael_lead_guard("반갑습니다, 박기진 리더님!", allow=True, add=False) == ("반갑습니다, 박기진 리더님!", False)   # 챕터 밖에는 안 붙임
    t4 = "좋습니다, 기초를 다지신 결정이네요. 좋습니다, 그 아이디어를 작게 시험해 보셨어요?"
    out4, _ = V.michael_lead_guard(t4, allow=True)
    assert out4.count("좋습니다") == 1 and out4.endswith("시험해 보셨어요?")


def test_contrast_lead_and_detection():
    # 도입구만으로는 대조가 아니다 — 사전 질문 앞 도입구는 떼어진다
    t = "네, 파일럿으로 체감을 만들어 주셨군요. 거꾸로 보면요, 그 방향을 팀과 같이 앉아 구체적인 계획으로 만든 적이 있었어요?"
    out, n = V.strip_contrast_lead(t)
    assert n == 1 and "거꾸로 보면요" not in out and not V.is_contrast_question(t)
    # 실제 대조 질문은 도입구를 남기고 대조로 센다
    t2 = "거꾸로 보면요, 그때 파일럿을 안 했다면 팀은 어떻게 움직였을까요?"
    assert V.strip_contrast_lead(t2) == (t2, 0) and V.is_contrast_question(t2)
    assert V.is_contrast_question("반대로 하셨다면 어땠을까요?") and V.is_contrast_question("다른 분이 맡았다면 결과가 달랐을까요?")
    assert not V.is_contrast_question("그때 어떻게 하셨어요?") and not V.is_contrast_question("사실 확인부터 해보겠습니다. 거꾸로 보면요, 최근 결정이 있으셨나요?")


def test_state_leak_and_emotion_statement():
    from diag_project.services.output_guard import find_state_leak, is_emotion_question, strip_state_leak
    t = "사건 두 개가 모두 정리되었습니다. 그 아이디어를 작게 먼저 시험해 보고 고치신 적이 있었습니까?"
    assert find_state_leak(t)
    out, n = strip_state_leak(t)
    assert n == 1 and out == "그 아이디어를 작게 먼저 시험해 보고 고치신 적이 있었습니까?"
    assert find_state_leak("사례 3건이 수집되었습니다.") and not find_state_leak("그 뒤로 어떻게 됐어요?")
    # 감정 '질문' 만 — 평서문은 아니다
    assert not is_emotion_question("그 돌아봄에서, 불안을 먼저 살피신 마음이 느껴지네요.")
    assert is_emotion_question("그때 어떤 마음이 드셨어요?") and is_emotion_question("팀원분이 불리해진다고 느끼셨던 지점을 어떻게 알아채셨는지도 궁금합니다.")


def test_contrast_and_preference():
    assert V.is_contrast_question("반대로 했다면 어땠을까요?") and V.is_contrast_question("그때 안 했다면 무엇이 달라졌을까요?")
    assert not V.is_contrast_question("그때 어떻게 하셨어요?")
    assert "숫자·기간" in V.preference_for("Jessica") and "직접 한 행동" in V.preference_for("Michael")
    assert "대조 탐침" in V.preference_for("Olivia") and "이미 썼으니" in V.preference_for("Olivia", contrast_used=True)
    assert "다른 질문 앞에는 붙이지 않는다" in V.preference_for("Olivia")
    blk = V.persona_guide_block("Lucas (루카스)")
    assert "[🎭 탐침 선호 — Lucas]" in blk and "알겠습니다 / 그렇군요" in blk


def test_wiring():
    src = open(os.path.join(ROOT, "diag_project", "routes", "diagnoses.py"), encoding="utf-8").read()
    assert 'if _mode in ("dict", "fallback"):' in src and "voice_question as _vq" in src and "voice_question as _vq_l" in src
    assert '"contrast_q": int(_tm.get("contrast_q") or 0)' in src and 'state["contrast_used"]' in src
    assert "michael_lead_guard as _mlg" in src and "_allow_good = (_turn_index - 1) not in _good_prev" in src
    assert "strip_contrast_lead as _scl" in src and '_tm["contrast_fix"] = 2' in src and 'voice_variant_count' in src
    l3 = open(os.path.join(ROOT, "diag_project", "prompts", "phase3a", "layer3_state.py"), encoding="utf-8").read()
    assert "persona_guide_block(_persona[\"name\"]" in l3
