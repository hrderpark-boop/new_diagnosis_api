"""LLM provider 선택 계층 (2026-10-15).

LLM_PROVIDER=gemini(기본) | claude 가 프로세스 기본값. 고객사(companies.llm_provider)별로 다른 provider 를 줄 수 있고,
세션 생성 시 그 값이 diagnosis_sessions.llm_provider 에 고정된다(세션 중간에 바뀌지 않음, null 이면 환경 기본값).
  - 기본값(gemini)이면 이 모듈은 provider 조회 외에 아무 일도 하지 않는다 —
    GeminiService._generate_with_retry 의 기존 Gemini 본문이 그대로 돈다(동작 0 변화).
  - claude 이면 코치 턴(CHAT_MODEL 계열) → claude-haiku-5-5, 분석·서술(ANALYSIS_MODEL) → claude-sonnet-5-5.
프롬프트 텍스트는 두 provider 가 공유하고, provider 별 차이는 요청 조립(build_request)·응답 해석(extract_text)
에만 둔다. 실제 호출·재시도·계측은 llm_service.GeminiService._generate_claude(호출 계층)가 맡는다.

Claude 5.5 세대 API 제약 (platform.claude.com 문서, 2026-10-15 확인):
  - extended thinking(type=enabled + budget_tokens)은 400 — thinking 은 adaptive(기본)이고 깊이는 output_config.effort.
      → Gemini 의 thinking_budget None/양수(dynamic·고정 예산) = adaptive, thinking_budget 0 = thinking 끔.
  - thinking 끄기: Haiku 5.5 는 {"type":"disabled"}(effort high 이하에서만), Sonnet 5.5 는 disabled 를 거부하므로
    {"type":"between_tools"}(도구 없이 쓰면 '생각 없이 텍스트만'과 같다). effort xhigh/max 에서는 둘 다 400 → adaptive 로 둔다.
    (platform.claude.com/docs/en/models/sonnet-5-5/migration-guide#turn-off-up-front-thinking)
  - temperature/top_p/top_k 는 기본값 외 전부 400 → 보내지 않는다(판정 호출의 temperature=0 결정론은 Claude 에선 불가).
    (platform.claude.com/docs/en/models/haiku-5-5/migration-guide#remove-sampling-parameters)
  - JSON 은 output_config.format={"type":"json_schema","schema":...}(구조화 출력). 스키마가 없는 json_mode 호출은
    프롬프트 지시만으로 JSON 을 받는다(기존 관용 파서가 처리).
  - max_tokens 는 thinking 토큰을 포함한다 → adaptive 호출은 CLAUDE_ADAPTIVE_MAX_TOKENS(기본 32000) 하한을 둔다.
  - 기본 display 는 omitted(thinking 본문 미반환). 응답은 content 블록을 type 으로 골라 text 만 이어 붙인다.
"""
import asyncio
import logging
import os
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

GEMINI = "gemini"
CLAUDE = "claude"
VALID_PROVIDERS = (GEMINI, CLAUDE)

DEFAULT_CHAT_MODEL = "claude-haiku-5-5"       # 코치 턴(실시간)
DEFAULT_ANALYSIS_MODEL = "claude-sonnet-5-5"  # 분석·서술(리포트)
_EFFORT_LEVELS = ("low", "medium", "high", "xhigh", "max")
_NO_THINKING_OFF_AT = ("xhigh", "max")        # 이 effort 에서는 thinking 을 끌 수 없다(400)

# Anthropic 크레딧 소진 400 메시지(Gemini 와 문구가 다르다). _call_with_retry 가 즉시 실패 처리에 쓴다.
CREDIT_DEPLETED_PHRASES = ("credit balance is too low",)


def provider_name() -> str:
    """프로세스 기본 provider(LLM_PROVIDER). 세션에 고정된 값이 없을 때의 폴백."""
    return ((os.getenv("LLM_PROVIDER") or GEMINI).strip().lower()) or GEMINI


def anthropic_key_configured() -> bool:
    """ANTHROPIC_API_KEY 존재 여부만(값은 절대 노출하지 않음). /admin/alerts 배너용."""
    return bool((os.getenv("ANTHROPIC_API_KEY") or "").strip())


def is_claude() -> bool:
    return provider_name() == CLAUDE


def validate_provider_config(name: Optional[str] = None) -> str:
    """provider 설정 검증. name 생략 시 환경 기본값(기동 단계 검증).

    잘못된 값·키 누락·SDK 미설치는 명확한 RuntimeError. gemini 는 아무것도 검사하지 않는다
    (기존과 동일 — GEMINI_API_KEYS 는 서비스 생성 시 검사).
    """
    p = (name or provider_name()).strip().lower()
    if p not in VALID_PROVIDERS:
        raise RuntimeError(
            f"LLM_PROVIDER={p!r} 는 지원하지 않는 값입니다. 'gemini'(기본) 또는 'claude' 로 설정하세요."
        )
    if p == CLAUDE:
        if not (os.getenv("ANTHROPIC_API_KEY") or "").strip():
            raise RuntimeError(
                "LLM provider 가 claude 인데 ANTHROPIC_API_KEY 환경변수가 없습니다. "
                "Render Environment(또는 로컬 .env)에 ANTHROPIC_API_KEY 를 등록하거나 provider 를 gemini 로 되돌리세요."
            )
        try:
            import anthropic  # noqa: F401
        except ImportError as e:  # pragma: no cover - 설치 환경 의존
            raise RuntimeError(
                "LLM provider claude 에는 anthropic SDK 가 필요합니다 — requirements.txt 의 anthropic 을 설치하세요."
            ) from e
    return p


# ── 고객사·세션별 provider ──────────────────────────────────────────────────────

def normalize_company_provider(value: Optional[str]) -> Optional[str]:
    """관리자 입력(companies.llm_provider) 정규화. 빈 값 → None(환경 기본값). 모르는 값 → ValueError."""
    v = (value or "").strip().lower()
    if not v:
        return None
    if v not in VALID_PROVIDERS:
        raise ValueError(f"llm_provider 는 {'/'.join(VALID_PROVIDERS)} 중 하나여야 합니다(입력: {value!r})")
    return v


def resolve_for_company(company_value: Optional[str]) -> str:
    """세션 생성 시 고정할 provider: 고객사 값이 있으면 그것, 없으면(null) 환경 기본값.

    모르는 값은 경고 후 환경 기본값(세션 생성이 설정 오타로 막히지 않게).
    """
    v = (company_value or "").strip().lower()
    if v in VALID_PROVIDERS:
        return v
    if v:
        logger.warning("companies.llm_provider=%r 는 알 수 없는 값 — 환경 기본값(%s) 사용", company_value, provider_name())
    return provider_name()


def resolve_session(session_value: Optional[str]) -> str:
    """세션에 고정된 provider(없는 구 세션은 환경 기본값)."""
    v = (session_value or "").strip().lower()
    return v if v in VALID_PROVIDERS else provider_name()


def cache_key_parts(provider: Optional[str]) -> Tuple[str, ...]:
    """분석 캐시 키에 끼울 provider 성분. gemini 는 빈 튜플 → 기존 gemini 캐시 키가 그대로 보존된다.

    claude 는 ("provider:claude",) → 별도 캐시가 생긴다(_ANALYSIS_PROMPT_VERSION 을 올릴 필요 없음).
    """
    p = resolve_session(provider)
    return () if p == GEMINI else (f"provider:{p}",)


# ── 요청 조립 ─────────────────────────────────────────────────────────────────

def chat_model() -> str:
    return (os.getenv("CLAUDE_CHAT_MODEL") or DEFAULT_CHAT_MODEL).strip()


def analysis_model() -> str:
    return (os.getenv("CLAUDE_ANALYSIS_MODEL") or DEFAULT_ANALYSIS_MODEL).strip()


def is_analysis_call(gemini_model: Optional[str], analysis_marker: str) -> bool:
    """호출자가 넘긴 Gemini 모델명으로 '분석 호출'인지 가른다 — ANALYSIS_MODEL(pro) 이면 분석, None·flash 는 코치."""
    if not gemini_model:
        return False
    return gemini_model == analysis_marker or "pro" in gemini_model.lower()


def resolve_model(gemini_model: Optional[str], analysis_marker: str) -> str:
    return analysis_model() if is_analysis_call(gemini_model, analysis_marker) else chat_model()


def effort_for(kind: str) -> Optional[str]:
    """CLAUDE_CHAT_EFFORT / CLAUDE_ANALYSIS_EFFORT. 미설정이면 None(모델 기본: Haiku medium·Sonnet high)."""
    raw = (os.getenv("CLAUDE_ANALYSIS_EFFORT" if kind == "analysis" else "CLAUDE_CHAT_EFFORT") or "").strip().lower()
    if not raw:
        return None
    if raw not in _EFFORT_LEVELS:
        logger.warning("CLAUDE_%s_EFFORT=%r 는 유효한 effort 가 아니다(%s) — 무시", kind.upper(), raw, "/".join(_EFFORT_LEVELS))
        return None
    return raw


def adaptive_max_tokens_floor() -> int:
    try:
        return max(1, int(os.getenv("CLAUDE_ADAPTIVE_MAX_TOKENS", "32000")))
    except (TypeError, ValueError):
        return 32000


def thinking_config(model: str, thinking_budget: Optional[int], effort: Optional[str]) -> Optional[Dict[str, str]]:
    """Gemini thinking_budget → Claude thinking 설정.

    0(끔) → Haiku: disabled / Sonnet 5.5: between_tools. effort xhigh·max 에선 끌 수 없어(400) adaptive 로 둔다.
    None·양수(dynamic·고정 예산) → None(= adaptive 기본, 깊이는 effort).
    """
    if thinking_budget == 0:
        if effort in _NO_THINKING_OFF_AT:
            logger.warning("effort=%s 에서는 thinking 을 끌 수 없어 adaptive 로 보낸다(model=%s)", effort, model)
            return None
        if "sonnet-5-5" in model:
            return {"type": "between_tools"}
        return {"type": "disabled"}
    return None


def build_request(
    *,
    prompt: str,
    system_instruction: Optional[str],
    max_tokens: int,
    json_mode: bool,
    json_schema: Optional[Dict[str, Any]],
    model: Optional[str],
    thinking_budget: Optional[int],
    analysis_marker: str,
) -> Dict[str, Any]:
    """messages.create 인자(dict). temperature/top_p/top_k 는 절대 넣지 않는다(5.5 세대 400)."""
    kind = "analysis" if is_analysis_call(model, analysis_marker) else "chat"
    claude_model = resolve_model(model, analysis_marker)
    effort = effort_for(kind)
    thinking = thinking_config(claude_model, thinking_budget, effort)

    mt = int(max_tokens)
    if thinking is None:
        # adaptive: thinking 토큰이 max_tokens 를 잠식해 JSON 이 잘릴 수 있다 → 하한(상한만 올리므로 비용 변화 없음).
        mt = max(mt, adaptive_max_tokens_floor())

    req: Dict[str, Any] = {
        "model": claude_model,
        "max_tokens": mt,
        "messages": [{"role": "user", "content": prompt}],
    }
    if system_instruction:
        req["system"] = system_instruction
    if thinking is not None:
        req["thinking"] = thinking
    output_config: Dict[str, Any] = {}
    if effort:
        output_config["effort"] = effort
    if json_mode and json_schema:
        output_config["format"] = {"type": "json_schema", "schema": json_schema}
    if output_config:
        req["output_config"] = output_config
    return req


# ── 클라이언트: 이벤트 루프마다 1개(연결 재사용). 재시도는 호출 계층(_call_with_retry)이 하므로 SDK 재시도는 끈다.
_CLIENT_STATE: Dict[str, Any] = {"loop": None, "client": None}


def get_client(timeout_ms: int):
    import anthropic

    loop = asyncio.get_running_loop()
    if _CLIENT_STATE["client"] is None or _CLIENT_STATE["loop"] is not loop:
        _CLIENT_STATE["client"] = anthropic.AsyncAnthropic(
            api_key=(os.getenv("ANTHROPIC_API_KEY") or "").strip(),
            timeout=timeout_ms / 1000.0,
            max_retries=0,
        )
        _CLIENT_STATE["loop"] = loop
    return _CLIENT_STATE["client"]


def extract_text(response: Any) -> str:
    """content 블록 중 text 만 이어 붙인다(thinking 블록은 제외). refusal 은 예외."""
    stop = getattr(response, "stop_reason", None)
    if stop == "refusal":
        raise ValueError("LLM_REFUSAL: Claude 가 요청을 거절했습니다(stop_reason=refusal)")
    parts = []
    for block in (getattr(response, "content", None) or []):
        if getattr(block, "type", "") == "text":
            parts.append(getattr(block, "text", "") or "")
    return "".join(parts)


def usage_counts(response: Any) -> Tuple[int, int, int]:
    """(입력, 보이는 출력, thinking) 토큰. thinking 은 usage.output_tokens_details.thinking_tokens(없으면 0)."""
    u = getattr(response, "usage", None)
    if u is None:
        return 0, 0, 0
    inp = int(getattr(u, "input_tokens", 0) or 0)
    out = int(getattr(u, "output_tokens", 0) or 0)
    det = getattr(u, "output_tokens_details", None)
    think = int(getattr(det, "thinking_tokens", 0) or 0) if det is not None else 0
    return inp, max(0, out - think), think
