"""§7-1: 온보딩 턴 상한 — 무한 온보딩·같은 질문 반복 차단 (스크립트, LLM 없음).

투머치토커 원판에서 라포 71턴·asked 0 으로 온보딩이 파탄났다. 원인: chapter
미시작 상태에서 DIAGNOSIS_CONFIRM 이 무한 반복되고 ONBOARDING_MAX 게이트가
그 뒤라 도달 불가. 하드 캡(6턴) 초과 시 즉시 COMPETENCY_ALIGN(→ BEI)으로 전환.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.services.instruction_decider import decide_instruction  # noqa: E402

P = [0, 0]


def ck(label, ok, extra=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label} {extra}")
    P[0] += ok
    P[1] += (not ok)


def _onboarding_state(rapport_turns):
    """라포·인트로 완료·챕터 미시작 상태(온보딩 CONFIRM 단계)."""
    return {
        "chapter": "organization_management",
        "session_deflection_count": 0, "session_already_warned": False,
        "disengagement_streak": 0, "probe_cycles": 0, "last_refusal": False,
        "awaiting_abort_decision": False, "pending_abort": False,
        "awaiting_continue_decision": False,
        "rapport_complete": True, "intro_done": True, "chapter_started": False,
        "competency_aligned": False,
        "name_extraction_failed": False, "name_reconfirm_asked": False,
        "rapport_turn_count": rapport_turns, "turn_count": 0,
        "last_user_response": "네 뭐 그렇죠. 그런데 예전에 제가 신입 때…(장황)",
        "chapter_message_count": 0,
    }


def test_confirm_before_cap():
    # 캡(6) 이전에는 CONFIRM (정상 온보딩 진행)
    ins = decide_instruction(_onboarding_state(3))
    ck("온보딩 3턴 → DIAGNOSIS_CONFIRM", ins == "DIAGNOSIS_CONFIRM", f"(={ins})")


def test_cap_forces_transition():
    # 캡(6) 도달 → CONFIRM 무한반복 대신 COMPETENCY_ALIGN 으로 강제 전환
    for t in (6, 8, 20, 71):
        ins = decide_instruction(_onboarding_state(t))
        ck(f"온보딩 {t}턴 → COMPETENCY_ALIGN(BEI 전환)",
           ins == "COMPETENCY_ALIGN", f"(={ins})")


def test_no_infinite_confirm():
    # 71턴에서 CONFIRM 이 다시 나오면 실패(투머치 사고 재현)
    ins = decide_instruction(_onboarding_state(71))
    ck("71턴에서 CONFIRM 무한반복 안 함", ins != "DIAGNOSIS_CONFIRM", f"(={ins})")


def _run():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            print(f"— {name}")
            fn()
    print(f"\n=== §7-1 온보딩 캡: {P[0]} PASS / {P[1]} FAIL ===")
    return P[1]


if __name__ == "__main__":
    sys.exit(1 if _run() else 0)
