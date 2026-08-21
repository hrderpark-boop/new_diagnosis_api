"""V-6(1): composite_shown 경계 + 상태 모델 3종 단위 테스트. 실행: pytest."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.services.scoring import (  # noqa: E402
    composite_shown, COMPOSITE_MIN_MEASURED,
)
from diag_project.routes.reports import (  # noqa: E402
    resolve_completion_status,
)


def test_threshold_is_18_default():
    assert COMPOSITE_MIN_MEASURED == 18


def test_composite_boundary_17_18_19():
    assert composite_shown(17) is False      # 임계 미만 → 종합 미표시
    assert composite_shown(18) is True       # 임계 도달 → 표시
    assert composite_shown(19) is True


def test_composite_extremes():
    assert composite_shown(0) is False
    assert composite_shown(26) is True
    assert composite_shown(None) is False    # 방어: None → False


def test_composite_custom_threshold():
    assert composite_shown(10, threshold=10) is True
    assert composite_shown(9, threshold=10) is False


def test_status_three_states_only():
    # 완주(5) → completed
    assert resolve_completion_status(5) == "completed"
    # 미완주(<5) → in_progress (incomplete/completed_insufficient 안 만든다)
    for c in (0, 1, 2, 3, 4):
        assert resolve_completion_status(c) == "in_progress"
    # 6+(방어) → completed
    assert resolve_completion_status(6) == "completed"


def test_status_never_emits_removed_states():
    removed = {"incomplete", "completed_insufficient"}
    for c in range(0, 7):
        assert resolve_completion_status(c) not in removed


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    ok = 0
    for fn in fns:
        fn(); print(f"  [PASS] {fn.__name__}"); ok += 1
    print(f"=== V-6 composite gate + status: {ok} PASS ===")
