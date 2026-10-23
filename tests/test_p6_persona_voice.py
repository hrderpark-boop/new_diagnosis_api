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
            out = V.voice_question(p, q)
            assert out.count("?") == 1 and is_question(out), (p, q, out)
    # 페르소나 표지
    q = "그때 리더님은 직접 어떻게 하셨어요?"
    assert V.voice_question("Ella", q) == q
    assert V.voice_question("Jessica", q).endswith("하셨습니까?")
    assert V.voice_question("Daniel", q).endswith("주시겠습니까?")
    assert V.voice_question("Michael", q).startswith("좋습니다, ")
    assert any(V.voice_question("Olivia", q).startswith(l) for l in V._OLIVIA_LEADS)
    lucas = V.voice_question("Lucas", q)
    assert "리더님" not in lucas and len(lucas) < len(q)
    assert V.voice_question("Jessica", "결과까지 책임지게 맡기신 일이 있었어요?") == "결과까지 책임지게 맡기신 일이 있었습니까?"
    assert V.voice_question("Daniel", "그 지표를 보고 실제로 뭘 고치셨어요?") == "그 지표를 보고 실제로 무엇을 고치셨는지 말씀해 주시겠습니까?"
    # 6명 결과가 서로 다르다(같은 입력 → 누군지 맞힐 수 있어야 한다)
    outs = {V.voice_question(p, q) for p in PERSONAS}
    assert len(outs) == 6


def test_contrast_and_preference():
    assert V.is_contrast_question("반대로 했다면 어땠을까요?") and V.is_contrast_question("그때 안 했다면 무엇이 달라졌을까요?")
    assert not V.is_contrast_question("그때 어떻게 하셨어요?")
    assert "숫자·기간" in V.preference_for("Jessica") and "직접 한 행동" in V.preference_for("Michael")
    assert "대조 탐침" in V.preference_for("Olivia") and "이미 썼으니" in V.preference_for("Olivia", contrast_used=True)
    blk = V.persona_guide_block("Lucas (루카스)")
    assert "[🎭 탐침 선호 — Lucas]" in blk and "알겠습니다 / 그렇군요" in blk


def test_wiring():
    src = open(os.path.join(ROOT, "diag_project", "routes", "diagnoses.py"), encoding="utf-8").read()
    assert 'if _mode in ("dict", "fallback"):' in src and "voice_question as _vq" in src and "voice_question as _vq_l" in src
    assert '"contrast_q": int(_tm.get("contrast_q") or 0)' in src and 'state["contrast_used"]' in src
    l3 = open(os.path.join(ROOT, "diag_project", "prompts", "phase3a", "layer3_state.py"), encoding="utf-8").read()
    assert "persona_guide_block(_persona[\"name\"]" in l3
