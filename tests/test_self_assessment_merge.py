"""순서1: self-eval 저장이 asked_subs 원장을 보존하는지(병합) 단위 테스트."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.routes.self_eval import merge_self_assessment  # noqa: E402


def test_preserves_asked_subs():
    """asked_subs 가 있는 세션에 자가진단을 병합해도 원장이 보존된다."""
    existing = {
        "asked_subs": {"people_management": ["갈등관리", "코칭 및 피드백"]},
        "last_engagement": "engaged",
    }
    payload = {"scores": {"people_management": 3.0}, "self_average": 3.0,
               "submitted_at": "2026-08-25T00:00:00Z"}
    merged = merge_self_assessment(existing, payload)
    # 원장 보존
    assert merged["asked_subs"] == existing["asked_subs"]
    assert merged["last_engagement"] == "engaged"
    # 자가진단 키 반영
    assert merged["scores"] == {"people_management": 3.0}
    assert merged["self_average"] == 3.0


def test_empty_existing():
    assert merge_self_assessment(None, {"scores": {}}) == {"scores": {}}
    assert merge_self_assessment({}, {"a": 1}) == {"a": 1}


def test_payload_overwrites_same_key_only():
    """같은 키(scores)는 갱신, 다른 키는 유지."""
    existing = {"scores": {"old": 1}, "asked_subs": {"x": ["y"]}}
    merged = merge_self_assessment(existing, {"scores": {"new": 2}})
    assert merged["scores"] == {"new": 2}          # 자가진단 키만 덮어씀
    assert merged["asked_subs"] == {"x": ["y"]}     # 원장 유지


def test_returns_new_object():
    """원본 dict 를 변형하지 않는다(새 객체 반환 → 변경 감지)."""
    existing = {"asked_subs": {"x": ["y"]}}
    merged = merge_self_assessment(existing, {"scores": {}})
    assert merged is not existing
    assert "scores" not in existing  # 원본 불변


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
    ok = 0
    for fn in fns:
        fn(); print(f"  [PASS] {fn.__name__}"); ok += 1
    print(f"=== self-assessment merge: {ok} PASS ===")
