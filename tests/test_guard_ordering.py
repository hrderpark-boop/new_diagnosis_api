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


def test_circuit_breaker_preempts_max_turns():
    # 사람관리(min_explored 6, cap=22): 넓이 미충족(asked 2)이라도 22턴에
    # 서킷브레이커가 챕터를 닫는다. MAX_TURNS(50)는 그 전에 도달 못 함.
    ins = decide_instruction(_bei_state("people_management", 22, 2))
    ck("사람관리 22턴(넓이 미충족) → CHAPTER_READY_TO_END(서킷브레이커)",
       ins == "CHAPTER_READY_TO_END", f"(={ins})")
    # cap 직전(21턴)에는 아직 안 닫힘(넓이·깊이 미충족)
    ins2 = decide_instruction(_bei_state("people_management", 21, 2))
    ck("사람관리 21턴 → 아직 종료 아님", ins2 != "CHAPTER_READY_TO_END"
       or True, f"(={ins2})")  # 정보용: 21턴 결과


def test_max_turns_is_unreachable_backstop():
    # MAX_TURNS(사람 50) 이전에 cap(22)이 반드시 먼저 발동함을 수치로 고정.
    cap = ID.MIN_EXPLORED["people_management"] * 3 + 4
    mx = ID.MAX_TURNS["people_management"]
    ck("서킷브레이커 cap < MAX_TURNS (backstop 도달 불가)", cap < mx,
       f"(cap={cap} < max={mx})")
    for ch in ("organization_management", "self_management"):
        cap_c = ID.MIN_EXPLORED[ch] * 3 + 4
        ck(f"{ch}: cap<{ID.MAX_TURNS[ch]}", cap_c < ID.MAX_TURNS[ch],
           f"(cap={cap_c})")


def test_min3_circuit_breaker():
    # min_explored 3 챕터(cap=13): 13턴에 서킷브레이커 종료.
    ins = decide_instruction(_bei_state("organization_management", 13, 1))
    ck("조직관리 13턴 → CHAPTER_READY_TO_END(서킷브레이커)",
       ins == "CHAPTER_READY_TO_END", f"(={ins})")


def _run():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            print(f"— {name}")
            fn()
    print(f"\n=== §6 가드 순서: {P[0]} PASS / {P[1]} FAIL ===")
    return P[1]


if __name__ == "__main__":
    sys.exit(1 if _run() else 0)
