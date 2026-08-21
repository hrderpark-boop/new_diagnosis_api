"""I-6: outer run 교집합 병합(outer_merge) 순수 함수 고정 테스트. 실행: pytest."""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.services.outer_merge import (  # noqa: E402
    classify_sub, merge_competency, _majority_level,
)


def _row(measured, level, ev=None):
    return {"measured": measured, "level": level,
            "evidence": ev if ev is not None else (["q"] if measured else [])}


def test_stable_all_three_same_level():
    m = classify_sub([_row(True, 1), _row(True, 1), _row(True, 1)], 3)
    assert m["class"] == "stable" and m["measured"] and m["level"] == 1
    assert m["borderline"] is None


def test_semi_two_of_three():
    m = classify_sub([_row(True, 2), _row(False, None), _row(True, 2)], 3)
    assert m["class"] == "semi" and m["measured"] and m["level"] == 2
    assert "detection" in m["borderline"]["flags"]
    assert m["detection_count"] == 2


def test_semi_three_detected_level_split():
    m = classify_sub([_row(True, 2), _row(True, 3), _row(True, 3)], 3)
    assert m["class"] == "semi"          # 3회 탐지지만 레벨 갈림
    assert m["level"] == 3               # 다수결
    assert "level" in m["borderline"]["flags"]
    assert m["borderline"]["level_range"] == [2, 3]


def test_weak_one_of_three_not_measured():
    m = classify_sub([_row(True, 1), _row(False, None), _row(False, None)], 3)
    assert m["class"] == "weak" and not m["measured"]
    assert m["level"] is None            # measured 아님 → 레벨 없음


def test_none_never_detected():
    m = classify_sub([_row(False, None)] * 3, 3)
    assert m["class"] == "none" and not m["measured"]


def test_majority_and_median():
    assert _majority_level([1, 1, 2]) == 1          # 다수결
    assert _majority_level([1, 2, 3]) == 2          # 전부 다르면 중앙값
    assert _majority_level([2, 3]) == 2             # 2개 갈림 → 보수적 최소


def test_evidence_union_dedup():
    m = classify_sub([_row(True, 1, ["a", "b"]), _row(True, 1, ["b", "c"]),
                      _row(True, 1, ["a"])], 3)
    assert m["evidence"] == ["a", "b", "c"]         # 합집합·중복제거·순서보존


def test_shuffle_invariant():
    rows = [_row(True, 2), _row(False, None), _row(True, 3)]
    base = classify_sub(rows, 3)
    for seed in range(10):
        r = rows[:]
        random.Random(seed).shuffle(r)
        m = classify_sub(r, 3)
        assert (m["class"], m["level"]) == (base["class"], base["level"])


def _run(sub_levels, err=False):
    """competency result 하나(한 outer run): {sub: (measured, level)}."""
    led = {s: {"asked": True, "measured": (lv is not None),
               "level": lv, "evidence": (["q"] if lv is not None else [])}
           for s, lv in sub_levels.items()}
    r = {"sub_ledger": led, "score_breakdown": {}}
    if err:
        r["_error_fallback"] = True
        r["_error_reason"] = "크레딧소진"
    return r


def test_merge_measured_and_qualifying_from_stable_semi():
    runs = [_run({"a": 1, "b": 2, "c": 1}),
            _run({"a": 1, "b": 2, "c": None}),
            _run({"a": 1, "b": 3, "c": None})]
    m = merge_competency(runs, "people_management", 3)
    led = m["sub_ledger"]
    assert led["a"]["stability"] == "stable" and led["a"]["measured"]
    assert led["b"]["stability"] == "semi" and led["b"]["measured"]
    assert led["c"]["stability"] == "weak" and not led["c"]["measured"]
    assert m["measured_count"] == 2                 # stable + semi
    assert m["stability_counts"] == {"stable": 1, "semi": 1, "weak": 1}


def test_merge_error_propagates():
    """I-4: 3회 중 1회라도 error-fallback → 병합 결과도 오염 표기."""
    runs = [_run({"a": 1}), _run({"a": 1}, err=True), _run({"a": 1})]
    m = merge_competency(runs, "people_management", 3)
    assert m.get("_error_fallback") is True


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    ok = 0
    for fn in fns:
        fn(); print(f"  [PASS] {fn.__name__}"); ok += 1
    print(f"=== outer_merge: {ok} PASS ===")
