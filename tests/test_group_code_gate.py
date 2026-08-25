"""D: group_code 게이트 + 정규화 단위 테스트. 실행: pytest."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.routes.participants import (  # noqa: E402
    _normalize_group_code, evaluate_group_code_gate,
)


def test_normalize_upper_and_strip():
    assert _normalize_group_code("simco") == "SIMCO"
    assert _normalize_group_code(" SIMCO ") == "SIMCO"
    assert _normalize_group_code("  cnc-pilot ") == "CNC-PILOT"
    assert _normalize_group_code(None) == ""
    assert _normalize_group_code("") == ""


def test_gate_enforced_valid_active():
    # 유효 + 활성 → 통과
    assert evaluate_group_code_gate("SIMCO", True, True) == (True, "ok")


def test_gate_enforced_not_found():
    # 코드로 회사 못 찾음(None) → 거부
    ok, reason = evaluate_group_code_gate("NOPE", None, True)
    assert ok is False and reason == "not_found"


def test_gate_enforced_inactive():
    # 회사는 있으나 비활성 → 거부
    ok, reason = evaluate_group_code_gate("OLDCO", False, True)
    assert ok is False and reason == "inactive"


def test_gate_enforced_empty():
    ok, reason = evaluate_group_code_gate("", None, True)
    assert ok is False and reason == "empty"


def test_gate_not_enforced_allows_everything():
    # 킬스위치 OFF → 빈 값·미존재도 기존처럼 통과
    assert evaluate_group_code_gate("", None, False) == (True, "not_enforced")
    assert evaluate_group_code_gate("NOPE", None, False) == (
        True, "not_enforced")


def test_normalized_variants_all_pass_gate():
    """SIMCO / simco / ' SIMCO ' 가 정규화 후 동일 코드로 통과."""
    for raw in ("SIMCO", "simco", " SIMCO ", "SiMcO"):
        code = _normalize_group_code(raw)
        assert code == "SIMCO"
        assert evaluate_group_code_gate(code, True, True) == (True, "ok")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    ok = 0
    for fn in fns:
        fn(); print(f"  [PASS] {fn.__name__}"); ok += 1
    print(f"=== group_code gate: {ok} PASS ===")
