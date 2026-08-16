"""A/B/C: 참여 이탈 중단 · 상태 분기 · 부분 리포트 게이팅 단위 테스트.

핵심 원칙(A-0): 중단 트리거는 '근거 부족'이 아니라 '참여 이탈'이다.
  · 부재 진술(성실히 설명, 사례 없음) → engaged → 중단 아님
  · 단답 반복("네"/"없습니다") → empty → 이탈 신호
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.services.avoidance_detector import (  # noqa: E402
    classify_engagement, detect_disengagement_refusal,
)
from diag_project.services.instruction_decider import decide_instruction  # noqa: E402

P = [0, 0]


def ck(label, ok, extra=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label} {extra}")
    P[0] += ok
    P[1] += (not ok)


# ── A-1: 이탈 신호 판정 ──
def test_absence_is_engaged_not_disengaged():
    c, _ = classify_engagement(
        "위임하는 경험은 많지 않습니다. 제가 직접 챙기는 편입니다")
    ck("부재 진술 → engaged(이탈 아님)", c == "engaged")


def test_short_filler_is_empty():
    for t in ["없습니다.", "네.", "글쎄요", "모르겠어요", ""]:
        c, _ = classify_engagement(t)
        ck(f"단답/무응답 → empty ({t!r})", c == "empty")


def test_refusal_detected():
    for t in ["나중에 하겠습니다", "지금은 좀 어렵네요", "그만하죠"]:
        c, _ = classify_engagement(t)
        ck(f"명시적 거부 → refusal ({t!r})", c == "refusal"
           and detect_disengagement_refusal(t))


def test_short_but_substantive_is_engaged():
    c, _ = classify_engagement("직접 했어요")
    ck("짧지만 실질 → engaged", c == "engaged")


# ── A-2/A-3: 중단 트리거 (decide_instruction) ──
def _state(**kw):
    base = {
        "chapter": "people_management", "session_deflection_count": 0,
        "session_already_warned": False, "disengagement_streak": 0,
        "probe_cycles": 0, "last_refusal": False,
        "awaiting_abort_decision": False, "pending_abort": False,
        "last_user_response": "네.",
    }
    base.update(kw)
    return base


def test_abort_confirm_on_streak3_cycles5():
    ins = decide_instruction(_state(disengagement_streak=3, probe_cycles=6))
    ck("연속3 & 사이클6 → ABORT_CONFIRM", ins == "ABORT_CONFIRM", f"(={ins})")


def test_no_abort_before_min_cycles():
    ins = decide_instruction(_state(disengagement_streak=3, probe_cycles=4))
    ck("연속3 but 사이클4(<5) → 중단 안 함", ins != "ABORT_CONFIRM", f"(={ins})")


def test_refusal_immediate_confirm():
    ins = decide_instruction(_state(last_refusal=True, probe_cycles=2))
    ck("명시적 거부 → 사이클<5여도 즉시 ABORT_CONFIRM",
       ins == "ABORT_CONFIRM", f"(={ins})")


def test_pending_abort_returns_disengaged():
    ins = decide_instruction(_state(pending_abort=True))
    ck("pending_abort → ABORT_DISENGAGED", ins == "ABORT_DISENGAGED",
       f"(={ins})")


def test_awaiting_does_not_retrigger_confirm():
    # 확인 대기 중이면 (pending 아님) 재트리거하지 않는다.
    ins = decide_instruction(_state(awaiting_abort_decision=True,
                                    disengagement_streak=3, probe_cycles=6))
    ck("확인 대기 중 → ABORT_CONFIRM 재발 안 함", ins != "ABORT_CONFIRM",
       f"(={ins})")


# ── C-3: 추천 게이팅 ──
def _details(n_measured):
    """n_measured 개의 measured 하위역량을 가진 합성 details."""
    subs = {}
    for i in range(n_measured):
        subs[f"sub{i}"] = {
            "asked": True, "measured": True, "level": 2, "score": 2.0,
            "evidence": [f"지난주에 직접 사례{i}를 처리했습니다"],
            "status": "measured", "gate_status": "passed",
        }
    return {"organization_management": {"name": "조직관리", "sub_ledger": subs}}


def test_recommendation_gating():
    from diag_project.services.course_recommender import (
        build_course_recommendation,
    )

    async def _no_llm_gate(_p):
        return '{"match": false, "reason": "x"}'

    async def run(n):
        return await build_course_recommendation(
            _details(n), transcript="", job_weights={}, llm=_no_llm_gate)

    def _ncards(r):
        if not r:
            return 0
        return len(r.get("growth", [])) + (1 if r.get("strength") else 0)

    loop = asyncio.get_event_loop()
    r0 = loop.run_until_complete(run(0))
    ck("measured 0 → 추천 없음(None)", r0 is None)
    r2 = loop.run_until_complete(run(2))
    ck("measured 2 → 추천 없음(None)", r2 is None)
    r3 = loop.run_until_complete(run(3))
    ck("measured 3 → 카드 발행 & ≤3", r3 is not None and _ncards(r3) <= 3,
       f"(={_ncards(r3)})")
    r6 = loop.run_until_complete(run(6))
    ck("measured 6 → 카드 ≤4(전역 상한)", r6 is not None and _ncards(r6) <= 4,
       f"(={_ncards(r6)})")
    r12 = loop.run_until_complete(run(12))
    ck("measured 12 → 카드 ≤4(전역 상한)", r12 is not None and _ncards(r12) <= 4,
       f"(={_ncards(r12)})")


def _run():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            print(f"— {name}")
            fn()
    print(f"\n=== A/B/C 중단·게이팅: {P[0]} PASS / {P[1]} FAIL ===")
    return P[1]


if __name__ == "__main__":
    sys.exit(1 if _run() else 0)
