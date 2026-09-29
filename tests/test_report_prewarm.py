"""A-2/A-4: 챕터 사전분석(prewarm)·ETA 단위 테스트. 실행: pytest.

  · 챕터 X 의 분석 입력(=캐시 키)은 X 가 끝난 뒤 다른 챕터 대화가 늘어도 그대로,
    X 챕터에 메시지가 추가되면 바뀐다(재개 후 재분석).
  · 사전분석 진행 중인 심층분석 키는 analyze 가 다시 부르지 않고 결과를 공유.
  · 사전분석은 어떤 예외도 밖으로 던지지 않는다(fire-and-forget).
  · ETA 라벨은 순수 함수.
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GEMINI_API_KEYS", "dummy")

from diag_project import llm_service as LS  # noqa: E402
from diag_project.services import report_prewarm as RP  # noqa: E402


def _run_coro(coro):
    loop = asyncio.new_event_loop()   # asyncio.run 은 다른 테스트의 루프를 비운다
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


async def _real_sleep(sec):
    loop = asyncio.get_running_loop()
    fut = loop.create_future()
    loop.call_later(sec, fut.set_result, None)
    await fut


def _msg(role, text, chapter):
    return {"role": role, "parts": text, "chapter": chapter}


HIST = [
    _msg("model", "반갑습니다", None),
    _msg("user", "안녕하세요", None),
    _msg("model", "조직관리 질문", "organization_management"),
    _msg("user", "조직 사례 답변", "organization_management"),
    _msg("model", "성과관리 질문", "performance_management"),
    _msg("user", "성과 사례 답변", "performance_management"),
]
CT = {"organization_management": "리더: 조직 사례 답변",
      "performance_management": "리더: 성과 사례 답변"}
ASKED = {"organization_management": {"변화관리"},
         "performance_management": {"목표설정"}}


def _keys(history, chapter, transcripts=CT):
    data, full_for = LS.GeminiService._chapter_inputs(history, transcripts)
    return LS._deep_cache_keys(chapter, data(chapter), full_for(chapter),
                               ASKED.get(chapter), 0)


def test_chapter_full_transcript_ends_at_chapter():
    _, full_for = LS.GeminiService._chapter_inputs(HIST, CT)
    org = full_for("organization_management")
    assert "조직 사례 답변" in org and "성과" not in org
    assert "성과 사례 답변" in full_for("performance_management")
    # 메시지가 없는 챕터 → 전체 대화(과거 동작)
    assert full_for("self_management").endswith("성과 사례 답변")


def test_no_chapter_info_keeps_legacy_full_transcript():
    legacy = [{"role": m["role"], "parts": m["parts"]} for m in HIST]
    _, full_for = LS.GeminiService._chapter_inputs(legacy, CT)
    assert full_for("organization_management").endswith("성과 사례 답변")


def test_cache_key_stable_after_later_chapters_grow():
    before = _keys(HIST, "organization_management")
    later = HIST + [_msg("model", "사람관리 질문", "people_management"),
                    _msg("user", "사람 사례", "people_management")]
    assert _keys(later, "organization_management") == before


def test_cache_key_changes_when_chapter_itself_changes():
    before = _keys(HIST, "organization_management")
    resumed = HIST + [_msg("user", "조직 사례 보충", "organization_management")]
    ct2 = dict(CT, organization_management=CT["organization_management"]
               + "\n리더: 조직 사례 보충")
    assert _keys(resumed, "organization_management", ct2) != before


def test_deep_inflight_is_shared(monkeypatch):
    """사전분석과 analyze 가 같은 심층분석 키를 동시에 → LLM 1회."""
    monkeypatch.setenv("ANALYSIS_CACHE_ENABLED", "0")
    monkeypatch.setattr(LS, "_SEM_STATE", {"loop": None, "sem": None})
    calls = []

    async def fake_llm(self, prompt, **kw):
        calls.append(1)
        await _real_sleep(0.05)
        return json.dumps({"sub_assessments": {}, "score_breakdown": {}})

    monkeypatch.setattr(LS.GeminiService, "_generate_with_retry", fake_llm)
    svc = LS.GeminiService()

    async def go():
        kw = dict(competency_key="organization_management",
                  relevant_utterances="리더: 답변", full_transcript="전체",
                  asked_subs={"변화관리"}, outer_idx=0)
        return await asyncio.gather(svc._analyze_single_competency(**kw),
                                    svc._analyze_single_competency(**kw))
    a, b = _run_coro(go())
    assert len(calls) == 1
    assert not a.get("_error_fallback") and not b.get("_error_fallback")
    assert not LS._DEEP_INFLIGHT


def test_prewarm_swallows_errors(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("GEMINI_CREDIT_DEPLETED")
    monkeypatch.setattr(LS.GeminiService, "prewarm_chapter", boom)
    # 잘못된 세션 id·알 수 없는 챕터·LLM 실패 모두 예외 없이 끝나야 한다.
    _run_coro(RP.prewarm_chapter_analysis("not-a-uuid", "organization_management"))
    _run_coro(RP.prewarm_chapter_analysis(
        "00000000-0000-0000-0000-000000000000", "no_such_chapter"))
    assert not RP._RUNNING


def test_schedule_without_loop_returns_none():
    assert RP.schedule_chapter_prewarm("x", "organization_management") is None


def test_estimate_label_pure():
    assert RP.estimate_label(5) == "1분 이내"          # 종합·추천만 남음
    assert RP.estimate_label(4).startswith("약 ")
    assert RP.estimate_label(0).startswith("약 ")
    assert RP.estimate_label(99) == RP.estimate_label(5)   # 범위 밖 보정
    assert RP.estimate_seconds(0) < RP.estimate_seconds(1) <= RP.estimate_seconds(5)
    # 진행 중 사전분석이 오래됐을수록 남은 시간이 줄어든다
    assert RP.estimate_seconds(0, [50]) < RP.estimate_seconds(0, [10])
