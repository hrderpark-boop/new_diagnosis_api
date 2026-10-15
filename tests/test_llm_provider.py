"""LLM provider 계층(2026-10-15) — 기본값 gemini 는 동작 0 변화, claude 분기는 요청 조립·응답 해석·오류 경로 검증.

실제 API 는 호출하지 않는다(anthropic 클라이언트를 가짜로 바꾼다).
"""
import asyncio
import json
import os
import types

import pytest

os.environ.setdefault("GEMINI_API_KEYS", "dummy")

from diag_project import llm_provider as P  # noqa: E402


def _run(coro):
    """asyncio.run 대신 — 다른 테스트 파일(test_level_gate 등)이 get_event_loop() 를 쓰므로
    현재 루프를 비워 두지 않는다(3.12+ 에서 'no current event loop' 유발)."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)

from diag_project import llm_schemas as S  # noqa: E402
from diag_project import llm_service as LS  # noqa: E402


# ── 기본값: gemini ────────────────────────────────────────────────────────────

def test_default_provider_is_gemini_and_needs_no_anthropic_key(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert P.provider_name() == "gemini"
    assert P.is_claude() is False
    assert P.validate_provider_config() == "gemini"


def test_gemini_path_never_touches_claude(monkeypatch):
    """기본값에서 _generate_with_retry 는 claude 분기로 들어가지 않는다(가짜 _generate_claude 가 호출되면 실패)."""
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("GEMINI_API_KEYS", "dummy")   # 전체 스위트에서는 .env 의 실제 키가 먼저 로드될 수 있다
    svc = LS.GeminiService()
    assert svc.available_keys == ["dummy"]

    async def _boom(self, *a, **k):
        raise AssertionError("gemini 기본값에서 claude 분기가 호출되었다")

    monkeypatch.setattr(LS.GeminiService, "_generate_claude", _boom)
    # Gemini 본문은 실제 키가 없으니 '모든 API 키 시도 실패' 로 끝나야 한다(claude 분기 AssertionError 가 아님).
    monkeypatch.setattr(LS, "_call_with_retry", _fail_fast)
    with pytest.raises(Exception) as ei:
        _run(svc._generate_with_retry("p", call_type="coach_light", json_schema={"type": "object"}))
    assert "모든 API 키 시도 실패" in str(ei.value)


async def _fail_fast(call_fn, max_retries=3, backoff_seconds=2.0):
    raise RuntimeError("stub: 네트워크 없음")


# ── 기동 검증 ─────────────────────────────────────────────────────────────────

def test_claude_without_key_fails_clearly(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "claude")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        P.validate_provider_config()
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        LS.GeminiService()


def test_unknown_provider_fails_clearly(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    with pytest.raises(RuntimeError, match="LLM_PROVIDER"):
        P.validate_provider_config()


def test_claude_service_does_not_require_gemini_keys(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("GEMINI_API_KEYS", "")
    svc = LS.GeminiService()
    assert svc.available_keys == []


# ── 요청 조립 ─────────────────────────────────────────────────────────────────

def _req(**kw):
    base = dict(prompt="p", system_instruction="sys", max_tokens=3000, json_mode=False, json_schema=None,
                model=None, thinking_budget=None, analysis_marker=LS.ANALYSIS_MODEL)
    base.update(kw)
    return P.build_request(**base)


def test_coach_turn_maps_to_haiku_with_thinking_off(monkeypatch):
    for k in ("CLAUDE_CHAT_MODEL", "CLAUDE_CHAT_EFFORT", "CLAUDE_ANALYSIS_EFFORT"):
        monkeypatch.delenv(k, raising=False)
    req = _req(model=None, thinking_budget=0, max_tokens=LS.PHASE3A_MAX_TOKENS_LIGHT)
    assert req["model"] == "claude-haiku-5-5"
    assert req["thinking"] == {"type": "disabled"}
    assert req["max_tokens"] == LS.PHASE3A_MAX_TOKENS_LIGHT   # thinking 끈 호출은 하한 적용 안 함
    assert req["system"] == "sys"
    assert req["messages"] == [{"role": "user", "content": "p"}]
    for banned in ("temperature", "top_p", "top_k"):
        assert banned not in req
    assert "output_config" not in req


def test_analysis_call_maps_to_sonnet_adaptive_with_structured_output(monkeypatch):
    for k in ("CLAUDE_ANALYSIS_MODEL", "CLAUDE_ANALYSIS_EFFORT", "CLAUDE_ADAPTIVE_MAX_TOKENS"):
        monkeypatch.delenv(k, raising=False)
    schema = S.summary_schema()
    req = _req(model=LS.ANALYSIS_MODEL, thinking_budget=None, json_mode=True, json_schema=schema, max_tokens=8192)
    assert req["model"] == "claude-sonnet-5-5"
    assert "thinking" not in req                      # adaptive(기본) — extended thinking 은 5.5 에서 400
    assert req["max_tokens"] == 32000                 # adaptive 하한
    assert req["output_config"]["format"] == {"type": "json_schema", "schema": schema}
    assert "effort" not in req["output_config"]       # 미설정 = 모델 기본


def test_fixed_gemini_budget_also_becomes_adaptive():
    req = _req(model=LS.ANALYSIS_MODEL, thinking_budget=2048)
    assert "thinking" not in req


def test_sonnet_thinking_off_uses_between_tools(monkeypatch):
    monkeypatch.delenv("CLAUDE_ANALYSIS_EFFORT", raising=False)
    req = _req(model=LS.ANALYSIS_MODEL, thinking_budget=0)
    assert req["thinking"] == {"type": "between_tools"}


def test_thinking_off_is_dropped_at_xhigh_effort(monkeypatch):
    monkeypatch.setenv("CLAUDE_CHAT_EFFORT", "xhigh")
    req = _req(model=None, thinking_budget=0)
    assert "thinking" not in req                      # 400 회피 → adaptive
    assert req["output_config"]["effort"] == "xhigh"


def test_invalid_effort_is_ignored(monkeypatch):
    monkeypatch.setenv("CLAUDE_CHAT_EFFORT", "turbo")
    req = _req(model=None, thinking_budget=0)
    assert "output_config" not in req


def test_json_mode_without_schema_sends_no_format():
    req = _req(model=LS.ANALYSIS_MODEL, json_mode=True, json_schema=None)
    assert "format" not in req.get("output_config", {})


def test_model_override_env(monkeypatch):
    monkeypatch.setenv("CLAUDE_CHAT_MODEL", "claude-haiku-9-9")
    monkeypatch.setenv("CLAUDE_ANALYSIS_MODEL", "claude-opus-5-5")
    assert _req(model=None)["model"] == "claude-haiku-9-9"
    assert _req(model=LS.ANALYSIS_MODEL)["model"] == "claude-opus-5-5"


# ── 스키마 ───────────────────────────────────────────────────────────────────

def test_schemas_are_claude_compatible():
    keys = LS._get_competency_keys()
    for sch in (S.evidence_extract_schema(keys), S.deep_analysis_schema(["지표A", "지표B"]),
                S.deep_analysis_schema([]), S.level_gate_schema(), S.summary_schema()):
        S.assert_claude_compatible(sch)
    assert set(S.evidence_extract_schema(keys)["properties"]) == set(keys)
    deep = S.deep_analysis_schema(["지표A"])
    assert set(deep["properties"]["sub_assessments"]["properties"]) == {"지표A"}
    assert deep["properties"]["sub_assessments"]["properties"]["지표A"]["properties"]["level"] == \
        {"anyOf": [{"type": "integer"}, {"type": "null"}]}


# ── 응답 해석 ─────────────────────────────────────────────────────────────────

def _resp(blocks, stop="end_turn", usage=None):
    content = [types.SimpleNamespace(type=t, text=x, thinking=x) for t, x in blocks]
    u = None
    if usage:
        inp, out, think = usage
        u = types.SimpleNamespace(
            input_tokens=inp, output_tokens=out,
            output_tokens_details=types.SimpleNamespace(thinking_tokens=think) if think is not None else None)
    return types.SimpleNamespace(content=content, stop_reason=stop, usage=u)


def test_extract_text_skips_thinking_blocks_and_joins_text():
    r = _resp([("thinking", ""), ("text", "안녕"), ("text", "하세요")])
    assert P.extract_text(r) == "안녕하세요"


def test_extract_text_refusal_raises():
    with pytest.raises(ValueError, match="LLM_REFUSAL"):
        P.extract_text(_resp([("text", "no")], stop="refusal"))


def test_usage_counts_splits_thinking():
    assert P.usage_counts(_resp([], usage=(100, 50, 20))) == (100, 30, 20)
    assert P.usage_counts(_resp([], usage=(100, 50, None))) == (100, 50, 0)
    assert P.usage_counts(types.SimpleNamespace(usage=None)) == (0, 0, 0)


# ── 호출 계층(_generate_claude) — 가짜 클라이언트로 끝까지 ───────────────────────

class _FakeMessages:
    def __init__(self, response=None, error=None):
        self.calls = []
        self._response = response
        self._error = error

    async def create(self, **kw):
        self.calls.append(kw)
        if self._error:
            raise self._error
        return self._response


def _fake_client(monkeypatch, response=None, error=None):
    fm = _FakeMessages(response, error)
    monkeypatch.setattr(P, "get_client", lambda timeout_ms: types.SimpleNamespace(messages=fm))
    return fm


def test_generate_claude_coach_turn_end_to_end(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.delenv("CLAUDE_CHAT_EFFORT", raising=False)
    fm = _fake_client(monkeypatch, response=_resp([("text", "그때 어떻게 하셨습니까?  User: 네")],
                                                  usage=(1200, 40, 0)))
    LS.USAGE_METER.reset()
    svc = LS.GeminiService()
    out = _run(svc._generate_with_retry(
        "p", system_instruction="sys", max_tokens=LS.PHASE3A_MAX_TOKENS_LIGHT,
        thinking_budget=0, call_type="coach_light"))
    assert out == "그때 어떻게 하셨습니까?"              # 'User:' 꼬리 제거는 Gemini 와 동일
    req = fm.calls[0]
    assert req["model"] == "claude-haiku-5-5" and req["thinking"] == {"type": "disabled"}
    assert "temperature" not in req
    rows = LS.USAGE_METER.summary()["by_type"]
    assert rows["coach_light[claude-haiku-5-5]"]["input"] == 1200


def test_generate_claude_analysis_structured_json(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    payload = {"results": [{"idx": 1, "supported_level": 2, "category": "구체행동", "reason": "r"}]}
    fm = _fake_client(monkeypatch, response=_resp([("thinking", ""), ("text", json.dumps(payload, ensure_ascii=False))]))
    svc = LS.GeminiService()
    raw = _run(svc._generate_with_retry(
        "p", max_tokens=8192, json_mode=True, model=LS.ANALYSIS_MODEL, temperature=0.0,
        thinking_budget=None, call_type="level_gate", json_schema=S.level_gate_schema()))
    assert json.loads(raw) == payload
    req = fm.calls[0]
    assert req["model"] == "claude-sonnet-5-5"
    assert req["output_config"]["format"]["schema"] == S.level_gate_schema()
    assert "thinking" not in req and "temperature" not in req


def test_generate_claude_empty_response_raises(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "claude")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    _fake_client(monkeypatch, response=_resp([("thinking", "")]))
    monkeypatch.setattr(LS.asyncio, "sleep", _no_sleep)
    svc = LS.GeminiService()
    with pytest.raises(ValueError, match="LLM_EMPTY_RESPONSE"):
        _run(svc._generate_with_retry("p", call_type="coach_light", thinking_budget=0))


async def _no_sleep(_s):
    return None


# ── 오류 경로(_call_with_retry) ────────────────────────────────────────────────

def test_claude_credit_depleted_fails_immediately(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "claude")
    slept = []

    async def _sleep(s):
        slept.append(s)

    monkeypatch.setattr(LS.asyncio, "sleep", _sleep)
    LS.clear_credit_alert()

    async def _call():
        raise RuntimeError("Error code: 400 - {'error': {'message': 'Your credit balance is too low to access the Anthropic API.'}}")

    with pytest.raises(RuntimeError, match="GEMINI_CREDIT_DEPLETED"):
        _run(LS._call_with_retry(_call, max_retries=3))
    assert slept == []                                  # 재시도 대기 없이 즉시 실패
    assert LS.LLM_ALERTS["credit_depleted_at"]          # 관리자 배너 상태 세팅
    LS.clear_credit_alert()


def test_claude_overloaded_is_retried(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "claude")
    monkeypatch.setattr(LS.asyncio, "sleep", _no_sleep)
    n = {"c": 0}

    async def _call():
        n["c"] += 1
        if n["c"] < 3:
            raise RuntimeError("Error code: 529 - {'error': {'type': 'overloaded_error'}}")
        return "ok"

    assert _run(LS._call_with_retry(_call, max_retries=3)) == "ok"
    assert n["c"] == 3


def test_gemini_ignores_claude_only_error_phrases(monkeypatch):
    """기본값 gemini 에서는 claude 전용 판정이 전부 꺼져 있다 — 529 는 재시도 없이 즉시 raise."""
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setattr(LS.asyncio, "sleep", _no_sleep)
    n = {"c": 0}

    async def _call():
        n["c"] += 1
        raise RuntimeError("Error code: 529 overloaded")

    with pytest.raises(RuntimeError):
        _run(LS._call_with_retry(_call, max_retries=3))
    assert n["c"] == 1


# ── 고객사·세션별 provider(2026-10-15 ■4) + 캐시 키(■3) ──────────────────────────

def test_resolve_for_company_null_means_env_default(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert P.resolve_for_company(None) == "gemini"
    assert P.resolve_for_company("") == "gemini"
    assert P.resolve_for_company("claude") == "claude"
    assert P.resolve_for_company(" Claude ") == "claude"
    assert P.resolve_for_company("openai") == "gemini"      # 모르는 값 → 환경 기본값(경고)
    monkeypatch.setenv("LLM_PROVIDER", "claude")
    assert P.resolve_for_company(None) == "claude"
    assert P.resolve_for_company("gemini") == "gemini"      # 고객사 명시값이 환경값보다 우선


def test_normalize_company_provider_rejects_unknown():
    assert P.normalize_company_provider(None) is None
    assert P.normalize_company_provider("  ") is None
    assert P.normalize_company_provider("CLAUDE") == "claude"
    with pytest.raises(ValueError):
        P.normalize_company_provider("openai")


def test_cache_key_parts_preserve_gemini_keys(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    assert P.cache_key_parts(None) == ()
    assert P.cache_key_parts("gemini") == ()
    assert P.cache_key_parts("claude") == ("provider:claude",)
    # deep 캐시 키: gemini 는 provider 인자 유무와 같다(기존 캐시 보존), claude 는 다르다(별도 캐시)
    base = ("org", "u", "t", set(), 0)
    assert LS._deep_cache_keys(*base) == LS._deep_cache_keys(*base, provider="gemini")
    assert LS._deep_cache_keys(*base) != LS._deep_cache_keys(*base, provider="claude")
    from diag_project.services import level_gate as LG
    assert LG._persist_key("org", "s", ["e"], 2) == LG._persist_key("org", "s", ["e"], 2, "gemini")
    assert LG._persist_key("org", "s", ["e"], 2) != LG._persist_key("org", "s", ["e"], 2, "claude")
    assert LG._cache_key("org", "s", ["e"], 2) == LG._cache_key("org", "s", ["e"], 2, "gemini")
    assert LG._cache_key("org", "s", ["e"], 2) != LG._cache_key("org", "s", ["e"], 2, "claude")


def test_bind_provider_fixes_session_provider_over_env(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)             # 환경 기본값 gemini
    monkeypatch.setenv("GEMINI_API_KEYS", "dummy")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    svc = LS.GeminiService()
    assert svc.provider() == "gemini"
    svc.bind_provider("claude")
    assert svc.provider() == "claude" and svc.is_claude()

    seen = {}

    async def _fake_claude(self, prompt, **kw):
        seen["kw"] = kw
        return "ok"

    monkeypatch.setattr(LS.GeminiService, "_generate_claude", _fake_claude)
    assert _run(svc._generate_with_retry("p", call_type="coach_light", thinking_budget=0)) == "ok"
    assert seen["kw"]["call_type"] == "coach_light"
    # 구 세션(null) → 환경 기본값으로 되돌아간다
    svc.bind_provider(None)
    assert svc.provider() == "gemini"


def test_bind_provider_claude_without_key_fails(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    monkeypatch.setenv("GEMINI_API_KEYS", "dummy")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    svc = LS.GeminiService()
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        svc.bind_provider("claude")


def test_models_and_migrations_have_llm_provider():
    from diag_project.models.company import Company
    from diag_project.models.diagnosis_session import DiagnosisSession
    from diag_project import database as DB
    assert "llm_provider" in Company.model_fields
    assert "llm_provider" in DiagnosisSession.model_fields
    ddl = " ".join(DB._LIGHT_MIGRATIONS)
    assert "ALTER TABLE companies ADD COLUMN llm_provider" in ddl
    assert "ALTER TABLE diagnosis_sessions ADD COLUMN llm_provider" in ddl
