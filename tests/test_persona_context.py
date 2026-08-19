"""§6(b): 페르소나 절삭·요약 주입 단위 테스트 (추적·회귀 포함).

'추적 밖 코드'가 조용히 사는 것을 막기 위해 절삭 로직을 모듈화하고 여기서
고정한다. flag off 무영향 / N=10 절삭 정확 / 사건 요약 주입을 검증.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.persona_context import (  # noqa: E402
    assemble_persona_prompt, summary_block, truncate_history,
)

P = [0, 0]


def ck(label, ok, extra=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label} {extra}")
    P[0] += ok
    P[1] += (not ok)


def _hist(n):
    # 코치/사용자 교대 n턴 (2n 줄)
    lines = []
    for i in range(n):
        lines.append(f"AI 코치: 질문{i}")
        lines.append(f"사용자: 답변{i}")
    return "\n".join(lines)


def test_off_no_truncation_no_summary():
    h = _hist(30)
    # off(n=0): 절삭 없음 + 사건 요약도 안 붙음(오버헤드 0)
    ck("off → 전체 히스토리 유지", truncate_history(h, 0) == h)
    p = assemble_persona_prompt("P", h, "Q", n_turns=0,
                                known_events=["사건A", "사건B"])
    ck("off → 사건 요약 미포함", "이미 말한 사건 요약" not in p)
    ck("off → 전체 히스토리 포함(답변0 남음)", "답변0" in p)


def test_n10_keeps_exactly_10_turns():
    h = _hist(30)  # 30턴
    t = truncate_history(h, 10)
    lines = t.split("\n")
    ck("N=10 → 정확히 20줄(10턴)", len(lines) == 20, f"({len(lines)})")
    ck("N=10 → 최근 유지(답변29 포함)", "답변29" in t)
    ck("N=10 → 오래된 것 절삭(답변0 제거)", "답변0" not in t)
    # 프롬프트 조립에서도 10턴만
    p = assemble_persona_prompt("P", h, "Q", n_turns=10)
    ck("조립 프롬프트도 답변0 제거", "답변0" not in p and "답변29" in p)


def test_summary_block_injected_when_on():
    p = assemble_persona_prompt("P", _hist(30), "Q", n_turns=10,
                                known_events=["팀원 갈등 중재", "마감 자료취합"])
    ck("N>0 → 사건 요약 블록 포함", "이미 말한 사건 요약" in p)
    ck("요약 항목 포함(갈등 중재)", "팀원 갈등 중재" in p)
    # 빈 known_events 면 블록 없음
    ck("사건 없으면 블록 없음", summary_block([]) == ""
       and summary_block(None) == "")


def _run():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            print(f"— {name}")
            fn()
    print(f"\n=== §6(b) 페르소나 절삭·요약: {P[0]} PASS / {P[1]} FAIL ===")
    return P[1]


if __name__ == "__main__":
    sys.exit(1 if _run() else 0)
