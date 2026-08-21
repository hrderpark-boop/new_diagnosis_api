"""R-1: 추천 후보 결정론 tie-break 순수 함수 고정 테스트.

김보통형(measured 전부 Lv.1 → rec_score 전부 동점)에서 카드 흔들림의
지배 원인이었던 '동점 추첨'을 순수 함수로 못박는다. 실행: pytest.
"""
import os
import random
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.services.course_recommender import (  # noqa: E402
    deterministic_candidate_key, _FRAMEWORK_ORDER,
)
from diag_project.data.competencies import COMPETENCY_FRAMEWORK  # noqa: E402


def _first_subs(n):
    """프레임워크 앞쪽 n개 (comp_key, sub_name) 을 정의 순서대로."""
    out = []
    for ck, cv in COMPETENCY_FRAMEWORK.items():
        if ck == "supplementary":
            continue
        for ind in (cv.get("indicators") or {}).values():
            out.append((ck, ind.get("name")))
    return out[:n]


def _cand(ck, sub, rec=3.0, ev=1, borderline=None):
    return {"comp_key": ck, "sub_name": sub, "rec_score": rec, "score": 1.0,
            "evidence": ["q"] * ev, "borderline": borderline}


def test_all_tied_returns_framework_order():
    """rec_score·근거수·borderline 이 전부 동일 → 프레임워크 고정 순서."""
    subs = _first_subs(5)
    cands = [_cand(ck, s) for ck, s in subs]
    ordered = sorted(reversed(cands), key=deterministic_candidate_key)
    got = [(c["comp_key"], c["sub_name"]) for c in ordered]
    expected = sorted(subs, key=lambda x: _FRAMEWORK_ORDER[x])
    assert got == expected, got


def test_borderline_detection_sinks_below_stable():
    """동점이면 borderline detection 후보가 안정 후보보다 뒤."""
    (ck1, s1), (ck2, s2) = _first_subs(2)
    stable = _cand(ck2, s2, rec=3.0)  # 프레임워크상 뒤지만 안정
    bl = _cand(ck1, s1, rec=3.0, borderline={"flags": ["detection"]})
    ordered = sorted([bl, stable], key=deterministic_candidate_key)
    assert (ordered[0]["comp_key"], ordered[0]["sub_name"]) == (ck2, s2)


def test_borderline_level_sinks_below_stable():
    (ck1, s1), (ck2, s2) = _first_subs(2)
    stable = _cand(ck2, s2, rec=3.0)
    bl = _cand(ck1, s1, rec=3.0, borderline={"flags": ["level"]})
    ordered = sorted([bl, stable], key=deterministic_candidate_key)
    assert (ordered[0]["comp_key"], ordered[0]["sub_name"]) == (ck2, s2)


def test_more_evidence_wins_tie():
    """borderline 동일·rec 동점이면 근거 수 많은 쪽 우선."""
    (ck1, s1), (ck2, s2) = _first_subs(2)
    few = _cand(ck1, s1, rec=3.0, ev=1)   # 프레임워크상 앞
    many = _cand(ck2, s2, rec=3.0, ev=3)  # 프레임워크상 뒤지만 근거 3
    ordered = sorted([few, many], key=deterministic_candidate_key)
    assert (ordered[0]["comp_key"], ordered[0]["sub_name"]) == (ck2, s2)


def test_higher_rec_score_wins_first():
    """rec_score 는 최우선 — 동점 꼬리키보다 앞선다."""
    (ck1, s1), (ck2, s2) = _first_subs(2)
    low = _cand(ck1, s1, rec=2.0)
    high = _cand(ck2, s2, rec=3.5, borderline={"flags": ["detection"]})
    ordered = sorted([low, high], key=deterministic_candidate_key)
    assert ordered[0]["rec_score"] == 3.5  # borderline 이어도 rec 높으면 먼저


def test_shuffle_invariant():
    """입력 순서를 어떻게 섞어도 출력이 동일(랜덤·해시 비의존)."""
    subs = _first_subs(8)
    cands = [_cand(ck, s, rec=3.0, ev=(i % 2) + 1,
                   borderline=({"flags": ["detection"]} if i % 3 == 0 else None))
             for i, (ck, s) in enumerate(subs)]
    base = [(c["comp_key"], c["sub_name"])
            for c in sorted(cands, key=deterministic_candidate_key)]
    for seed in range(20):
        rnd = cands[:]
        random.Random(seed).shuffle(rnd)
        got = [(c["comp_key"], c["sub_name"])
               for c in sorted(rnd, key=deterministic_candidate_key)]
        assert got == base, (seed, got)


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    ok = 0
    for fn in fns:
        fn()
        print(f"  [PASS] {fn.__name__}")
        ok += 1
    print(f"=== R-1 tie-break: {ok} PASS ===")
