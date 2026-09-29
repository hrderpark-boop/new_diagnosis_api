"""item6: outer run 병렬화 — 동시 실행되는지, 병합 결과가 순차와 같은지.

LLM 은 가짜(_analyze_single_competency 를 대체, 실제 타이머로 대기)다. 결과는
(대역량, outer_idx) 로 결정되고 outer 마다 달라, 병합이 run 순서를 지키는지 본다.
asyncio.sleep 은 다른 테스트가 전역으로 바꿔 두므로 loop.call_later 로 기다린다.
"""
import asyncio
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GEMINI_API_KEYS", "dummy")

from diag_project import llm_service as LS  # noqa: E402
from diag_project.data.competencies import COMPETENCY_FRAMEWORK  # noqa: E402
from diag_project.services import analysis_progress as AP  # noqa: E402
from diag_project.services import course_recommender as CR  # noqa: E402
from diag_project.services import level_gate as LG  # noqa: E402

DELAY = 0.15


def _run_coro(coro):
    """asyncio.run 은 끝나며 현재 루프를 비워, get_event_loop() 를 쓰는 다른
    테스트(test_level_gate 등)를 깨뜨린다 → 전용 루프로만 돌린다."""
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _real_sleep(sec):
    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    loop.call_later(sec, fut.set_result, None)
    await fut


def _fake_result(key, o):
    subs = [ind["name"] for ind in COMPETENCY_FRAMEWORK[key]["indicators"].values()]
    led = {}
    for i, s in enumerate(subs):
        measured = (i + o) % 3 != 0          # outer 마다 탐지가 다르게
        led[s] = {"asked": True, "measured": measured,
                  "level": (1 + (i + 2 * o) % 4) if measured else None,
                  "evidence": [f"{key}/{s}/o{o}"] if measured else []}
    return {"sub_ledger": led, "comment": f"{key}-o{o}",
            "score_breakdown": {"star_depth_bonus": 0.1 * o,
                                "confidence_adj": 0.0}}


class _Probe:
    def __init__(self):
        self.inflight = 0
        self.max_inflight = 0
        self.outers_seen_together = set()
        self.active = []

    async def fake(self, svc, competency_key, relevant_utterances,
                   full_transcript, asked_subs=None, outer_idx=0,
                   role_summary=None):
        self.inflight += 1
        self.active.append(outer_idx)
        self.max_inflight = max(self.max_inflight, self.inflight)
        self.outers_seen_together.add(frozenset(self.active))
        await _real_sleep(DELAY)
        self.active.remove(outer_idx)
        self.inflight -= 1
        return _fake_result(competency_key, outer_idx)


def _patch(monkeypatch, parallel: bool, probe: _Probe):
    monkeypatch.setattr(LS, "_OUTER_PARALLEL", parallel)
    monkeypatch.setattr(LS, "_ANALYSIS_OUTER_RUNS", 3)
    monkeypatch.setattr(LS, "_ANALYSIS_SAMPLES", 1)
    monkeypatch.setattr(LS.GeminiService, "_analyze_single_competency",
                        lambda self, **kw: probe.fake(self, **kw))

    async def _summary(self, user_name, competency_results):
        return {"feedback_summary": "s", "total_score": 0.0}
    monkeypatch.setattr(LS.GeminiService, "_generate_comprehensive_summary",
                        _summary)

    async def _no_rec(*a, **k):
        return None
    monkeypatch.setattr(CR, "build_course_recommendation", _no_rec)


def _run(keys_progress=None):
    svc = LS.GeminiService()
    keys = LS._get_competency_keys()
    transcripts = {k: f"{k} 대화" for k in keys}
    asked = {k: set() for k in keys}

    async def go():
        t0 = time.monotonic()
        res = await svc.generate_diagnosis_result(
            history=[{"role": "user", "parts": "hi"}], user_name="리더",
            chapter_transcripts=transcripts, asked_subcompetencies=asked,
            progress=keys_progress)
        return res, time.monotonic() - t0
    return _run_coro(go())


def test_outer_runs_are_concurrent_and_merge_matches_sequential(monkeypatch):
    seq_probe = _Probe()
    _patch(monkeypatch, False, seq_probe)
    seq, seq_t = _run()

    par_probe = _Probe()
    _patch(monkeypatch, True, par_probe)
    prog = AP.start("t-par", LS._get_competency_keys(), 3)
    par, par_t = _run(prog)

    # 순차: 한 번에 한 outer run(5-wide) / 병렬: 15 단위가 동시에, outer 섞임
    assert seq_probe.max_inflight == 5
    assert all(len(set(s)) <= 1 for s in seq_probe.outers_seen_together)
    assert par_probe.max_inflight == 15
    assert any(len(set(s)) == 3 for s in par_probe.outers_seen_together)
    assert par_t < seq_t * 0.7, (par_t, seq_t)

    # 병합 결과는 순차 경로와 완전히 같다(run 순서·대역량 순서 포함).
    assert list(par["details"].keys()) == list(seq["details"].keys())
    assert json.dumps(par["details"], sort_keys=True, ensure_ascii=False) == \
        json.dumps(seq["details"], sort_keys=True, ensure_ascii=False)
    assert par["coverage"] == seq["coverage"]
    # run0 서술을 기준으로 쓴다(outer 순서 보존 확인)
    assert all(v["comment"].endswith("-o0") for v in par["details"].values())

    snap = AP.get("t-par")   # 분석 단계 뒤 summary(‖recommend) 로 넘어가 있다
    assert snap["outer_done"] == 3 and snap["stage"] in ("summary", "recommend")
    assert all(len(v) == 3 for v in prog._units.values())


def test_concurrency_cap_bounds_llm_calls(monkeypatch):
    """세마포어 상한: 실제 LLM 호출(_generate_with_retry)이 상한을 넘지 않는다."""
    monkeypatch.setattr(LS, "_ANALYSIS_CONCURRENCY", 4)
    monkeypatch.setattr(LS, "_SEM_STATE", {"loop": None, "sem": None})
    state = {"n": 0, "max": 0}

    async def fake_llm(self, prompt, **kw):
        state["n"] += 1
        state["max"] = max(state["max"], state["n"])
        await _real_sleep(0.05)
        state["n"] -= 1
        return json.dumps({"sub_assessments": {}, "score_breakdown": {}})

    monkeypatch.setattr(LS.GeminiService, "_generate_with_retry", fake_llm)
    monkeypatch.setenv("ANALYSIS_CACHE_ENABLED", "0")
    svc = LS.GeminiService()
    keys = LS._get_competency_keys()

    async def go():
        return await svc._analyze_outer_parallel(
            [{"role": "user", "parts": "hi"}], {k: "t" for k in keys},
            {k: set() for k in keys}, keys, 3)
    out = _run_coro(go())
    assert len(out) == 3 and all(list(r.keys()) == keys for r in out)
    assert state["max"] == 4


def test_gate_shares_inflight_verdict(monkeypatch):
    """병렬 outer 가 같은 후보를 동시에 게이트에 넣으면 LLM 1회로 판정을 공유."""
    monkeypatch.setenv("ANALYSIS_CACHE_ENABLED", "0")
    LG._GATE_CACHE.clear()
    calls = []

    async def gate_llm(prompt):
        calls.append(prompt)
        await _real_sleep(0.05)
        return json.dumps({"results": [
            {"idx": 1, "supported_level": 2, "category": "구체행동",
             "reason": "ok"}]})

    cand = {"권한위임": {"evidence": ["팀원에게 결정권을 넘겼다"],
                        "claimed_level": 3}}

    async def go():
        return await asyncio.gather(*[
            LG.gate_verify_levels("people_management", dict(cand), gate_llm)
            for _ in range(3)])
    res = _run_coro(go())
    assert len(calls) == 1
    assert all(r["권한위임"]["verified_level"] == 2 for r in res)
    assert not LG._INFLIGHT
    LG._GATE_CACHE.clear()


def test_gate_shared_failure_is_rejudged(monkeypatch):
    """공유한 판정이 실패(pending)면 기다린 쪽이 직접 재판정한다."""
    monkeypatch.setenv("ANALYSIS_CACHE_ENABLED", "0")
    monkeypatch.setattr(LG, "GATE_MAX_RETRIES", 1)
    LG._GATE_CACHE.clear()
    calls = []

    async def gate_llm(prompt):
        calls.append(prompt)
        await _real_sleep(0.05)
        if len(calls) == 1:
            return "not json"
        return json.dumps({"results": [
            {"idx": 1, "supported_level": 3, "category": "구체행동",
             "reason": "ok"}]})

    cand = {"권한위임": {"evidence": ["팀원에게 결정권을 넘겼다"],
                        "claimed_level": 3}}

    async def go():
        return await asyncio.gather(
            LG.gate_verify_levels("people_management", dict(cand), gate_llm),
            LG.gate_verify_levels("people_management", dict(cand), gate_llm))
    first, second = _run_coro(go())
    assert first["권한위임"]["pending"] is True
    assert second["권한위임"]["verified_level"] == 3
    assert len(calls) == 2
    assert not LG._INFLIGHT
    LG._GATE_CACHE.clear()
