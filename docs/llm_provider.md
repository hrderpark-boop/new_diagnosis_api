# LLM provider 계층 (2026-10-15)

`LLM_PROVIDER` 환경변수로 LLM 공급자를 고른다. 기본값 `gemini`. 미설정이면 기존 Gemini 경로가 **코드 변경 없이** 그대로 돈다
(분기는 `GeminiService._generate_with_retry` 첫 줄의 `is_claude()` 한 번만).

| 구분 | gemini(기본) | claude |
|---|---|---|
| 코치 턴(실시간, `CHAT_MODEL`) | gemini-2.5-flash | `claude-haiku-5-5` (`CLAUDE_CHAT_MODEL`) |
| 분석·서술(`ANALYSIS_MODEL`) | gemini-2.5-pro | `claude-sonnet-5-5` (`CLAUDE_ANALYSIS_MODEL`) |
| 필수 키 | `GEMINI_API_KEYS` | `ANTHROPIC_API_KEY` — 없으면 **기동 단계**(`main.on_startup`)와 서비스 생성 시 RuntimeError |
| SDK | google-genai | anthropic==1.14.0 (gemini 기본값에서는 import 되지 않음) |

프롬프트 텍스트는 두 provider 가 공유한다. provider 별 차이는 `diag_project/llm_provider.py`(요청 조립·응답 해석)와
`GeminiService._generate_claude`(호출·재시도·계측)에만 있다. 구조화 출력 스키마는 `diag_project/llm_schemas.py`.

## Gemini 인자 → Claude 매핑

| Gemini 호출 인자 | Claude 요청 | 근거(platform.claude.com, 2026-10-15 확인) |
|---|---|---|
| `thinking_budget=0` (코치 턴) | Haiku: `thinking={"type":"disabled"}` / Sonnet 5.5: `{"type":"between_tools"}` | 5.5 세대는 adaptive thinking 기본. Sonnet 5.5 는 `disabled` 거부(400), `between_tools` 가 "생각 없이 텍스트만" |
| `thinking_budget=None`(dynamic) 또는 양수 | `thinking` 생략(adaptive). 깊이는 `CLAUDE_*_EFFORT` | `type:"enabled"+budget_tokens`(extended thinking)는 4.7 이후 모델에서 400 → 지시의 "extended thinking"은 adaptive 로 대응 |
| `temperature` | **보내지 않음** | 5.5 세대는 기본값 외 temperature/top_p/top_k 전부 400. 판정 호출의 temperature=0 결정론은 Claude 에선 불가 |
| `json_mode=True` + `json_schema` | `output_config.format={"type":"json_schema","schema":…}` | 구조화 출력. object 는 `additionalProperties:false` 필수, 수치 범위 제약 미지원 |
| `json_mode=True`, 스키마 없음 | 프롬프트 지시만 | 기존 관용 파서(`_safe_parse_json`)가 처리 |
| `max_tokens` | thinking 켠(adaptive) 호출은 `max(max_tokens, CLAUDE_ADAPTIVE_MAX_TOKENS=32000)` | thinking 토큰이 max_tokens 를 잠식해 JSON 이 잘리는 것 방지. 상한만 올리므로 비용 변화 없음 |
| `system_instruction` | `system` | |
| 응답 텍스트 | content 블록 중 `type=="text"` 만 이어붙임 | 기본 `display=omitted` 로 thinking 블록은 비어서 온다. `stop_reason=refusal` → `LLM_REFUSAL` 예외, `max_tokens` → 경고 로그 |

effort 를 지정하지 않으면 모델 기본(Haiku `medium`, Sonnet `high`). `xhigh`/`max` 에서는 thinking 을 끌 수 없어(400)
`thinking_budget=0` 이어도 adaptive 로 보낸다.

## 오류·재시도·계측

- 재시도는 Gemini 와 같은 `_call_with_retry`. claude 분기에서만 추가 판정: 400 `credit balance is too low` → 즉시 실패
  (`GEMINI_CREDIT_DEPLETED` 마커 유지 → `error_kind=credit`, 관리자 배너), 529 `overloaded` → 503 과 같은 backoff 재시도.
  gemini 기본값에서는 두 판정이 항상 False.
- SDK 자체 재시도는 끈다(`max_retries=0`). 타임아웃은 `LLM_HTTP_TIMEOUT_MS`(90초) 공유. 클라이언트는 이벤트 루프당 1개 재사용.
- 토큰 계측은 `USAGE_METER` 공유(`usage.output_tokens_details.thinking_tokens` 를 thinking 으로 분리). 요율표 `_PRICE` 에
  두 Claude 모델 추가(Haiku 장문 요율 경계 100k 는 200k 경계로 근사).

## 구조화 출력 스키마(llm_schemas.py)

| call_type | 스키마 | 프롬프트 템플릿 |
|---|---|---|
| evidence_extract | `{역량키: string}` (키는 `_get_competency_keys()`) | `_build_classification_json_template` |
| deep_analysis | reasoning_process(S/A/R description+evidence[]) · score_breakdown · sub_assessments{하위역량: measured/level(int|null)/evidence[]/consistency_flag} · strength/growth/gap/situational_pattern · behavior_frequency(enum) · score · comment | `_analyze_single_competency` |
| level_gate | `{"results":[{idx, supported_level, category(enum), reason}]}` | `services/level_gate._build_gate_prompt` |
| summary | feedback_summary · archetype{name,description} · blind_spot · idp[] · top_keywords[{keyword,meaning}] | `_generate_comprehensive_summary` |

프롬프트의 JSON 템플릿을 바꾸면 스키마도 함께 바꾼다(`tests/test_llm_provider.py::test_schemas_are_claude_compatible` 가 제약 위반을 잡는다).

## 전환 절차

1. Render Environment 에 `ANTHROPIC_API_KEY` 추가 → 2. `LLM_PROVIDER=claude` → 3. 재배포(기동 로그 `🧠 LLM provider: claude` 확인).
되돌리기는 `LLM_PROVIDER` 삭제(또는 `gemini`). 파일럿 규칙 P-5b(세션 시간 배포 금지)는 그대로 적용.

알려진 차이: (1) 판정 호출 결정론(temperature 0) 불가 → outer 3회 교집합이 더 중요해진다. (2) 분석 캐시 키에 provider 가 들어가지
않으므로 provider 전환 직후에는 `_ANALYSIS_PROMPT_VERSION` 을 올려 캐시를 무효화할 것(그래야 Claude 결과로 재분석된다).
