"""1·5: 정의 질문(COMPETENCY_ASK) per-chapter 게이트 고정 테스트.

브릿지의 조기 START_CHAPTER 태깅으로 chapter_started 가 미리 True 여도,
이 챕터에서 정의를 아직 안 물었으면(definition_asked=False) 먼저 묻는다.
이미 물었으면(True) COMPETENCY_ALIGN 으로 넘어간다(재발화 없음).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.services.instruction_decider import decide_instruction  # noqa: E402


def _chapter_entry_state(definition_asked, competency_aligned=False,
                         chapter_started=True):
    """챕터 진입(브릿지로 chapter_started 이미 True) 상태."""
    return {
        "chapter": "performance_management",
        "session_deflection_count": 0, "session_already_warned": False,
        "disengagement_streak": 0, "probe_cycles": 0, "last_refusal": False,
        "awaiting_abort_decision": False, "pending_abort": False,
        "awaiting_continue_decision": False,
        "rapport_complete": True, "intro_done": True,
        "chapter_started": chapter_started,
        "competency_aligned": competency_aligned,
        "definition_asked": definition_asked,
        "name_extraction_failed": False, "name_reconfirm_asked": False,
        "rapport_turn_count": 0, "turn_count": 2,
        "last_user_response": "네, 성과관리는 그냥 목표 달성이죠.",
        "chapter_message_count": 0,
    }


def test_ask_when_not_yet_asked():
    """정의 미질문(브릿지로 chapter_started=True) → COMPETENCY_ASK 먼저."""
    assert decide_instruction(_chapter_entry_state(False)) == "COMPETENCY_ASK"


def test_align_after_asked():
    """정의 질문 완료 → COMPETENCY_ALIGN (재질문 없음)."""
    assert decide_instruction(
        _chapter_entry_state(True)) == "COMPETENCY_ALIGN"


def test_opening_after_aligned():
    """정의 합의까지 끝 → CHAPTER_OPENING(첫 BEI)."""
    assert decide_instruction(
        _chapter_entry_state(True, competency_aligned=True)) == "CHAPTER_OPENING"


def test_no_reask_gate_is_per_chapter():
    """definition_asked=True 면 다시 COMPETENCY_ASK 로 돌아가지 않는다."""
    for aligned in (False, True):
        out = decide_instruction(_chapter_entry_state(True, aligned))
        assert out != "COMPETENCY_ASK", (aligned, out)


def test_align_sublist_matches_competencies():
    """item2 → (2026-10-28 P0-1) ALIGN 하위역량 목록은 프롬프트가 아니라 백엔드 렌더러(render_align)가 붙인다.
    competencies.py 의 목록이 '· ' 줄로 전부 들어가는지 렌더 결과로 확인."""
    from diag_project.services.align_render import render_align, align_shape_ok
    from diag_project.data.competencies import COMPETENCY_FRAMEWORK
    for ck, cv in COMPETENCY_FRAMEWORK.items():
        if ck == "supplementary":
            continue
        subs = [v["name"] for v in cv.get("indicators", {}).values()
                if v.get("name")]
        out = render_align(llm_text="말씀 잘 들었어요.", chapter=ck, sub_names=subs, persona_name="Ella",
                           bridge_sub_key=None, bridge_sub_name=subs[0], anchor="그런 일이 최근에 있었어요?")
        ok, why = align_shape_ok(out, subs)
        assert ok, (ck, why)
        for s in subs:
            assert f"· {s}" in out, f"{ck}: '{s}' 누락"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    ok = 0
    for fn in fns:
        fn(); print(f"  [PASS] {fn.__name__}"); ok += 1
    print(f"=== definition gate: {ok} PASS ===")
