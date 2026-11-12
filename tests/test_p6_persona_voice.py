"""(2026-10-23, 6번 P4) 페르소나 어미 변환 계층 · 마무리 어구 풀 · 탐침 선호 · 배선(LLM·DB 없음)."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.data.competencies import SUBCOMPETENCY_ANCHOR_QUESTIONS as A  # noqa: E402
from diag_project.services import persona_voice as V  # noqa: E402
from diag_project.services.output_guard import count_questions, find_banned_tail, is_question  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PERSONAS = ["Ella", "Jessica", "Olivia", "Daniel", "Michael", "Lucas"]
ALL_Q = [q for qs in A.values() for q in qs]   # (2026-11-04 BEI) 사다리 질문 사전 삭제 — 앵커 52문만


def test_fixed_receive_tails_are_gone():
    """(2026-11-11 P10-5) 코치별 고정 받기 문구(되받기 마무리 어구 풀)는 전수 삭제 — 프롬프트에도 싣지 않는다."""
    assert not hasattr(V, "PERSONA_TAILS") and not hasattr(V, "tails_for")
    for p in PERSONAS:
        blk = V.persona_guide_block(p)
        assert "마무리 어구" not in blk and "리더가 방금 쓴 낱말" in blk and "되받기" not in blk
        for gone in ("흥미로운 지점", "궤도를 바꿨", "확인했습니다", "그러셨습니까", "그게 움직임"):
            assert gone not in blk, (p, gone)
    assert find_banned_tail("짐작이 되네요.")          # 금지 어구 가드는 그대로


def test_voice_keeps_one_question_and_content():
    for q in ALL_Q:
        for p in PERSONAS:
            for v in (0, 1, 2):
                out = V.voice_question(p, q, variant=v)
                # (2026-11-04 P3-4 2차) Michael 요청형은 물음표 없이 '들려주세요.' 로 끝나는 간접 질문. (3차) 꼬리 3종 변주도 질문 1개
                assert count_questions(out) == 1 and is_question(out), (p, q, out)
                if v == 0:
                    assert out.count("?") == (0 if p == "Michael" else 1), (p, q, out)
    q = "그때 리더님은 직접 어떻게 하셨어요?"
    assert V.voice_question("Ella", q) == q
    o = V.voice_question("Olivia", q)
    assert o != q and o.endswith("을까요?") and not o.startswith(("거꾸로", "다른 쪽", "조금 비켜", "질문을 뒤집", "한 발"))   # (2026-10-28 P0-3) 어미만 바꾸고 도입구는 없다
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








def test_contrast_and_preference():
    assert V.is_contrast_question("반대로 했다면 어땠을까요?") and V.is_contrast_question("그때 안 했다면 무엇이 달라졌을까요?")
    assert not V.is_contrast_question("그때 어떻게 하셨어요?")
    assert "숫자·기간" in V.preference_for("Jessica") and "직접 한 행동" in V.preference_for("Michael")
    # (2026-11-11 P10-2) 대조(가정) 질문은 본 호출이 쓰지 않는다 — 사례 내용을 넣은 슬롯 문장으로만 나간다
    assert "가정을 거는 질문" in V.preference_for("Olivia") and "쓰지 않는다" in V.preference_for("Olivia")
    assert "반대로 했다면" not in V.preference_for("Olivia") and V.preference_for("Olivia", contrast_used=True) == V.preference_for("Olivia")
    blk = V.persona_guide_block("Lucas (루카스)")
    assert "[🎭 탐침 선호 — Lucas]" in blk and "알겠습니다 / 그렇군요" not in blk


