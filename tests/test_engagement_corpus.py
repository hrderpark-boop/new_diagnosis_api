"""V-4/V-5: 한국어 실사용 이탈 표현 코퍼스 회귀.

classify_engagement 이 실사용 표현을 옳게 분류하는지 고정한다. 신규 오탐/미탐이
발견되면 이 코퍼스에 추가하는 것을 절차로 삼는다(V-5#2).

절차: 오분류가 관측되면 (1) 이 코퍼스에 케이스 추가 (2) 기준 조정 (3) 회귀 통과.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.services.avoidance_detector import (  # noqa: E402
    classify_engagement,
)

P = [0, 0]

# (표현, 기대 분류) — 실사용 코퍼스.
CORPUS = [
    # ── 이탈: 필러/무성의 단답 → empty ──
    ("아 네...", "empty"),
    ("음 그냥 뭐", "empty"),
    ("됐어요", "empty"),
    ("패스", "empty"),
    ("글쎄요 뭐", "empty"),
    ("잘 모르겠는데요", "empty"),
    ("네", "empty"),
    ("없습니다.", "empty"),
    ("", "empty"),
    # ── 이탈: 건너뛰기·거부 의도 → refusal ──
    ("다음에요", "refusal"),
    ("그냥 넘어가죠", "refusal"),
    ("지금은 어렵습니다", "refusal"),
    # ── H4: 휴식·미루기 요청 → pause(이탈 아님, USER_REQUESTS_PAUSE → paused) ──
    #   과거엔 refusal 이었으나 ABORT_CONFIRM 체인 대신 일시중지로 분리했다.
    ("그만하죠", "pause"),
    ("오늘은 그만할게요", "pause"),
    ("나중에 하겠습니다", "pause"),
    ("잠시 쉬었다가 다시 할게요.", "pause"),          # 프론트 '잠시 쉬기' 버튼
    ("오늘은 여기서 잠시 쉴게요.", "pause"),           # 프론트 '다음에 하기' 버튼
    # V-5 의 정중하고 '긴' 미루기·재개 요청도 pause(길이 ≤ PAUSE_MAX_LEN).
    ("죄송한데 오늘 회의가 계속 잡혀 있어서 도저히 집중이 안 되네요, "
     "다음에 다시 하면 안 될까요?", "pause"),
    ("제가 지금 급한 일이 생겨서요, 오늘은 여기까지 하고 다음에 이어서 "
     "진행하면 좋겠습니다.", "pause"),
    # ── 이탈 아님: 성실한 응답(부재 진술 포함) → engaged ──
    ("위임하는 경험은 많지 않습니다. 제가 직접 챙기는 편입니다", "engaged"),
    ("제가 직접 두 팀원을 불러 조율했습니다", "engaged"),
    ("직접 했어요", "engaged"),
    # V-5 회귀: '그만두면 아쉬울까'(=중단 싫다, 계속 원함) → engaged
    ("제가 혹시라도 중간에 그만두면 오늘 나눴던 이야기가 흐지부지될까 "
     "걱정도 됩니다. 괜찮으시다면 조금 더 진행해볼 수 있었으면 좋겠습니다.",
     "engaged"),
    # 과정에 대한 의문(저항)이나 사례를 담은 응답 — 중단 아님
    ("이런 거 꼭 해야 하나요? 그래도 지난주에 팀원 갈등을 중재한 적은 "
     "있습니다.", "engaged"),
]


def _run():
    print("표현 → 분류 (기대 대비)")
    for text, exp in CORPUS:
        got, det = classify_engagement(text)
        ok = got == exp
        P[0] += ok
        P[1] += (not ok)
        mark = "✓" if ok else "✗ FAIL"
        show = (text[:32] + "…") if len(text) > 32 else text
        print(f"  {mark} {got:8}(기대 {exp:8}) :: {show}")
    print(f"\n=== V-4/V-5 이탈 코퍼스: {P[0]} PASS / {P[1]} FAIL ===")
    return P[1]


if __name__ == "__main__":
    sys.exit(1 if _run() else 0)
