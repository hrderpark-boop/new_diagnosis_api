"""(2026-11-02 P3 비용) 분석 비용 절감 — 판정 전용 교차검증 run · 적응형 3회째(갈린 칸 한정) · 게이트 적응 투표."""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GEMINI_API_KEYS", "dummy")

from diag_project import llm_service as LS  # noqa: E402
from diag_project.services import level_gate as LG  # noqa: E402
from diag_project.services.outer_merge import disagreeing_subs, merge_outer_runs, run_evaluated  # noqa: E402


def test_judge_only_tail_and_focus_cache_key(monkeypatch):
    monkeypatch.setattr(LS, "_DEEP_JUDGE_ONLY", True)
    assert LS.judge_only_tail(0) == ""
    t1 = LS.judge_only_tail(1)
    assert "출력 범위" in t1 and "빈 문자열" in t1 and "판정 대상" not in t1 and "sub_assessments" in t1
    t2 = LS.judge_only_tail(2, {"회복탄력성", "중심성"})
    assert "다음 하위역량만 판정한다: 중심성, 회복탄력성" in t2 and "출력 범위" in t2
    monkeypatch.setattr(LS, "_DEEP_JUDGE_ONLY", False)
    assert LS.judge_only_tail(1) == "" and "판정 대상" in LS.judge_only_tail(2, {"중심성"})
    # 한정 판정은 별도 캐시 키, 판정 전용(outer≥1) 전체 판정은 기존 키 그대로
    k_full = LS._deep_cache_keys("self_management", "u", "f", {"a"}, 2, provider="claude")
    k_focus = LS._deep_cache_keys("self_management", "u", "f", {"a"}, 2, provider="claude", focus_subs={"중심성"})
    assert k_full != k_focus
    assert LS._deep_cache_keys("self_management", "u", "f", {"a"}, 1, provider="claude") == \
        LS._deep_cache_keys("self_management", "u", "f", {"a"}, 1, provider="claude", focus_subs=None)
    import inspect
    src = inspect.getsource(LS.GeminiService._analyze_single_competency)
    assert src.index("_split_deep_prompt(prompt)") < src.index("judge_only_tail(outer_idx, focus_subs)") < src.index("_deep_cache_keys(")
    assert 'result["_eval_subs"]' in src


def _row(measured, level, gate="passed", asked=True):
    return {"asked": asked, "measured": measured, "level": level, "score": float(level) if measured else None,
            "evidence": [f"e{level}"] if measured else [], "gate_status": gate if asked else "n_a",
            "status": "measured" if measured else ("evidence_missing" if asked else "unexplored")}


def test_disagreeing_subs_and_merge_with_skipped_third_run():
    r0 = {"sub_ledger": {"A": _row(True, 2), "B": _row(False, None, "n_a")}, "comment": "c0",
          "score_breakdown": {"star_depth_bonus": 0.0, "confidence_adj": 0.0}}
    r1 = {"sub_ledger": {"A": _row(True, 2), "B": _row(False, None, "n_a")}}
    assert disagreeing_subs([r0, r1]) == []
    r1b = {"sub_ledger": {"A": _row(True, 3), "B": _row(False, None, "n_a")}}
    assert disagreeing_subs([r0, r1b]) == ["A"]
    assert disagreeing_subs([r0, {"sub_ledger": {"A": _row(False, None, "failed"), "B": _row(False, None, "n_a")}}]) == ["A"]   # 게이트 탈락도 불일치
    assert disagreeing_subs([r0, {"_error_fallback": True, "sub_ledger": {"A": {}, "B": {}}}]) == ["A", "B"]
    assert disagreeing_subs([r0, None]) == []
    # 3회째 생략(None): 2/2 일치 → stable, 배지 없음, gate_runs 의 evaluated 표식
    m = merge_outer_runs([{"k": r0}, {"k": r1}, {"k": None}], 3)["k"]
    a = m["sub_ledger"]["A"]
    assert a["measured"] and a["level"] == 2 and a["stability"] == "stable" and a["borderline"] is None
    assert [g["evaluated"] for g in a["gate_runs"]] == [True, True, False]
    assert m["sub_ledger"]["B"]["stability"] == "none" and m["measured_count"] == 1 and m["comment"] == "c0"
    assert "_eval_subs" not in m
    # 3회째가 A 만 한정 판정: A 는 3표(2,3,3 → semi·중앙값 3), B 는 앞 두 run 만(none)
    r2 = {"sub_ledger": {"A": _row(True, 3), "B": _row(False, None, "n_a")}, "_eval_subs": ["A"]}
    m2 = merge_outer_runs([{"k": r0}, {"k": r1b}, {"k": r2}], 3)["k"]
    a2 = m2["sub_ledger"]["A"]
    assert a2["stability"] == "semi" and a2["level"] == 3 and a2["borderline"]["flags"] == ["level"] and a2["borderline"]["of"] == 3
    assert [g["evaluated"] for g in m2["sub_ledger"]["B"]["gate_runs"]] == [True, True, False]
    assert run_evaluated(r2, "A") and not run_evaluated(r2, "B") and not run_evaluated(None, "A") and run_evaluated(r0, "B")


def _fake_gate_llm(calls, split_level_for: str):
    async def llm(prompt, _sys=None):
        names = re.findall(r"\[(\d+)\] 하위역량: (.+?) \(", prompt)
        calls.append([n for _, n in names])
        k = len(calls)
        res = []
        for idx, name in names:
            lv = (3 if k == 1 else 2) if name == split_level_for else 2
            res.append({"idx": int(idx), "supported_level": lv, "category": "구체행동", "reason": "판정"})
        return json.dumps({"results": res})
    return llm


def _two_subs():
    from diag_project.data.competencies import COMPETENCY_FRAMEWORK
    subs = [ind["name"] for ind in COMPETENCY_FRAMEWORK["people_management"]["indicators"].values()]
    return subs[0], subs[1]


def _run(coro):
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def test_gate_adaptive_votes_third_only_for_split_items(monkeypatch):
    monkeypatch.setenv("GATE_VOTES", "3")
    monkeypatch.setenv("ANALYSIS_CACHE_ENABLED", "0")
    monkeypatch.setattr(LG, "GATE_VOTES_ADAPTIVE", True)
    LG._GATE_CACHE.clear()
    s1, s2 = _two_subs()
    calls: list = []
    ev = ["2024년 3월 신규 프로젝트에서 팀원에게 결정 권한을 넘기고 주간 리뷰로 확인했습니다"]
    out = _run(LG.gate_verify_levels("people_management",
                                     {s1: {"evidence": ev, "claimed_level": 3}, s2: {"evidence": ev + ["그때 갈등을 따로 만나 풀었습니다"], "claimed_level": 3}},
                                     _fake_gate_llm(calls, s2), provider="claude"))
    assert len(calls) == 3 and sorted(calls[0]) == sorted([s1, s2]) and calls[2] == [s2]   # 3표째는 갈린 칸만
    assert out[s1]["verified_level"] == 2 and out[s1]["votes"] == [2, 2] and out[s1]["downgraded"]
    assert out[s2]["verified_level"] == 2 and sorted(out[s2]["votes"]) == [2, 2, 3]
    assert LG.vote_agrees({"verified_level": 2, "dropped": False}, {"verified_level": 2, "dropped": False})
    assert not LG.vote_agrees({"verified_level": 2, "dropped": False}, {"verified_level": None, "dropped": True})
    assert not LG.vote_agrees({"verified_level": 2, "dropped": False}, LG._pending("x"))
    # 적응 끔: 3표 전부 두 칸
    monkeypatch.setattr(LG, "GATE_VOTES_ADAPTIVE", False)
    LG._GATE_CACHE.clear()
    calls2: list = []
    _run(LG.gate_verify_levels("people_management", {s1: {"evidence": ev, "claimed_level": 3}, s2: {"evidence": ev, "claimed_level": 2}},
                               _fake_gate_llm(calls2, s2), provider="claude"))
    assert len(calls2) == 3 and all(len(c) == 2 for c in calls2)
