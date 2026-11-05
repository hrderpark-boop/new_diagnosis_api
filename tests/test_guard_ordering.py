"""§6: 상태 전이 가드 도달성 — 상한/게이트가 조기 return 에 가려지지 않는가.

§7-1(온보딩 CONFIRM 이 ONBOARDING_MAX 게이트를 가림), role="assistant"(빈결과
은닉)처럼 '조용히 사는' 도달 불가 분기를 방지한다. 여기서는 챕터 종료 계열의
검사 순서를 고정한다.

발견:
- chapter_over_budget(서킷브레이커, cap=min_explored*3+4=13~22)가
  MAX_TURNS_REACHED(35~50)보다 '낮은' 턴에서 먼저 발동 → MAX_TURNS 는 사실상
  도달 불가한 backstop(무해). 이 순서가 유지되는지(넓이 미충족 시 브레이커가
  챕터를 닫는지) 고정한다.
- 온보딩 하드캡(§7-1)은 test_onboarding_cap 에서 별도 고정.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.services.instruction_decider import decide_instruction  # noqa: E402
from diag_project.services import instruction_decider as ID  # noqa: E402

P = [0, 0]


def ck(label, ok, extra=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label} {extra}")
    P[0] += ok
    P[1] += (not ok)
    # (2026-10-19) pytest 에서도 실패가 드러나도록 — 이전엔 print·카운터만이라 항상 PASS 였다.
    assert ok, f"{label} {extra}".strip()


def _bei_state(chapter, turn_count, asked_ct):
    """온보딩·회피·중단 전부 통과해 '챕터 종료 계열' 검사에 도달하는 상태."""
    return {
        "chapter": chapter, "turn_count": turn_count,
        "session_deflection_count": 0, "session_already_warned": False,
        "disengagement_streak": 0, "probe_cycles": 0, "last_refusal": False,
        "awaiting_abort_decision": False, "pending_abort": False,
        "awaiting_continue_decision": False,
        "rapport_complete": True, "intro_done": True, "chapter_started": True,
        "competency_aligned": True, "chapter_message_count": turn_count,
        "name_extraction_failed": False, "name_reconfirm_asked": False,
        "rapport_turn_count": 0,
        # 정상 실질 응답(회피/거부/메타/무효 아님)
        "last_user_response": "지난주에 팀원과 직접 회의를 열어 역할을 나눴습니다.",
        "contains_avoidance_keywords": False,
        "events_with_star_70": 2,  # _no_strong=False → no-yield 미발동
        "avoidance_count_in_chapter": 0, "no_yield_ultimatum_given": False,
        "has_contrary_probe": False, "duplicate_suspected": False,
        "asked_in_chapter": ["a"] * asked_ct,
        "events_collected": 2,
    }


def test_budget_below_max_turns_and_close_paths():
    """(2026-11-04 BEI) 챕터 종료는 라우트의 사례 단계(예산 16~20)가 먼저 닫는다 — 결정기는 bei_state=close 또는 MAX_TURNS 안전망에서만 닫는다."""
    from diag_project.services import bei_engine as B
    for ch, mx in ID.MAX_TURNS.items():
        if ch == "supplementary":
            continue
        ck(f"{ch} 예산 < MAX_TURNS", B.chapter_budget(ch) < mx, f"({B.chapter_budget(ch)} < {mx})")
    ins = decide_instruction(_bei_state("people_management", 22, 2))
    ck("사람관리 22턴(사례 진행 중) → EPISODE_PROBE(종료는 라우트)", ins == "EPISODE_PROBE", f"(={ins})")
    st = _bei_state("people_management", 22, 2); st["bei_state"] = "close"
    ins2 = decide_instruction(st)
    ck("bei_state=close → CHAPTER_READY_TO_END", ins2 == "CHAPTER_READY_TO_END", f"(={ins2})")
    ins3 = decide_instruction(_bei_state("organization_management", 40, 1))
    ck("조직관리 40턴(MAX_TURNS 안전망) → CHAPTER_READY_TO_END", ins3 == "CHAPTER_READY_TO_END", f"(={ins3})")


def _run():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            print(f"— {name}")
            fn()
    print(f"\n=== §6 가드 순서: {P[0]} PASS / {P[1]} FAIL ===")
    return P[1]


if __name__ == "__main__":
    sys.exit(1 if _run() else 0)
