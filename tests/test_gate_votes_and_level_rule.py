"""(2026-10-23 D·E) 게이트 투표(merge_votes) · Lv.1 판정 규칙 · claude 전용 게이트 캐시 버전(gemini 키 바이트 유지)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
try:   # 실 LLM 테스트의 skip 판정은 .env 의 키도 본다(수집 시점에 앱이 아직 load_dotenv 를 안 했을 수 있다)
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
except Exception:  # noqa: BLE001
    pass

from diag_project.services import level_gate as LG  # noqa: E402


def _v(level, cat="구체행동", reason="r"):
    return {"verified_level": level, "category": cat, "reason": reason, "downgraded": False, "dropped": level is None, "pending": False}


def test_merge_votes_median_and_majority_drop():
    m = LG.merge_votes([_v(3), _v(2), _v(3)], 3)
    assert m["verified_level"] == 3 and m["votes"] == [3, 2, 3] and not m["downgraded"]
    m2 = LG.merge_votes([_v(2), _v(3)], 3)                       # 짝수면 낮은 쪽
    assert m2["verified_level"] == 2 and m2["downgraded"]
    m3 = LG.merge_votes([_v(None, "태도"), _v(None, "일반화"), _v(2)], 2)   # 과반 탈락
    assert m3["dropped"] and m3["verified_level"] is None and m3["votes"] == [0, 0, 2]
    m4 = LG.merge_votes([_v(None, "태도"), _v(2), _v(2)], 2)     # 탈락 1표는 과반 아님
    assert m4["verified_level"] == 2 and not m4["dropped"]
    assert LG.merge_votes([LG._pending("x"), None], 2)["pending"]


def test_gate_votes_env(monkeypatch):
    monkeypatch.delenv("GATE_VOTES", raising=False)
    assert LG.gate_votes() == LG.GATE_VOTES_DEFAULT == 3
    monkeypatch.setenv("GATE_VOTES", "3"); assert LG.gate_votes() == 3
    monkeypatch.setenv("GATE_VOTES", "0"); assert LG.gate_votes() == 1


def test_gate_prompt_level_rule():
    p = LG._build_gate_prompt([{"sub_name": "전략적 사고", "evidence": ["e"], "claimed_level": 2, "ref": LG.level_reference("organization_management", "전략적 사고")}])
    assert "서술을 모두 대조해 발화에 가장 잘 맞는 것" in p and "자동으로 Lv.n-1 로 내리지 않는다" in p
    assert "Lv.1 은 Lv.1 서술" in p and "실제로 맞을 때만" in p and "강등 또는 유지만" in p


def test_cache_keys_gemini_unchanged_claude_versioned():
    assert LG.GATE_PROMPT_VERSION == "2026-08-17.v1"
    assert LG._persist_key("organization_management", "전략적 사고", ["발화 A"], 3, "gemini") == \
        "2c4b011d4b87f1cbb569569f329459c2b0f3dc753a51206d0b34cbfffc5bf66c"       # 변경 전과 바이트 동일
    assert LG._persist_key("organization_management", "전략적 사고", ["발화 A"], 3, "claude") != \
        LG._persist_key("organization_management", "전략적 사고", ["발화 A"], 3, "gemini")
    assert LG.GATE_PROMPT_VERSION_CLAUDE in LG._cache_key("o", "s", ["e"], 2, "claude")
    assert LG.GATE_PROMPT_VERSION_CLAUDE not in LG._cache_key("o", "s", ["e"], 2, "gemini")


@pytest.mark.skipif(not (os.getenv("FM_LIVE_GATE_TEST") == "1" and os.getenv("ANTHROPIC_API_KEY")),
                    reason="실 LLM 게이트 — FM_LIVE_GATE_TEST=1 과 ANTHROPIC_API_KEY 가 있을 때만")
def test_live_strategic_thinking_is_not_level_one():
    """E 확정 조건: '내년을 보고 미룬 결정'(cbd5210b 전략적 사고 근거)은 Lv.1 로 가면 안 된다."""
    import asyncio
    from diag_project.llm_service import GeminiService, ANALYSIS_MODEL, _JUDGMENT_TEMPERATURE, _GATE_TB
    from diag_project import llm_schemas as S
    os.environ["ANALYSIS_CACHE_ENABLED"] = "0"
    ev = ["최근 추진 중인 AI 에이전트 기반 업무 프로세스 전면 도입을 내년으로 미루기로 결정했습니다.",
          "당장의 적용 속도보다는 팀이 완벽히 준비된 상태에서 안착하는 것을 우선순위로 두었습니다.",
          "그러나 에이전트를 안정적으로 운용하기 위한 사전 학습과 하네스 구조 이해가 먼저라는 이유를 들며 진심으로 설득했습니다."]
    svc = GeminiService().bind_provider("claude")

    async def llm(p):
        return await svc._generate_with_retry(p, max_tokens=8192, json_mode=True, model=ANALYSIS_MODEL, temperature=_JUDGMENT_TEMPERATURE,
                                              thinking_budget=_GATE_TB, call_type="level_gate", json_schema=S.level_gate_schema())
    LG._GATE_CACHE.clear()
    out = asyncio.run(LG.gate_verify_levels("organization_management", {"전략적 사고": {"evidence": ev, "claimed_level": 2}}, llm, provider="claude"))
    assert out["전략적 사고"]["verified_level"] == 2, out
