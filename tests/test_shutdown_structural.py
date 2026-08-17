"""V-6: 구조적 셧다운 기준 안정성 검증.

절대 측정 수(measured<11)는 경계에서 불안정 — 김보통 4회 실측 measured
5·6·14·11 로 흔들려 정식/부분 리포트가 오락가락했다. 구조 기준(대역량 3개
이상에서 각 2건 이상 measured)은 '자격 대역량 수'로 판정해 ±1~2건 변동에
흔들리지 않는다.

김보통 4회 실측 대역량별 measured:
  run1 [1,1,1,2,0] 자격1 · run2 [1,2,2,1,0] 자격2  → 부분(insufficient)
  run3 [2,3,4,3,2] 자격5 · te   [2,2,4,2,1] 자격4  → 정식(completed)
경계(3)에서 자격 대역량이 1·2 vs 4·5 로 넓게 갈려 안정적.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.services.scoring import (  # noqa: E402
    score_suppressed_structural,
)

P = [0, 0]


def ck(label, ok, extra=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label} {extra}")
    P[0] += ok
    P[1] += (not ok)


def test_kim_bautong_4runs_stable():
    runs = {
        "run1(measured5)": ([1, 1, 1, 2, 0], True),   # 자격1 → 부분
        "run2(measured6)": ([1, 2, 2, 1, 0], True),   # 자격2 → 부분
        "run3(measured14)": ([2, 3, 4, 3, 2], False),  # 자격5 → 정식
        "te(measured11)": ([2, 2, 4, 2, 1], False),   # 자격4 → 정식
    }
    for name, (counts, exp_suppressed) in runs.items():
        got = score_suppressed_structural(counts)
        ck(f"{name} → suppressed={exp_suppressed}", got == exp_suppressed,
           f"(자격 {sum(1 for c in counts if c >= 2)}개)")


def test_boundary_and_scatter():
    # 산발적 measured(대역량당 1건)는 총수가 많아도 정식 발행 안 됨(구조 요구).
    ck("산발 [1,1,1,1,1](measured5, 자격0) → 부분",
       score_suppressed_structural([1, 1, 1, 1, 1]) is True)
    # 깊이 있는 3대역량 2건씩 → 정식
    ck("[2,2,2,0,0](measured6, 자격3) → 정식",
       score_suppressed_structural([2, 2, 2, 0, 0]) is False)
    # 경계 바로 아래(자격2) → 부분
    ck("[2,2,1,1,0](자격2) → 부분",
       score_suppressed_structural([2, 2, 1, 1, 0]) is True)
    # 전량 미측정 → 부분
    ck("[0,0,0,0,0] → 부분", score_suppressed_structural([0, 0, 0, 0, 0]) is True)


def test_not_lowering_bar():
    # 🚨 임계를 낮춰 정식 발행을 늘리지 않는다: measured 10 이 산발이면 부분.
    ck("measured10 산발 [1,1,2,2,4]→자격3? 실제 확인",
       score_suppressed_structural([1, 1, 2, 2, 4]) is False)  # 자격3 → 정식
    ck("measured10 편중 [1,1,1,1,6]→자격1 → 부분",
       score_suppressed_structural([1, 1, 1, 1, 6]) is True)


def _run():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            print(f"— {name}")
            fn()
    print(f"\n=== V-6 구조적 셧다운: {P[0]} PASS / {P[1]} FAIL ===")
    return P[1]


if __name__ == "__main__":
    sys.exit(1 if _run() else 0)
