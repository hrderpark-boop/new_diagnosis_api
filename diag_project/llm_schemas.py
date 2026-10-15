"""Claude 구조화 출력용 JSON Schema — 분석·서술 호출 4종 (LLM_PROVIDER=claude 에서만 사용).

Gemini 경로는 response_mime_type=application/json 만 쓰고 이 모듈을 참조하지 않는다.
각 스키마는 llm_service 의 해당 프롬프트에 적힌 JSON 템플릿과 키가 1:1 로 같아야 한다
(템플릿을 바꾸면 여기도 함께 고친다).

Claude 구조화 출력 제약(platform.claude.com/docs/en/build-with-claude/structured-outputs, 2026-10-15 확인):
  - object 는 additionalProperties=false 가 필수 → 동적 키(역량 키·하위역량 이름)는 호출 시점에 전개한다.
  - minimum/maximum·minLength/maxLength 미지원 → 점수 범위는 스키마가 아니라 프롬프트·후처리(클램프)가 지킨다.
  - null 허용은 anyOf 로 표현한다(level: 정수 또는 null).
"""
from typing import Any, Dict, Iterable, List


def _obj(props: Dict[str, Any], required: Iterable[str] | None = None) -> Dict[str, Any]:
    return {
        "type": "object",
        "properties": props,
        "required": list(required if required is not None else props.keys()),
        "additionalProperties": False,
    }


def _arr(items: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": "array", "items": items}


_STR: Dict[str, Any] = {"type": "string"}
_NUM: Dict[str, Any] = {"type": "number"}
_INT: Dict[str, Any] = {"type": "integer"}
_BOOL: Dict[str, Any] = {"type": "boolean"}
_INT_OR_NULL: Dict[str, Any] = {"anyOf": [{"type": "integer"}, {"type": "null"}]}


def evidence_extract_schema(competency_keys: Iterable[str]) -> Dict[str, Any]:
    """STEP 1 발화 분류: {역량키: "관련 발언 전문"} — _build_classification_json_template 과 동일 키."""
    keys = list(competency_keys)
    return _obj({k: _STR for k in keys})


def deep_analysis_schema(sub_indicators: List[str] | None) -> Dict[str, Any]:
    """STEP 2 심층분석: _analyze_single_competency 프롬프트의 출력 템플릿.

    sub_assessments 의 키는 하위역량 이름(한글). 비어 있으면 템플릿과 같은 자리표시자를 쓴다
    (_build_sub_scores_json_template 참조).
    """
    names = list(sub_indicators) if sub_indicators else ["핵심지표1", "핵심지표2"]
    step = _obj({"description": _STR, "evidence": _arr(_STR)})
    sub = _obj({
        "measured": _BOOL,
        "level": _INT_OR_NULL,
        "evidence": _arr(_STR),
        "consistency_flag": _BOOL,
    })
    return _obj({
        "reasoning_process": _obj({"1_situation": step, "2_action": step, "3_result": step}),
        "score_breakdown": _obj({
            "rubric_base": _NUM, "star_depth_bonus": _NUM,
            "confidence_adj": _NUM, "final": _NUM,
        }),
        "sub_assessments": _obj({n: sub for n in names}),
        "strength_point": _STR,
        "growth_point": _STR,
        "gap_analysis": _STR,
        "situational_pattern": _STR,
        "behavior_frequency": {"type": "string", "enum": ["높음", "보통", "낮음"]},
        "score": _NUM,
        "comment": _STR,
    })


def level_gate_schema() -> Dict[str, Any]:
    """레벨 게이트(services/level_gate._build_gate_prompt): {"results": [{idx, supported_level, category, reason}]}."""
    item = _obj({
        "idx": _INT,
        "supported_level": _INT,
        "category": {"type": "string", "enum": ["구체행동", "태도", "일반화", "부재"]},
        "reason": _STR,
    })
    return _obj({"results": _arr(item)})


def summary_schema() -> Dict[str, Any]:
    """STEP 3 종합(_generate_comprehensive_summary): feedback_summary·archetype·blind_spot·idp·top_keywords."""
    return _obj({
        "feedback_summary": _STR,
        "archetype": _obj({"name": _STR, "description": _STR}),
        "blind_spot": _STR,
        "idp": _arr(_STR),
        "top_keywords": _arr(_obj({"keyword": _STR, "meaning": _STR})),
    })


def assert_claude_compatible(schema: Dict[str, Any], path: str = "$") -> None:
    """테스트용 자가 점검: 모든 object 에 additionalProperties=false 와 required=전체 키가 있는지 재귀 확인."""
    if not isinstance(schema, dict):
        return
    if schema.get("type") == "object":
        assert schema.get("additionalProperties") is False, f"{path}: additionalProperties 는 false 여야 한다"
        props = schema.get("properties") or {}
        assert set(schema.get("required") or []) == set(props.keys()), f"{path}: required 가 전체 키와 다르다"
        for k, v in props.items():
            assert_claude_compatible(v, f"{path}.{k}")
    for bad in ("minimum", "maximum", "minLength", "maxLength", "pattern"):
        assert bad not in schema, f"{path}: {bad} 는 Claude 구조화 출력이 지원하지 않는다"
    if "items" in schema:
        assert_claude_compatible(schema["items"], f"{path}[]")
    for alt in schema.get("anyOf") or []:
        assert_claude_compatible(alt, f"{path}|anyOf")
