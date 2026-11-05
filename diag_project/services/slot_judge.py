"""(2026-11-04 BEI) 슬롯 판정·사례→하위역량 매핑 — Haiku 1콜씩. 실패하면 호출자는 직전 상태를 유지한다.

  judge_slots : 리더 답 직후, 코치 본 호출 전. 사례 전문(여는 앵커부터)과 직전 슬롯 상태 → 6슬롯 filled|partial|empty + 인용(원문 그대로),
                no_case(그런 일이 없다·기억 안 남), switched_case(다른 사례로 넘어감).
  map_episode : 사례 종료 시. 사례 전문 + 챕터 하위역량(이름·설명·'행동:' 단서) → [{sub, strength: strong|weak, quote}].
                strong = 그 하위역량의 '리더 행동'이 원문에 있음. 태도·방침 설명만이면 weak.
FM_LLM_STUB 가 켜져 있으면 LLM 없이 결정론 스텁(1단계 스모크·pytest 용): 리더 턴 n 이면 슬롯 n개가 차고, 매핑은 여는 하위역량 strong.
호출 계층은 llm_service.GeminiService._generate_with_retry(세션 provider: gemini flash / claude haiku). 구조화 출력 스키마는 llm_schemas.
"""
from __future__ import annotations

import json
import logging
import os

from diag_project.services.bei_engine import SLOT_KEYS, SLOT_LABELS, is_no_case_text

logger = logging.getLogger(__name__)

SLOT_JUDGE_PROMPT_VERSION = "2026-11-04.v1"
_SLOT_RULES = (
    "context: 시점(연·분기·'지난달' 같은 상대 표현 포함)과 상대 또는 대상이 둘 다 있으면 filled, 하나만 있으면 partial.\n"
    "action: 리더가 1인칭으로 직접 한 말·결정·행동('제가 …했다')이 있으면 filled. 팀이 한 일·방침·생각만이면 partial.\n"
    "reaction: 상대(팀원·상사·고객)의 말·행동·태도 변화가 하나라도 있으면 filled.\n"
    "result: 그 뒤 달라진 것이 하나 있으면 filled(정성적 변화도 결과). '잘 됐다'만이면 partial.\n"
    "criterion: 왜 그렇게 했는지 이유 또는 버린 선택지·트레이드오프가 하나 있으면 filled.\n"
    "reflection: 돌아보며 바꿀 점 또는 배운 점이 하나 있으면 filled.\n"
)


def _stub_on() -> bool:
    return bool(os.getenv("FM_LLM_STUB"))


def _transcript_text(transcript: list[tuple[str, str]], max_chars: int = 6000) -> str:
    lines = [f"{'코치' if r == 'model' else '리더'}: {t}" for r, t in transcript if (t or "").strip()]
    body = "\n".join(lines)
    return body[-max_chars:]


def _leader_text(transcript: list[tuple[str, str]]) -> str:
    return " ".join(t for r, t in transcript if r == "user")


def _parse(raw: str) -> dict:
    from diag_project.llm_service import _safe_parse_json
    try:
        out = _safe_parse_json(raw or "")
        return out if isinstance(out, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


def _stub_slots(transcript: list[tuple[str, str]], prev_slots: dict | None) -> dict:
    leader_turns = [t for r, t in transcript if r == "user"]
    last = leader_turns[-1] if leader_turns else ""
    no_case = is_no_case_text(last)
    # 실질 답(없다는 답·단답 제외) 하나당 슬롯 하나가 순서대로 찬다 — 인용은 그 답의 앞 30자
    substantive = [t for t in leader_turns if not is_no_case_text(t) and len(t.replace(" ", "")) >= 12]
    slots = {}
    for i, k in enumerate(SLOT_KEYS):
        st = "filled" if i < len(substantive) else "empty"
        slots[k] = {"status": st, "quote": substantive[i][:30] if st == "filled" else ""}
    return {"slots": slots, "no_case": no_case, "switched_case": False, "stub": True}


async def judge_slots(llm, *, transcript: list[tuple[str, str]], prev_slots: dict | None) -> dict:
    """반환: {"slots": {key: {status, quote}}, "no_case": bool, "switched_case": bool, "error": bool}.
    transcript = [("model", 코치 문장), ("user", 리더 답), ...] 여는 앵커부터 이번 답까지."""
    if _stub_on() or llm is None:
        return _stub_slots(transcript, prev_slots)
    from diag_project.llm_schemas import slot_judge_schema
    prev_lines = "\n".join(f"- {SLOT_LABELS[k]}({k}): {(prev_slots or {}).get(k, {}).get('status', 'empty')}" for k in SLOT_KEYS)
    prompt = (
        "아래는 리더십 진단 대화에서 코치가 리더의 '사례 하나'를 듣고 있는 구간입니다. 리더가 지금까지 말한 내용만으로 여섯 슬롯이 "
        "찼는지 판정하세요. 코치의 질문은 근거가 아닙니다. 리더가 말하지 않은 것을 추정하지 마세요.\n\n"
        f"[슬롯 기준]\n{_SLOT_RULES}\n"
        "quote 는 그 슬롯을 채운 리더의 말을 원문 그대로(공백·조사까지 그대로, 40자 이내) 옮기세요. 없으면 빈 문자열.\n"
        "no_case: 리더가 이 질문에 해당하는 일이 없다·기억이 안 난다고 답했으면 true.\n"
        "switched_case: 리더의 마지막 답이 지금 듣던 사례가 아니라 전혀 다른 사례로 넘어갔으면 true(같은 사례의 다른 장면은 false).\n\n"
        f"[직전 판정]\n{prev_lines}\n\n[대화]\n{_transcript_text(transcript)}\n\n"
        "JSON 으로만 답하세요: {\"slots\": {\"context\": {\"status\": \"filled|partial|empty\", \"quote\": \"\"}, ... 6개}, "
        "\"no_case\": false, \"switched_case\": false}"
    )
    try:
        raw = await llm._generate_with_retry(
            prompt=prompt, max_tokens=700, json_mode=True, json_schema=slot_judge_schema(),
            thinking_budget=0, call_type="slot_judge", temperature=0.0,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("슬롯 판정 호출 실패(직전 상태 유지): %s", e)
        return {"slots": {}, "no_case": False, "switched_case": False, "error": True}
    out = _parse(raw)
    slots = out.get("slots") if isinstance(out.get("slots"), dict) else {}
    return {"slots": {k: (slots.get(k) or {}) for k in SLOT_KEYS},
            "no_case": bool(out.get("no_case")), "switched_case": bool(out.get("switched_case")), "error": not bool(slots)}


def _stub_labels(transcript: list[tuple[str, str]], opener_sub: str | None) -> list[dict]:
    first = next((t for r, t in transcript if r == "user"), "")
    return [{"sub": opener_sub, "strength": "strong", "quote": (first or "")[:40]}] if opener_sub else []


async def map_episode(llm, *, transcript: list[tuple[str, str]], chapter_name: str,
                      sub_defs: list[dict], opener_sub: str | None) -> list[dict]:
    """sub_defs = [{"name", "description", "action_cue"}]. 반환 [{sub, strength, quote}] — 인용은 호출자(bei_engine)가 원문 검증하지 않는다;
    여기서 리더 원문에 없는 인용은 quote 를 비운다(strength 는 유지)."""
    if _stub_on() or llm is None:
        return _stub_labels(transcript, opener_sub)
    from diag_project.llm_schemas import episode_map_schema
    from diag_project.services.bei_engine import quote_in_text
    defs = "\n".join(f"- {d['name']}: {d.get('description', '')}" + (f" (행동 단서: {d['action_cue']})" if d.get("action_cue") else "")
                     for d in sub_defs)
    prompt = (
        f"아래는 리더십 진단 '{chapter_name}' 영역에서 리더가 들려준 사례 하나입니다. 이 사례가 아래 하위역량 중 어느 것의 근거가 되는지 "
        "전부 고르세요(여러 개 가능, 해당 없으면 빈 목록).\n"
        "strength: 'strong' = 그 하위역량에 해당하는 **리더가 직접 한 행동**이 리더의 말에 있다. 'weak' = 태도·방침·생각으로만 스쳤다.\n"
        "quote: 근거가 되는 리더의 말을 원문 그대로 40자 이내로. 코치의 말은 근거가 아닙니다.\n\n"
        f"[하위역량]\n{defs}\n\n[사례 대화]\n{_transcript_text(transcript)}\n\n"
        "JSON 으로만 답하세요: {\"labels\": [{\"sub\": \"하위역량 이름(목록 표기 그대로)\", \"strength\": \"strong|weak\", \"quote\": \"\"}]}"
    )
    try:
        raw = await llm._generate_with_retry(
            prompt=prompt, max_tokens=600, json_mode=True, json_schema=episode_map_schema(),
            thinking_budget=0, call_type="episode_map", temperature=0.0,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("사례 매핑 호출 실패(여는 하위역량 weak 로 기록): %s", e)
        return [{"sub": opener_sub, "strength": "weak", "quote": ""}] if opener_sub else []
    out = _parse(raw)
    labels = out.get("labels") if isinstance(out.get("labels"), list) else []
    leader = _leader_text(transcript)
    names = {d["name"] for d in sub_defs}
    clean: list[dict] = []
    for lb in labels:
        if not isinstance(lb, dict):
            continue
        sub = str(lb.get("sub") or "").strip()
        if sub not in names:
            sub = next((n for n in names if sub and (sub in n or n in sub)), "")
        if not sub:
            continue
        quote = str(lb.get("quote") or "").strip()
        clean.append({"sub": sub, "strength": "strong" if str(lb.get("strength") or "").lower() == "strong" else "weak",
                      "quote": quote if quote_in_text(quote, leader) else ""})
    if opener_sub and opener_sub in names and all(c["sub"] != opener_sub for c in clean):
        clean.append({"sub": opener_sub, "strength": "weak", "quote": ""})   # 여는 하위역량은 최소 weak
    return clean


def sub_defs_for(chapter: str) -> list[dict]:
    """매핑 프롬프트 재료: 챕터 하위역량 이름·설명·must_ask 의 '행동:' 항목."""
    from diag_project.data.competencies import COMPETENCY_FRAMEWORK, SUBCOMPETENCY_MUST_ASK
    out = []
    for key, ind in (COMPETENCY_FRAMEWORK.get(chapter, {}).get("indicators") or {}).items():
        cues = [c.split(":", 1)[1].strip() for c in (SUBCOMPETENCY_MUST_ASK.get(key) or []) if c.startswith("행동")]
        out.append({"key": key, "name": ind.get("name", ""), "description": (ind.get("description") or "").strip()[:120],
                    "action_cue": cues[0] if cues else ""})
    return out


def dump(d: dict) -> str:
    return json.dumps(d, ensure_ascii=False)
