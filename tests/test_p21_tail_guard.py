"""(2026-10-22 P2-1) 입버릇 반복 가드 — 되받기 마무리 어구 세션 카운트, 금지 어구, '리더님,' 문두 3턴 1회 (LLM·DB 없음)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.services import output_guard as G  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_tail_phrase_and_lead_tails():
    assert G.tail_phrase("팀원들의 얼굴이 풀리고 회의 분위기까지 밝아졌다는 말씀이 마음에 남네요.") == "마음에 남네요"
    assert G.lead_tails("반발한 팀원을 따로 만나셨군요. 그 장면이 그려지네요. 그때 어떻게 하셨어요?") == ["따로 만나셨군요", "장면이 그려지네요"]
    assert G.lead_tails("그때 어떻게 하셨어요?") == []


def test_banned_tails_detected_and_stripped():
    t = "리더님이 만든 안도감이 실제로 팀의 움직임으로 이어진 장면이 그려지네요. 요즘 무엇인가 바꾸려고 시도하신 적 있으세요?"
    assert G.find_banned_tail(t) == ["그려지네요"]
    out, n = G.strip_lead_sentences(t, set())
    assert n == 1 and out == "요즘 무엇인가 바꾸려고 시도하신 적 있으세요?"
    for b in ("마음에 남아요", "짐작이 되네요", "인상에 남네요", "분명하게 들어왔어요"):
        assert G.find_banned_tail(f"그 말씀이 {b}. 그때는요?"), b
    assert G.find_banned_tail("팀원과 따로 만나 이유를 설명하셨군요. 그 뒤로는요?") == []


def test_repeated_tail_stripped_keeps_question_and_fallback_when_empty():
    t = "두 달에 걸쳐 전환하셨군요. 그 뒤로 어떻게 됐어요?"
    out, n = G.strip_lead_sentences(t, {"걸쳐 전환하셨군요"})
    assert n == 1 and out == "그 뒤로 어떻게 됐어요?"
    out2, n2 = G.strip_lead_sentences("두 달에 걸쳐 전환하셨군요.", {"걸쳐 전환하셨군요"})
    assert n2 == 1 and out2 == "그러셨군요."


def test_leading_honorific():
    assert G.starts_with_honorific("리더님, 그 결정은 언제였을까요?") and G.starts_with_honorific("박기진 리더님, 그때는요?")
    assert not G.starts_with_honorific("그때 리더님은 어떻게 하셨어요?")
    assert G.strip_leading_honorific("리더님, 그 결정은 언제였을까요?") == ("그 결정은 언제였을까요?", True)
    assert G.strip_leading_honorific("그때 리더님은요?") == ("그때 리더님은요?", False)


def test_route_wiring():
    src = open(os.path.join(ROOT, "diag_project", "routes", "diagnoses.py"), encoding="utf-8").read()
    assert "# 8-n." in src and '_gl_store["tail_counts"] = _tcg' in src
    assert '"tail": _tm.get("tail")' in src and "strip_leading_honorific as _slh" in src
    assert "any(_swh(_t) for _t in _recent_coach_texts)" in src     # 직전 2턴에 '리더님,' 이 있으면 뗀다
