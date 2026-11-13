"""(2026-11-11 P10-2) 페르소나 슬롯 문장 렌더 — 고정 문장 대신 그 사례의 구체 내용을 넣어 LLM 이 쓴다.

11/11 운영 Olivia 검토: "반대로 하셨다면 어떻게 됐을까요?" 같은 고정 슬롯 질문은 어느 사례에나 붙어 무엇을 묻는지 흐리다.
리더가 고른 선택과 버린 선택을 낱말로 넣어야 한다 — "시범 운영 없이 바로 전면 도입하셨다면 팀원들은 어떻게 움직였을까요?"
6명 전부 같은 원칙(Ella 는 슬롯 없음):
  criterion       Jessica  실제로 내린 결정을 짚고 기준을 묻는 질문
  reason          Lucas    고른 쪽·버린 쪽을 짚고 이유를 한 줄로 청하는 질문
  counterfactual  Olivia   버린 선택(또는 하지 않았을 경우)을 짚은 가정 질문
  other_side      Olivia   그 장면의 상대를 짚고 그 사람 자리에서 본 모습을 묻는 질문
  cheer           Michael  실제로 한 선택을 짚고 응원하는 평서문(질문은 LLM 본문이 잇는다)
  observation     Daniel   리더가 놓였던 자리를 짚고 선배로서 건네는 평서문
  will            Michael  응원 다음 턴 — 그 상황을 짚고 다시 온다면 무엇부터 할지 묻는 질문
집중 호출(Haiku) 1회 + 형식 불합격 시 1회 더. 그래도 불합격이면 None — 호출자는 슬롯을 넣지 않는다(고정 문장으로 메우지 않는다).
검사(slot_sentence_ok)는 순수 함수라 LLM 없이 테스트한다.
"""
from __future__ import annotations

import logging
import os
import re

from diag_project.services.output_guard import (
    _content_chunks, count_question_markers, find_praise, find_state_leak, is_question, key_noun_phrase, split_sentences,
)

logger = logging.getLogger(__name__)

QUESTION_KINDS = frozenset({"criterion", "reason", "counterfactual", "other_side", "will"})
STATEMENT_KINDS = frozenset({"cheer", "observation"})
SLOT_MAX_CHARS = 90
SLOT_STATEMENT_MAX_EOJEOL = 16     # (P12d-4) 12 → 16 — p12c: Michael 응원 문장이 두 영역 모두 탈락

# 종류별 지시(무엇을 쓰는가)와 결 예시. 예시는 진단과 무관한 분야(집·이사)로만 쓴다 — 가이드 예시는 금지 예까지 그대로 베낀다(CLAUDE.md).
_SPEC: dict[str, tuple[str, str]] = {
    "criterion": ("리더가 실제로 내린 결정을 리더의 낱말로 짚고, 그렇게 정할 때 무엇을 기준으로 삼았는지 묻는 질문 한 문장.",
                  "전세 대신 월세로 정하실 때 무엇을 기준으로 삼으셨습니까?"),
    "reason": ("리더가 고른 쪽과 버린 쪽을 리더의 낱말로 짚고, 그쪽을 고른 이유를 한 줄로 청하는 짧은 질문 한 문장.",
               "전세 말고 월세를 고른 이유, 한 줄로 하면 무엇입니까?"),
    "counterfactual": ("리더가 실제로 고른 쪽 대신 '고르지 않은 쪽'을 했다고 가정하고, 그랬다면 그 자리의 사람들이 어떻게 움직였을지 묻는 질문 한 문장. "
                       "꼴: '[고른 쪽] 대신(없이) [고르지 않은 쪽]을 하셨다면, [사람]은 어떻게 …했을까요?' — 가정하는 것은 반드시 '고르지 않은 쪽'이다.",
                       "월세 대신 전세로 무리해서 들어가셨다면 식구들은 어떻게 움직였을까요?"),
    "other_side": ("리더가 말한 그 장면의 상대(사람)를 리더의 낱말로 짚고, 그 사람 자리에서는 그 장면이 어떻게 보였을지 묻는 질문 한 문장.",
                   "이사 날짜를 갑자기 들은 집주인 자리에서는 그 전화가 어떤 장면이었을까요?"),
    "cheer": ("리더가 실제로 한 선택 하나를 리더의 낱말 한두 개로 짧게 짚고(열여섯 어절 안쪽 — 답을 다시 읊지 않는다), 그 선택을 응원한다고 말하는 평서문 한 문장. 질문이 아니다. "
              "'좋다·훌륭하다·대단하다·잘하셨다' 같은 평가어 없이 '응원'이라는 말로만.",
              "돌아가는 길인 줄 알면서 월세로 정하신 그 선택, 응원해요."),
    # (2026-11-12 P11d-3) 'A와 B 사이에서 … 혼자 …셨겠습니다' 틀의 출처를 지웠다 — 지시문의 '누구 사이에서'·'감당했을 것', 예시 5종의 '사이에서'·'혼자'·
    #   '~셨겠습니다', 그리고 그 낱말이 있어야 통과시키던 꼴 검사. 예시는 주지 않는다.
    #   (P11e-6) '떠안았던 것' 이라는 지시문 낱말이 출력('…직접 떠안으셨습니다')에 나와 바꿨다.
    "observation": ("리더가 그 일에서 스스로 정하고 책임진 것(리더가 말한 것만) 하나를 리더의 낱말 한두 개로 짧게(열여섯 어절 안쪽) 짚어 말하는 평서문 한 문장. "
                    "질문·조언·평가가 아니다. 문장의 주어는 리더다. 문장의 뼈대와 끝맺음은 사례마다 다르게 쓴다.",
                    ""),
    "will": ("리더가 겪은 그 상황을 리더의 낱말로 짚고, 같은 상황이 다시 오면 무엇부터 할지 묻는 질문 한 문장.",
             "다음에 또 이사 날짜가 겹치면 무엇부터 정하시겠어요?"),
}
# 예시(다른 분야)의 낱말이 출력에 들어오면 베낀 것 — 불합격
_EXAMPLE_WORDS = ("전세", "월세", "이사", "집주인", "식구")
# 리더의 1인칭을 코치 문장에 옮긴 꼴("…제가 먼저 따로 이야기를 꺼내야 했던 자리") — 수선하지 않고 그 슬롯 문장을 버린다
_FIRST_PERSON_RE = re.compile(r"(^|[\s'‘“\"(,])(제가|제|저는|저도|저의|저를|저에게|저한테|저\s*혼자|저희[가-힣]*|내가|나는|우리\s*팀)(?=[\s,.]|$)")


def has_leader_first_person(text: str | None) -> bool:
    return bool(_FIRST_PERSON_RE.search(text or ""))


def _ending_key(text: str | None) -> str:
    """끝맺음 = 마지막 어절(문장부호 제외). '가볍지 않으셨겠습니다' 는 뒤 두 어절을 한 덩어리로 본다."""
    toks = re.sub(r"[.?!…~\"'”’]+$", "", (text or "").strip()).split()
    if not toks:
        return ""
    return "".join(toks[-2:]) if (len(toks) >= 2 and toks[-2] in ("않", "않으셨", "못") or (len(toks) >= 2 and toks[-2].endswith("지"))) else toks[-1]


def _shape_key(text: str | None) -> str:
    """문형 = 쉼표 앞 마지막 낱말(명사로 끊고 서술을 붙이는 꼴 '…했던 자리, …')."""
    m = re.search(r"([가-힣]{1,6})[,，]\s*[^,，]{2,30}$", (text or "").strip())
    return m.group(1) if m else ""


def repeats_used_shape(text: str | None, used: list[str] | None) -> str | None:
    """이번 세션에서 이미 쓴 슬롯 문장과 끝맺음이 같거나('…가볍지 않으셨겠습니다'), 같은 문형('…자리, …')이면 그 사유."""
    # (2026-11-13 P12b-1) 끝맺음 반복 검사는 뺐다 — Michael 응원 문장은 늘 '…응원해요'로 끝나, 둘째 영역부터 매 턴 불합격하며 다시 쓰기를 썼다(p12 6턴)
    sk = _shape_key(text)
    for u in used or []:
        if sk and sk == _shape_key(u):
            return "same_shape"
    return None
_KIND_SHAPE: dict[str, re.Pattern] = {
    "criterion": re.compile(r"(기준|근거|무엇을 보고|뭘 보고|어디에 두)"),
    "reason": re.compile(r"(이유|왜|까닭)"),
    "counterfactual": re.compile(r"(다면|더라면|았으면|었으면|없이|대신|않고|말고)[^?]*\?"),
    "other_side": re.compile(r"(입장|자리에서|쪽에서|눈에는|보기에는|편에서)"),
    "cheer": re.compile(r"응원"),
    "will": re.compile(r"(다시|다음에|또)[^?]*\?"),
}
_ADVICE_RE = re.compile(r"(하시면 좋|해 보시|하셔야|하는 게 좋|권합니다|추천)")
_SPEC_ECHO_RE = re.compile(r"(알아주(셨|시|었|십|는)|알아\s*드|한마디로|선배로서|짚어\s*드)")
# (p10b) "2명 먼저 쓰자고 버리셨다면" — 지시문의 '버린 선택'이 문장에 들어와 고른 쪽과 버린 쪽이 뒤섞였다. 선택을 '버렸다'고 가정하는 꼴은 불합격.
_GARBLED_CF_RE = re.compile(r"(버리셨다면|버렸다면|버리셨더라면|버렸더라면|고 버리|를 버리셨|을 버리셨)")
_CHOICE_KINDS = frozenset({"counterfactual", "reason", "criterion"})


# (2026-11-12 P11b-4) 같은 턴 안에서 같은 낱말 반복 금지 — 슬롯 문장이 그 턴의 질문에 쓰인 코치의 낱말('쉽지 않은')을 되풀이하면 불합격.
#   리더가 쓴 낱말(사람·일의 이름)은 두 문장에 다 나와도 된다.
_REPEAT_IGNORE = ("리더님", "리더", "말씀", "그때", "있었", "하셨", "무엇", "어떻게", "어떤", "주시", "들려")


def repeated_turn_words(slot_text: str | None, other_text: str | None, leader_texts: list[str] | None) -> list[str]:
    theirs = {c for x in (leader_texts or []) for c in _content_chunks(x or "") if len(c) >= 2}

    def _own(t: str | None) -> set[str]:
        return {c for c in _content_chunks(t or "") if len(c) >= 2 and not c.startswith(_REPEAT_IGNORE)
                and not any(c == o or c.startswith(o) or o.startswith(c) for o in theirs)}
    a, b = _own(slot_text), _own(other_text)
    return sorted(c for c in a if any(c == o or c[:2] == o[:2] for o in b))


def slot_sentence_ok(kind: str, text: str | None, leader_texts: list[str] | None, *, persona_name: str | None = None,
                     used: list[str] | None = None, avoid_text: str | None = None) -> tuple[bool, str]:
    """슬롯 문장 형식 검사 — (통과, 사유). 한 문장 · 종류에 맞는 꼴 · 리더가 쓴 낱말 2개 이상 · 예시 베낌 없음 · 평가·조언 없음 · 코치 어미."""
    from diag_project.services.persona_register import register_violations
    t = re.sub(r"\s+", " ", (text or "").strip())
    sents = [x.strip() for x in split_sentences(t) if x.strip()]
    if len(sents) != 1:
        return False, f"sentences={len(sents)}"
    if not (12 <= len(t) <= SLOT_MAX_CHARS):
        return False, "length"
    if kind in STATEMENT_KINDS and len(t.split()) > SLOT_STATEMENT_MAX_EOJEOL:
        return False, "length"          # (2026-11-14 P12c-3 → P12d-4) 응원·관찰 문장은 16어절 이하 — p12b: 답을 통째로 되풀이한 26어절 응원 문장. 넘으면 그 문장 없이 나간다
    if kind in QUESTION_KINDS:
        if not (is_question(t) and t.endswith("?")) or count_question_markers(t) != 1:
            return False, "not_one_question"
    elif is_question(t) or "?" in t:
        return False, "question_in_statement"
    shape = _KIND_SHAPE.get(kind)
    if shape is not None and not shape.search(t):
        return False, "shape"
    if any(w in t for w in _EXAMPLE_WORDS):
        return False, "example_copied"
    mine = {c for c in _content_chunks(t) if len(c) >= 2}
    theirs = {c for x in (leader_texts or []) for c in _content_chunks(x or "") if len(c) >= 2}
    shared = {c for c in mine if c in theirs or any(len(o) >= 2 and (c.startswith(o) or o.startswith(c)) for o in theirs)}
    if len(shared) < 2:
        return False, "no_case_words"            # 리더가 쓴 낱말이 2개는 들어가야 '그 사례의 문장'이다
    if find_praise(t) or find_state_leak(t) or _ADVICE_RE.search(t):
        return False, "praise_or_advice"
    if kind == "counterfactual" and _GARBLED_CF_RE.search(t):
        return False, "garbled_choice"
    if register_violations(persona_name, t, scope="strict"):
        return False, "register"
    norm = re.sub(r"\s+", "", t)
    if any(norm == re.sub(r"\s+", "", u or "") for u in (used or [])):
        return False, "repeated"
    # (2026-11-12 P11-B) 리더의 1인칭('제가'·'저희')을 코치 문장에 그대로 옮기지 않는다 · 이번 세션에서 쓴 슬롯 문장과 같은 끝맺음·같은 문형을 다시 쓰지 않는다(6명 공통)
    if has_leader_first_person(t):
        return False, "first_person"
    _rs = repeats_used_shape(t, used)
    if _rs:
        return False, _rs
    if avoid_text and repeated_turn_words(t, avoid_text, leader_texts):
        return False, "repeat_word"
    if _SPEC_ECHO_RE.search(t):
        return False, "instruction_echo"         # (시뮬 p11b) '…그 무게를 알아주셨습니다' — [쓸 문장]의 말('알아주는')을 문장에 옮겼다
    return True, ""


def _stub_sentence(kind: str, leader_texts: list[str], persona_name: str | None) -> str | None:
    """FM_LLM_STUB(스모크·pytest) 전용 — LLM 없이 리더 답의 명사구로 만든 표식 문장. 운영에서는 쓰지 않는다."""
    np_ = key_noun_phrase(" ".join(leader_texts[-2:])) or key_noun_phrase(" ".join(leader_texts))
    if not np_:
        return None
    return f"'{np_}' 이야기에 붙는 {kind} 자리입니다." if kind in STATEMENT_KINDS else f"'{np_}' 이야기에 붙는 {kind} 질문입니까?"


def _pick_sentence(raw: str | None) -> str:
    """LLM 출력에서 슬롯 문장만 꺼낸다 — '문장:' 줄이 있으면 그 줄, 없으면 마지막 줄(앞의 '고른 쪽/고르지 않은 쪽' 줄은 버린다)."""
    lines = [ln.strip().strip('"“”') for ln in (raw or "").strip().split("\n") if ln.strip()]
    if not lines:
        return ""
    for ln in lines:
        m = re.match(r"^문장\s*[:：]\s*(.+)$", ln)
        if m:
            return m.group(1).strip().strip('"“”')
    body = [ln for ln in lines if not re.match(r"^(고른 쪽|고르지 않은 쪽)\s*[:：]", ln)]
    return (body[-1] if body else "").strip()


async def render_slot(llm, *, kind: str, persona_name: str | None, transcript: list[tuple[str, str]], used: list[str] | None = None,
                      rounds: int = 2, avoid_text: str | None = None) -> tuple[str | None, str]:
    """(슬롯 문장 | None, 모드). 모드 'llm' | 'llm_regen' | 'stub' | 'miss:<사유>'."""
    from diag_project.services.persona_register import apply_register, register_hint
    leader = [t for r, t in (transcript or []) if r == "user" and (t or "").strip()]
    if kind not in _SPEC or not leader:
        return None, "miss:no_material"
    if os.getenv("FM_LLM_STUB"):
        s = _stub_sentence(kind, leader, persona_name)
        return (s, "stub") if s else (None, "miss:stub")
    if llm is None:
        return None, "miss:no_llm"
    spec, example = _SPEC[kind]
    example = apply_register(persona_name, example, scope="strict")[0] if example else ""
    used_block = ""
    if used:
        used_block = ("[이번 세션에서 이미 쓴 문장 — 같은 끝맺음·같은 문형을 다시 쓰지 않는다]\n"
                      + "\n".join(f"- {re.sub(r'\\s+', ' ', (u or '').strip())[:90]}" for u in used[-5:]) + "\n\n")
    said = "\n".join(f"- {re.sub(r'\\s+', ' ', t.strip())[-400:]}" for t in leader[-5:])
    base = (
        f"당신은 리더십 BEI 코치 {persona_name or 'Ella'}입니다. 지금 듣고 있는 사례에 대해 아래 [쓸 문장] 하나만 씁니다.\n\n"
        f"[이 사례에서 리더가 한 말 — 그대로]\n{said}\n\n"
        f"[쓸 문장] {spec}\n\n"
        "[규칙]\n- 정확히 한 문장, 70자 안쪽.\n- 리더가 위에서 실제로 쓴 낱말을 두 개 이상 넣는다(무엇을 고르고 무엇을 버렸는지, 누구와의 일인지가 문장에 보여야 한다).\n"
        "- 리더가 하지 않은 말·없는 사실을 만들지 않는다. 누가 한 일인지를 바꾸지 않는다. 가리키기만 하는 말로 때우지 않는다.\n"
        "- 역량·항목 이름, 평가·칭찬·조언은 쓰지 않는다.\n"
        "- 리더가 자기를 가리킨 말('제가', '저희')은 옮기지 않는다 — 코치의 자리에서 '리더님'으로 쓰거나 주어를 뺀다.\n"
        f"- 말투: {register_hint(persona_name)}\n\n"
        + used_block
        + (f"[이 문장 바로 뒤에 붙을 질문 — 이 질문에 쓰인 꾸밈말·서술어를 되풀이하지 않는다]\n- {re.sub(r'\\s+', ' ', avoid_text.strip())[:160]}\n\n" if avoid_text else "")
        + (f"[결 참고 — 다른 분야의 예. 낱말을 가져오지 말 것] {example}\n\n" if example else "")
        + ("출력은 세 줄입니다(앞 두 줄은 리더의 낱말로 짧게).\n고른 쪽: …\n고르지 않은 쪽: …\n문장: …" if kind in _CHOICE_KINDS
           else "출력: 문장만. 따옴표·설명 없이.")
    )
    prompt, mode, why = base, "llm", ""
    for attempt in range(max(1, rounds)):
        try:
            out = await llm._generate_with_retry(prompt=prompt, max_tokens=220, thinking_budget=0, call_type="slot_render", temperature=0.5)
        except Exception as e:  # noqa: BLE001
            logger.warning("슬롯 문장 렌더링 실패: %s", e)
            return None, "miss:error"
        cand = _pick_sentence(out)
        cand = apply_register(persona_name, cand, scope="strict")[0]
        ok, why = slot_sentence_ok(kind, cand, leader, persona_name=persona_name, used=used, avoid_text=avoid_text)
        if ok:
            return cand, mode
        if why == "length" and kind == "observation":
            # (2026-11-12 P11d-2) 관찰 문장이 길면 다시 쓰지 않는다 — 이번 턴은 관찰 없이
            logger.info("관찰 문장 길이 초과 → 넣지 않음: %r", cand[:90])
            return None, "miss:length"
        if why == "first_person":
            # (P11-B) 리더의 1인칭을 옮긴 문장은 고쳐 쓰지 않는다 — 이번 턴은 슬롯을 넣지 않는다
            logger.info("슬롯 문장에 리더의 1인칭(%s) → 넣지 않음: %r", kind, cand[:90])
            return None, "miss:first_person"
        logger.info("슬롯 문장 형식 불합격(%s, %s) → %s: %r", kind, why, "다시 쓰기" if attempt == 0 else "넣지 않음", cand[:90])
        mode = "llm_regen"
        prompt = base + (f"\n\n🚨 방금 출력은 조건에 맞지 않았습니다({why}). [쓸 문장]의 꼴로, 리더가 쓴 낱말 두 개 이상을 넣어 한 문장만 다시 쓰세요.")
    return None, f"miss:{why}"
