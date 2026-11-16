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
import re
import os

from diag_project.services.bei_engine import SLOT_KEYS, SLOT_LABELS, is_no_case_text

logger = logging.getLogger(__name__)

SLOT_JUDGE_PROMPT_VERSION = "2026-11-15.v2"   # (P13-1) 행동 채움 기준 상향 · 반응은 리더가 이끌거나 함께 일하는 사람만
_SLOT_RULES = (
    "context: 시점(연·월·분기·'지난달' 같은 상대 표현 포함)과 상대(사람 이름·직함) 또는 대상(무슨 일인지)이 둘 다 있으면 filled — "
    "한 문장에 짧게 함께 나와도 채운 것이다. 하나만 있으면 partial.\n"
    # (2026-11-15 P13-1) 11/14 운영 Lucas: 여는 답의 한 줄 요약('…하자고 제안했습니다')만으로 행동이 채움이 되어 리더 본인의 행동을 묻는 질문이 0이었다
    "action: 리더가 직접 한 구체적인 말(그때 한 말을 옮긴 것)이나 조치(누구에게 무엇을 어떻게 했는지)가 하나 이상 있으면 filled. "
    "'…하기로 했다'·'…하자고 했다'·'…하도록 했다' 수준의 한 줄 요약이나 팀이 한 일·방침·생각만이면 partial.\n"
    "reaction: 리더가 이끌거나 함께 일하는 사람(팀원·상사·동료·협업자)의 말·행동·태도 변화가 하나라도 있으면 filled. "
    "교육생·고객처럼 팀 밖 사람의 반응은 reaction 이 아니라 result 로 본다.\n"
    "result: 그 뒤 달라진 것이 하나 있으면 filled(정성적 변화, 팀 밖 사람의 반응·만족도도 결과). '잘 됐다'만이면 partial.\n"
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
    return {"slots": slots, "no_case": no_case, "switched_case": False, "incident": not no_case, "stub": True, "specific": True}


async def judge_slots(llm, *, transcript: list[tuple[str, str]], prev_slots: dict | None, closed_cases: dict | None = None) -> dict:
    """반환: {"slots": {key: {status, quote}}, "no_case": bool, "switched_case": bool, "error": bool, "same_as": 표지|None}.
    transcript = [("model", 코치 문장), ("user", 리더 답), ...] 여는 앵커부터 이번 답까지.
    (2026-11-14 P12e-4) closed_cases = {표지: 그 이야기에서 리더가 한 말} — 이번 영역에서 이미 닫힌 이야기 가운데 이번 답과 낱말이 겹치는 후보.
      주어지면 같은 호출에 항목 하나(same_as)를 더해 '리더가 한 결정·행동이 닫힌 이야기와 같은가'를 판정한다(추가 호출 없음). 애매하면 다른 장면."""
    if _stub_on() or llm is None:
        return _stub_slots(transcript, prev_slots)
    from diag_project.llm_schemas import slot_judge_schema
    prev_lines = "\n".join(f"- {SLOT_LABELS[k]}({k}): {(prev_slots or {}).get(k, {}).get('status', 'empty')}" for k in SLOT_KEYS)
    _cc = {str(k): re.sub(r"\s+", " ", str(v or "")).strip()[:500] for k, v in (closed_cases or {}).items() if str(v or "").strip()}
    _same_block = ""
    if _cc:
        _same_block = (
            # (2026-11-15 P13e-2) 기준을 '같은 때·같은 사람·같은 일'에서 '리더가 한 결정·행동이 같은가'로 바꿨다 — p13d Olivia·Lucas: 같은 개편 과제에서
            #   나온 다른 결정(운영 횟수를 줄이고 교재를 다시 만들기로 함)을 닫힌 사례(교육 목표를 현장 적용으로 바꿈)와 같은 장면으로 판정했다.
            "same_as: 아래 [앞에서 이미 들은 이야기] 가운데, 리더의 마지막 답에 나온 **리더의 결정·행동이 그 이야기의 결정·행동과 같은 것**이 있으면 그 표지를 그대로 쓴다. "
            "같은 프로젝트·같은 시기·같은 사람들이 나오더라도 마지막 답에 그 이야기에 없던 새로운 결정이나 행동이 있으면 다른 장면이다 — 그때는 빈 문자열. "
            "어느 쪽인지 애매하면 다른 장면으로 본다. '아까 말씀드린' 같은 말이 있어도 결정·행동이 다른 일이면 다른 장면이다.\n"
            "[앞에서 이미 들은 이야기]\n" + "\n".join(f"- ({k}) {v}" for k, v in _cc.items()) + "\n")
    prompt = (
        "아래는 리더십 진단 대화에서 코치가 리더의 '사례 하나'를 듣고 있는 구간입니다. 리더가 지금까지 말한 내용만으로 여섯 슬롯이 "
        "찼는지 판정하세요. 코치의 질문은 근거가 아닙니다. 리더가 말하지 않은 것을 추정하지 마세요.\n\n"
        f"[슬롯 기준]\n{_SLOT_RULES}\n"
        "quote 는 그 슬롯을 채운 리더의 말을 원문 그대로(공백·조사까지 그대로, 40자 이내) 옮기세요. 없으면 빈 문자열.\n"
        "no_case: 리더가 이 질문에 해당하는 일이 없다·기억이 안 난다고 답했으면 true.\n"
        "specific: 리더의 **마지막 답**에 구체 표지가 있으면 true — 숫자·수량, 구체 시점(날짜·요일·몇 주 뒤), 실제로 한 말의 인용, "
        "특정 산출물이나 눈에 보이는 장면 가운데 어느 것이든. 방향만 말하고 그런 표지가 없으면 false.\n"
        "incident: 리더의 답(지금까지 전체)에 시점·인물·리더가 한 구체 행동 중 하나라도 있으면 true. 하나도 없고 '없어요·글쎄요·특별히·그 정도·"
        "보통은·대체로' 류의 일반론·회피만이면 false.\n"
        "switched_case: 리더의 마지막 답이 지금 듣던 사례가 아니라 전혀 다른 사례로 넘어갔으면 true(같은 사례의 다른 장면은 false).\n"
        + (_same_block if _cc else "") + "\n"
        f"[직전 판정]\n{prev_lines}\n\n[대화]\n{_transcript_text(transcript)}\n\n"
        "JSON 으로만 답하세요: {\"slots\": {\"context\": {\"status\": \"filled|partial|empty\", \"quote\": \"\"}, ... 6개}, "
        "\"no_case\": false, \"switched_case\": false, \"incident\": true" + (", \"same_as\": \"\"" if _cc else "") + "}"
    )
    try:
        raw = await llm._generate_with_retry(
            prompt=prompt, max_tokens=700, json_mode=True, json_schema=slot_judge_schema(with_same=bool(_cc)),
            thinking_budget=0, call_type="slot_judge", temperature=0.0,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("슬롯 판정 호출 실패(직전 상태 유지): %s", e)
        return {"slots": {}, "no_case": False, "switched_case": False, "incident": None, "error": True}
    out = _parse(raw)
    slots = out.get("slots") if isinstance(out.get("slots"), dict) else {}
    _inc = out.get("incident")
    _sa = re.sub(r"[()\s]", "", str(out.get("same_as") or ""))
    return {"same_as": (_sa if (_cc and _sa in _cc) else None),
            "slots": {k: (slots.get(k) or {}) for k in SLOT_KEYS},
            "no_case": bool(out.get("no_case")), "switched_case": bool(out.get("switched_case")),
            "incident": (bool(_inc) if isinstance(_inc, bool) else None), "error": not bool(slots),
            "specific": (out.get("specific") if isinstance(out.get("specific"), bool) else None)}


MAP_STRONG_MIN_CONFIDENCE = 0.8


def quote_matches_loosely(quote: str | None, leader_text: str | None) -> bool:
    """매핑 인용 검증(느슨): 원문 그대로 들어 있거나, 인용의 어절(2자 이상) 중 70% 이상이 리더 원문에 있으면 참.
    슬롯 인용(merge_slots)은 엄격 검증을 유지하고, 매핑은 모델이 인용을 조금 줄여 쓰는 일이 잦아(E3 '표로 정리해서' 류) 느슨하게 본다."""
    from diag_project.services.bei_engine import quote_in_text
    if quote_in_text(quote, leader_text):
        return True
    import re as _re
    toks = [t for t in _re.split(r"[\s,.'\"“”‘’…·!?()]+", quote or "") if len(t) >= 2]
    if len(toks) < 2:
        return False
    body = (leader_text or "").replace(" ", "")
    hit = sum(1 for t in toks if t.replace(" ", "") in body)
    return hit / len(toks) >= 0.7   # (2026-11-05 3단계 전 1) strong = 인용 문장이 정의의 행동을 직접 보여주고 확신도 ≥ 0.8. 아니면 weak → SWEEP 대상


def _stub_labels(transcript: list[tuple[str, str]], opener_sub: str | None) -> list[dict]:
    first = next((t for r, t in transcript if r == "user"), "")
    return [{"sub": opener_sub, "strength": "strong", "quote": (first or "")[:40], "confidence": 1.0}] if opener_sub else []


async def map_episode(llm, *, transcript: list[tuple[str, str]], chapter_name: str,
                      sub_defs: list[dict], opener_sub: str | None) -> list[dict]:
    """sub_defs = [{"name", "description", "action_cue", "lv2_example"}]. 반환 [{sub, strength, quote, confidence}] — 인용은 호출자(bei_engine)가 원문 검증하지 않는다;
    여기서 리더 원문에 없는 인용은 quote 를 비운다(strength 는 유지)."""
    if _stub_on() or llm is None:
        return _stub_labels(transcript, opener_sub)
    from diag_project.llm_schemas import episode_map_schema
    defs = "\n".join(
        f"- {d['name']}: {d.get('description', '')}"
        + (f"\n    Lv.2 행동 예: {d['lv2_example']}" if d.get("lv2_example") else "")
        + (f"\n    행동 단서: {d['action_cue']}" if d.get("action_cue") else "")
        for d in sub_defs)
    prompt = (
        f"아래는 리더십 진단 '{chapter_name}' 영역에서 리더가 들려준 사례 하나입니다. 아래 하위역량 **각각**에 대해 이 사례가 근거가 되는지 "
        "판정하세요 — 목록의 하위역량마다 항목 하나씩, 빠뜨리지 말고(해당 없으면 strength 'none').\n"
        "[판정 규칙]\n"
        "- strength 'strong': quote 에 적은 리더의 문장이 그 하위역량 정의(또는 Lv.2 행동 예)에 적힌 행동을 **직접** 보여준다. "
        "사례의 전체 인상이 아니라 문장 하나로 확인되어야 한다. 그 행동이 다른 하위역량 정의에 더 잘 맞으면 그쪽만 strong.\n"
        "- strength 'weak': 태도·방침·생각으로만 스쳤거나, 행동이 있어도 그 정의와 간접적으로만 닿는다(예: 설득을 '숫자로' 했다는 것만으로 비전 공유가 되지 않는다. "
        "사용법을 가르쳤다는 것만으로 변화관리가 되지 않는다. 작게 먼저 해 보자는 제안만으로 혁신이 되지 않는다).\n"
        "- confidence(0~1): 그 라벨이 맞을 확신. 정의의 행동을 quote 문장에서 그대로 확인할 수 있을 때만 0.8 이상.\n"
        "- 한 사례에 strong 은 보통 1~2개(행동이 또렷하면 3개까지). 리더가 그 정의의 행동을 실제로 했는데 none 으로 두는 것도 오류다 — "
        "행동이 한 문장이라도 있으면 strong 후보로 보고 확신도로 가른다.\n"
        "- 'none': 그 하위역량과 닿는 말이 없다.\n"
        "- quote: 근거가 되는 리더의 말을 원문 그대로 40자 이내로. 코치의 말은 근거가 아닙니다.\n\n"
        f"[하위역량]\n{defs}\n\n[사례 대화]\n{_transcript_text(transcript)}\n\n"
        "JSON 으로만 답하세요: {\"labels\": [{\"sub\": \"하위역량 이름(목록 표기 그대로)\", \"strength\": \"strong|weak|none\", \"confidence\": 0.0, \"quote\": \"\"}]}"
    )
    try:
        raw = await llm._generate_with_retry(
            prompt=prompt, max_tokens=1600, json_mode=True, json_schema=episode_map_schema(),   # 하위역량 9개 × 4필드 — 600 이면 잘린다(2026-11-05 s3)
            thinking_budget=0, call_type="episode_map", temperature=0.0,
        )
    except Exception as e:  # noqa: BLE001
        logger.warning("사례 매핑 호출 실패(여는 하위역량 weak 로 기록): %s", e)
        return [{"sub": opener_sub, "strength": "weak", "quote": ""}] if opener_sub else []
    out = _parse(raw)
    labels = out.get("labels") if isinstance(out.get("labels"), list) else []
    if not labels:
        logger.warning("사례 매핑 응답에 라벨이 없음(잘림·파싱 실패 가능, %d자) — 여는 하위역량 weak 폴백: %s", len(raw or ""), (raw or "")[-120:])
    leader = _leader_text(transcript)
    names = {d["name"] for d in sub_defs}
    clean: list[dict] = []
    for lb in labels:
        if not isinstance(lb, dict) or str(lb.get("strength") or "").lower() == "none":
            continue
        sub = str(lb.get("sub") or "").strip()
        if sub not in names:
            sub = next((n for n in names if sub and (sub in n or n in sub)), "")
        if not sub:
            continue
        quote = str(lb.get("quote") or "").strip()
        quote_ok = quote_matches_loosely(quote, leader)
        try:
            conf = float(lb.get("confidence") if lb.get("confidence") is not None else 0.0)
        except (TypeError, ValueError):
            conf = 0.0
        # strong 은 (판정 strong) ∧ (확신도 ≥ 0.8) ∧ (인용이 리더 원문에 있음) — 하나라도 빠지면 weak(SWEEP 대상)
        strong = str(lb.get("strength") or "").lower() == "strong" and conf >= MAP_STRONG_MIN_CONFIDENCE and quote_ok
        clean.append({"sub": sub, "strength": "strong" if strong else "weak", "quote": quote if quote_ok else "", "confidence": round(conf, 2)})
    # 같은 하위역량이 여러 번 나오면 가장 강한 것 하나만(strong > weak, 확신도 높은 쪽)
    best: dict[str, dict] = {}
    for c in clean:
        k = c["sub"]
        if k not in best or (c["strength"], c["confidence"]) > (best[k]["strength"], best[k]["confidence"]):
            best[k] = c
    clean = list(best.values())
    if opener_sub and opener_sub in names and all(c["sub"] != opener_sub for c in clean):
        clean.append({"sub": opener_sub, "strength": "weak", "quote": ""})   # 여는 하위역량은 최소 weak
    return clean


def sub_defs_for(chapter: str) -> list[dict]:
    """매핑 프롬프트 재료: 챕터 하위역량 이름·정의(없으면 Lv.2 기술)·Lv.2 행동 예 첫 줄·must_ask 의 '행동:' 항목."""
    from diag_project.data.competencies import COMPETENCY_FRAMEWORK, SUBCOMPETENCY_MUST_ASK
    out = []
    for key, ind in (COMPETENCY_FRAMEWORK.get(chapter, {}).get("indicators") or {}).items():
        cues = [c.split(":", 1)[1].strip() for c in (SUBCOMPETENCY_MUST_ASK.get(key) or []) if c.startswith("행동")]
        ex2 = str((ind.get("examples") or {}).get(2) or "")
        lv2 = next((ln.strip().lstrip("・•·-").strip() for ln in ex2.split("\n") if ln.strip()), "")
        desc = (ind.get("description") or "").strip() or str((ind.get("levels") or {}).get(2) or "").strip()
        out.append({"key": key, "name": ind.get("name", ""), "description": desc[:120],
                    "action_cue": cues[0] if cues else "", "lv2_example": lv2[:80]})
    return out


def dump(d: dict) -> str:
    return json.dumps(d, ensure_ascii=False)
