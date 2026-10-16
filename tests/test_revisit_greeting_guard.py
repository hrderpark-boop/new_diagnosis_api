"""(2026-10-16) 재방문 인사 출력 가드 — gemini 리플레이에서 첫 세션 INTRO 턴에 "다시 뵙게 되어서" 가 나왔다(LLM·DB 없음)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.services import output_guard as G  # noqa: E402

GEMINI_INTRO = ("네, 다시 뵙게 되어서 저도 반갑습니다. 금요일님의 리더십 역량을 깊이 들여다보고 싶으신 마음, 잘 알겠습니다. "
                "자신을 이해하려는 노력이 리더십 성장의 첫걸음이 되니, 오늘 저희가 함께하는 이 시간이 의미 있을 거예요.")


def test_find_revisit_greeting():
    assert G.find_revisit_greeting(GEMINI_INTRO) == ["다시 뵙게 되"]
    assert G.find_revisit_greeting("오랜만에 뵙네요. 지난번에 이어 가볼까요?") == ["오랜만", "지난번에 이어"]
    assert G.find_revisit_greeting("교육팀장이시군요. 어떤 일을 맡고 계세요?") == []
    # '다시' 자체는 금지가 아니다(되묻기·재시도 문장 보호)
    assert G.find_revisit_greeting("다시 한번 말씀해 주시겠어요?") == []


def test_strip_revisit_sentence_keeps_rest():
    out, n = G.strip_revisit_greeting(GEMINI_INTRO)
    assert n == 1
    assert "다시 뵙" not in out
    assert out.startswith("금요일님의 리더십 역량을")
    assert "의미 있을 거예요." in out


def test_strip_all_revisit_keeps_question_core():
    out, n = G.strip_revisit_greeting("네, 다시 뵙게 되어 반갑습니다! 오늘 오후는 어떻게 보내고 계세요?")
    assert n == 1 and out == "오늘 오후는 어떻게 보내고 계세요?"
    out, n = G.strip_revisit_greeting("다시 뵙게 되어 반갑습니다.")
    assert n == 1 and "다시 뵙" not in out


def test_route_wires_guard_and_excludes_resumed_sitting():
    src = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                            "diag_project", "routes", "diagnoses.py"), encoding="utf-8").read()
    assert 'v["revisit"]' in src and "strip_revisit_greeting(clean_reply)" in src
    assert "_resumed_sitting" in src        # 자리가 바뀐 뒤 첫 턴은 제외
