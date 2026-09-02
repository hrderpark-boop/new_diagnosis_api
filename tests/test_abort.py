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
    # H4 이후: '건너뛰기·거부'만 refusal. 휴식·미루기("나중에 하겠습니다",
    # "오늘은 그만할게요", "그만하죠")는 pause 로 분리됐다(아래 테스트).
    for t in ["다음에요", "그냥 넘어가죠", "지금은 어렵습니다"]:
        c, _ = classify_engagement(t)
        ck(f"명시적 거부(짧음) → refusal ({t!r})", c == "refusal")


def test_pause_intent_is_not_refusal():
    """H4: 휴식·미루기 요청은 이탈(refusal)이 아니라 pause — 프론트 '잠시 쉬기/
    다음에 하기' 버튼 문구가 ABORT_CONFIRM 체인을 타지 않아야 한다."""
    for t in ["나중에 하겠습니다", "오늘은 그만할게요", "그만하죠",
              "잠시 쉬었다가 다시 할게요.", "오늘은 여기서 잠시 쉴게요.",
              "오늘은 여기까지 하고 잠시 쉴게요."]:
        c, _ = classify_engagement(t)
        ck(f"휴식 요청 → pause ({t!r})", c == "pause", f"(={c})")


def test_long_substantive_mentioning_quit_is_engaged():
    """🚨 회귀: 긴 성실한 답변이 '그만두' 등 키워드를 우연히 포함해도
    (부분 문자열) refusal 로 오판하지 않는다 — 김보통 오중단의 원인이었다."""
    t = ("제가 혹시라도 중간에 그만두면 오늘 나눴던 귀한 이야기들이 "
         "흐지부지될까 걱정도 됩니다. 괜찮으시다면 조금 더 진행해볼 수 "
         "있었으면 좋겠습니다. 계속 잘 부탁드립니다.")
    c, _ = classify_engagement(t)
    ck("긴 서술 속 '그만두면' → engaged(중단 아님)", c == "engaged")


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


def test_pause_request_beats_abort_confirm():
    """H4: 휴식 요청은 A-2(ABORT_CONFIRM) 보다 먼저 USER_REQUESTS_PAUSE.
    연속 이탈 3회·사이클 6이라도 pause 문구면 일시중지(재개 가능)로 간다."""
    for t in ["잠시 쉬었다가 다시 할게요.", "오늘은 여기서 잠시 쉴게요."]:
        ins = decide_instruction(_state(
            last_user_response=t, disengagement_streak=3, probe_cycles=6))
        ck(f"pause 문구 → USER_REQUESTS_PAUSE ({t!r})",
           ins == "USER_REQUESTS_PAUSE", f"(={ins})")


def test_pending_abort_still_wins_over_pause():
    """ABORT_CONFIRM 에 '쉴게요'로 답한 경우(pending_abort) 는 중단 확정 유지."""
    ins = decide_instruction(_state(
        pending_abort=True, last_user_response="잠시 쉴게요"))
    ck("pending_abort + pause 문구 → ABORT_DISENGAGED",
       ins == "ABORT_DISENGAGED", f"(={ins})")


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
