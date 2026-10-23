"""(2026-10-23 A) evidence 재선택 — 게이트가 태도·일반화로 거절하면 같은 답변에서 행동 문장을 1회 다시 고른다."""
import asyncio
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project import llm_schemas as S  # noqa: E402
from diag_project.services import level_gate as LG  # noqa: E402

CH = ("코치: 최근에 내년을 보고 하신 결정이 있으셨나요?\n"
      "리더: 최근 추진 중인 AI 에이전트 전면 도입을 내년으로 미루기로 결정했습니다. 팀원들의 역량 내재화와 안정성을 확보한 후 적용하는 것이 "
      "장기적으로 훨씬 효과적이기 때문입니다. 선임급에게는 사전 학습이 먼저라는 이유를 들어 설득했습니다.\n"
      "코치: 그 뒤로는요?\n리더: 기본 교육과 인프라 구축에 집중하고 있습니다.")
OLD = ["장기적으로 훨씬 효과적이기 때문입니다."]


def test_leader_lines_and_verbatim_filter():
    lines = LG.leader_answer_lines(CH, OLD)
    assert len(lines) == 1 and lines[0].startswith("최근 추진 중인")
    picked = LG.filter_verbatim(["AI 에이전트 전면 도입을 내년으로 미루기로 결정했습니다.", "지어낸 문장입니다 절대 없음", "짧다"], lines)
    assert picked == ["AI 에이전트 전면 도입을 내년으로 미루기로 결정했습니다."]
    assert LG.leader_answer_lines(CH, ["없는 근거"]) == [l for l in [x[3:].strip() for x in CH.split("\n") if x.startswith("리더:")]]


def test_reselect_prompt_and_schema():
    p = LG.build_reselect_prompt("전략적 사고", ["리더 답변 한 줄"], OLD)
    assert "실제로 한 행동 문장" in p and "이유·판단·신념" in p and "verbatim" in p
    S.assert_claude_compatible(S.evidence_reselect_schema())


def test_reselect_evidence_uses_llm_and_filters(monkeypatch):
    monkeypatch.setenv("ANALYSIS_CACHE_ENABLED", "0")
    seen = {}

    async def fake_llm(prompt):
        seen["p"] = prompt
        return '{"evidence": ["선임급에게는 사전 학습이 먼저라는 이유를 들어 설득했습니다.", "창작 문장"]}'
    out = asyncio.run(LG.reselect_evidence(fake_llm, "organization_management", "전략적 사고", OLD, CH, provider="claude"))
    assert out == ["선임급에게는 사전 학습이 먼저라는 이유를 들어 설득했습니다."] and "전략적 사고" in seen["p"]

    async def bad_llm(prompt):
        raise RuntimeError("boom")
    assert asyncio.run(LG.reselect_evidence(bad_llm, "organization_management", "전략적 사고", OLD, CH)) == []
    assert asyncio.run(LG.reselect_evidence(fake_llm, "organization_management", "전략적 사고", OLD, "")) == []


def test_pipeline_wiring():
    from diag_project import llm_service as L
    src = inspect.getsource(L.GeminiService._run_level_gate)
    assert "_reselect_dropped_evidence" in src and '"_chapter_text"' in src
    m = inspect.getsource(L.GeminiService._reselect_dropped_evidence)
    assert "RESELECT_CATEGORIES" in m and '"reselected": True' in m and "still_dropped" in m
    full = open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "diag_project", "llm_service.py"), encoding="utf-8").read()
    assert "🚨 행동 문장 우선" in full and 'result["_chapter_text"] = relevant_utterances' in full
    assert LG.RESELECT_CATEGORIES == ("태도", "일반화")
