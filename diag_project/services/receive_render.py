"""(2026-11-16 P14-1·3) 받는 말 전용 호출 — 리더가 방금 한 말을 한 문장으로 받는다.

11/16 운영 Lucas(조직관리·성과관리): 받는 말이 없는 턴이 절반이었다. 본 호출이 받는 말과 질문을 함께 쓰고 허용 목록이 받는 말을 지웠기 때문이다
(p13g: 탈락 9~11건). P13f 는 사례를 닫는 턴에만 전용 호출을 썼다 — P14 는 본론의 모든 턴(탐침·첫 꼬리·훑는 질문)과 라포·영역 정의 턴으로 넓힌다.
받는 말은 리더의 직전 답만 있으면 쓸 수 있어 슬롯 판정 호출과 동시에 돈다. 본 호출과 첫 꼬리 전용 호출은 질문만 쓴다.

  kind      쓰는 것                                                확인
  probe     답에서 가장 구체적인 대목 하나를 집어 다시 말하는 한 문장      허용 끝맺음 · 12어절 이하 · 리더 답과 겹치는 내용 낱말 2개 이상 · 금지 꼴 아님
  align     리더의 정의에서 구절 하나를 그대로 집어 다시 말하는 한 문장    허용 끝맺음 · 16어절 이하 · 겹치는 내용 낱말 3개 이상
  smalltalk 짧은 답의 낱말 하나를 받아 한 문장                       내용 낱말이 모두 리더 답에 있는 낱말일 것
  role      낱말 나열 답의 낱말을 그대로 넣어 다시 말하는 한 문장          내용 낱말이 모두 리더 답에 있는 낱말일 것

확인에서 떨어지면 사유를 한 줄로 넘겨 한 번 더 쓴다. 그래도 떨어지면 None — 호출자는 받는 말 없이(라포·영역 정의·사례를 닫는 전환 턴은 고정 받기로) 내보낸다.
(2026-11-18 P14f) 제3자 높임 확인은 없앴다 — p14e 탈락 23건 가운데 13건이 오탐이었고(높임이 리더 행동에 붙은 문장), 팀원·강사를 높여 말하는 것 자체는 틀린 말이 아니다.
받을 내용이 없는 답('네', '없어요', 떠오르지 않는다는 답)에는 부르지 않는다.
(2026-11-18 P15) 본론에서는 사례를 닫는 전환 턴에만 부른다(영역당 두 번까지, 직전 답이 리더 본인의 행동·배운 점일 때) — 사례 안 꼬리 질문 턴에는 부르지 않는다.
  11/18 운영 Lucas: 본론 21턴 중 12턴이 되짚는 문장으로 시작했다. 슬롯 판정과 함께 돌리던 호출(render_receive_gated)과 미룬 다시 쓰기는 지웠다.
"""
from __future__ import annotations

import logging
import os
import re

from diag_project.services.output_guard import _content_chunks, is_question, split_sentences

logger = logging.getLogger(__name__)

ANSWER_TAIL_CHARS = 700
ALIGN_MAX_EOJEOL = 16
PROBE_PROMPT_EOJEOL = 9            # (P14b-2) 본론 받는 말은 9어절 이내로 쓰게 한다(확인의 상한은 종전대로 12어절)
QUOTE_SHARE_MAX = 1 / 3            # (P14b-2) '…다는 말씀이네요/이군요' 꼴은 세션 받는 말의 1/3 이하
_LEAD_ADDRESS_RE = re.compile(r"^리더님(께서는|께서|이|은|,)?\s*")
_META_RE = re.compile(r"—|(?<![A-Za-z])no,|규칙|혹은\s*더\s*정확히|다시\s*말하면|낱말은|must\s|ending")
PROBE_CHECK_EOJEOL = 12            # (P14c-6 → P14d-3) 10어절로 낮췄다가 12어절로 되돌렸다(p14c: 길이 탈락 25건). 지시문은 9어절 이내 그대로
# (P14d-1) 받는 말 안의 평가·칭찬 낱말 — 리더가 쓴 낱말이면 그대로 옮긴 것이라 보지 않는다(p14c Daniel: '…제안이 핵심이라고 짚으셨습니다')
_EVAL_WORD_RE = re.compile(r"핵심|인상|훌륭|대단|좋은|멋진|탁월|뛰어난|의미\s*있|돋보")
ALIGN_MIN_SHARED = 3
SMALL_MAX_EOJEOL = 12
_KIND_WHAT: dict[str, str] = {
    # (2026-11-16 P14b-2) 대목 하나 → 낱말 하나. p14: 답 전체를 옮겨 12어절을 넘긴 탈락이 10건 중 9건, 받는 말과 질문 앞 절이 같은 내용을 되풀이했다.
    # (2026-11-18 P14e-1) '가장 구체적인 낱말 하나만 집어'를 글자 그대로 따라 '가장 구체적인 낱말은 …입니다'를 썼다(p14d) — 하나만 골라 짧게로 바꿨다
    # (2026-11-18 P14f-3) 길이 탈락(p14e 24건)은 답을 통째로 옮기거나 두 절을 쉼표로 이은 문장이었다
    "probe": ("리더가 방금 말한 것 가운데 하나만 골라 짧은 한 문장으로 다시 말한다. 답 전체를 옮기지 않는다. 쉼표로 두 절을 잇지 않는다.",),
    "align": ("리더가 방금 말한 뜻풀이에서 구절 하나를 그대로 집어 한 문장으로 다시 말한다. 뜻풀이 전체를 줄여 옮기지 않는다.",),
    "smalltalk": ("리더의 짧은 답에서 낱말 하나를 그대로 받아 한 문장으로 다시 말한다. 리더가 쓰지 않은 낱말을 보태지 않는다.",),
    "role": ("리더가 늘어놓은 낱말을 그대로 넣어 한 문장으로 다시 말한다. 숫자와 직함은 리더가 쓴 그대로 쓰고 다른 뜻으로 풀지 않는다.",),
}
RETRY_NOTES: dict[str, str] = {
    "ending": "끝맺음이 리더의 말을 다시 말하는 꼴이 아니었다",
    "long": "문장이 너무 길었다 — 앞 문장의 절 하나만 남겨 {limit}어절 이내로 쓴다",
    "overlap": "리더가 쓴 낱말이 모자랐다",
    "ban": "평가·짐작·감상이 섞였다",
    "question": "묻는 문장이었다",
    "words": "리더가 쓰지 않은 낱말이 들어갔다",
    "same_ending": "이번에 쓰지 않기로 한 끝맺음을 썼다",
    "praise": "평가하거나 칭찬하는 낱말이 들어갔다",
    "meta": "설명이나 고쳐 쓰기가 섞였다",
    "dup": "'말씀'을 두 번 썼다",
    "quote_cap": "'-다는 말씀이네요' 꼴을 너무 자주 썼다",
    "empty": "문장이 없었다",
}


def _limit(kind: str) -> int:
    return ALIGN_MAX_EOJEOL if kind == "align" else (PROBE_PROMPT_EOJEOL if kind == "probe" else SMALL_MAX_EOJEOL)


def retry_note(why: str | None, kind: str = "probe") -> str:
    """다시 쓸 때 넘기는 한 줄 사유."""
    return RETRY_NOTES.get(str(why or ""), "쓸 수 없는 문장이었다").format(limit=_limit(kind))


def receivable(answer: str | None, prev_answer: str | None = None) -> bool:
    """받을 내용이 있는 답인가 — 내용 낱말이 둘 미만이거나, 떠오르지 않는다는 답이거나, 바로 앞 답과 같으면 부르지 않는다."""
    from diag_project.services.bei_engine import is_no_recall_text
    a = re.sub(r"\s+", " ", (answer or "").strip())
    if len([c for c in _content_chunks(a) if len(c) >= 2]) < 2:
        return False
    if is_no_recall_text(a):
        # (P14b-2 → P14e-4) 답 전체가 모른다·없다일 때만 부르지 않는다 — '기억나는 게 없습니다. 다만 …했습니다'처럼 섞인 답은 부른다
        rest = " ".join(x for x in split_sentences(a) if x.strip() and not is_no_recall_text(x))
        if len([c for c in _content_chunks(rest) if len(c) >= 2]) < 2:
            return False
    return not (prev_answer and re.sub(r"\s+", "", prev_answer) == re.sub(r"\s+", "", a))


def build_receive_prompt(*, leader_answer: str, persona_name: str | None, kind: str = "probe", avoid_endings: list[str] | None = None,
                         retry_note: str | None = None, no_quote: bool = False, retry_prev: str | None = None) -> str:
    from diag_project.services.persona_register import register_hint
    from diag_project.services.turn_checks import RECEIVE_ENDING_HINT
    ans = re.sub(r"\s+", " ", (leader_answer or "").strip())[-ANSWER_TAIL_CHARS:]
    from diag_project.services.turn_checks import RECEIVE_KEY_HINT
    avoid = [RECEIVE_KEY_HINT.get(x, x) for x in (avoid_endings or []) if x][:2]
    from diag_project.services.persona_register import register_of as _rof_p
    formal = _rof_p(persona_name) == "formal"
    limit = _limit(kind)
    return (
        "당신은 리더십 코치입니다. 리더가 방금 한 말을 한 문장으로 받습니다.\n\n"
        f"[리더가 방금 한 말]\n{ans}\n\n"
        f"[규칙]\n- {_KIND_WHAT.get(kind, _KIND_WHAT['probe'])[0]}\n"
        "- 평서문 한 문장만 쓴다. 물음과 앞으로 무엇을 할지 알리는 말은 쓰지 않는다.\n"
        "- 리더가 쓴 낱말로만 쓴다. 평가·짐작·감상·칭찬을 보태지 않는다. 리더가 말하지 않은 사실은 넣지 않는다.\n"
        f"- {limit}어절을 넘기지 않는다.\n"
        + (f"- 끝은 코치의 평소 말투와 무관하게 -군요, -네요, -지요 꼴로 맺는다 — {RECEIVE_ENDING_HINT} 가운데 하나.\n" if kind in ("probe", "align") else "")
        + ("- 평소 말투가 합쇼체여도 이 문장만은 예외로 위의 꼴로 맺는다.\n" if formal and kind in ("probe", "align") else "")
        + "- 지난 일은 지난 일로 쓴다 — 지금 하고 있는 일처럼 옮기지 않는다.\n"
        + ("- 이번에는 끝을 " + ", ".join(avoid) + " 꼴로 맺지 않는다 — 다른 꼴로 맺는다.\n" if avoid and kind in ("probe", "align") else "")
        + ("- 이번에는 '-다는 말씀이네요', '-다는 말씀이군요' 꼴을 쓰지 않는다.\n" if no_quote and kind == "probe" else "")
        + "- 팀원·강사·교육생처럼 리더가 아닌 사람이 한 말·걱정·반응을 다시 말할 때는 그 사람을 주어로 밝혀 쓴다. "
        "주어를 빼서 리더가 한 일처럼 읽히게 쓰지 않는다.\n"
        "- 문장을 '리더님'으로 시작하지 않는다. '말씀'이라는 낱말은 한 번만 쓴다.\n"
        "- 리더를 부를 때는 '리더님'이라고만 한다.\n"
        + (f"- 말투: {register_hint(persona_name)}\n" if kind in ("smalltalk", "role") else "- 존댓말로 쓴다.\n")
        + (f"- 앞서 쓴 문장: {retry_prev}\n" if retry_note and retry_prev else "")      # (P14f-3) 길이로 떨어졌을 때만 앞 문장을 보여 준다 — 절 하나만 남기게
        + (f"- 앞서 쓴 문장은 쓸 수 없었다 — {retry_note}. 그 점을 고쳐 새로 쓴다.\n" if retry_note else "")
        + "\n출력: 다시 말하는 한 문장만. 설명, 고쳐 쓰기, 따옴표 풀이를 덧붙이지 않는다."
    )


# 문장을 맺는 데 쓰는 가벼운 서술어 — 리더 답에 없어도 된다(뜻을 보태지 않는다)
_LIGHT_PREDICATES = frozenset(("맡고", "맡으", "맡아", "계시", "계신", "하시", "하고", "하는", "이시", "있으", "있는", "지내", "보내", "일하", "함께", "그렇", "말씀", "이네", "이군"))


_KOR_COUNT_RE = re.compile(r"(한|두|세|네|다섯|여섯|일곱|여덟|아홉|열)\s*(분|명|사람|개|곳|팀)(?![가-힣]*[가-힣]{3})")


def words_from_answer(sentence: str | None, answer: str | None) -> bool:
    """받는 말의 내용 낱말이 모두 리더 답에 있는 낱말인가(앞 두 글자 기준, 숫자 포함). 호칭 '리더님'은 뺀다."""
    ans = re.sub(r"\s+", "", answer or "")
    src = {c[:2] for c in _content_chunks(answer or "") if len(c) >= 2}
    for c in _content_chunks(re.sub(r"리더님(께서|이|은|도)?", " ", sentence or "")):
        if len(c) < 2:
            continue
        if c[:2] in src or c[:2] in ans or c[:2] in _LIGHT_PREDICATES:
            continue
        return False
    if not all(d in ans for d in re.findall(r"\d+", sentence or "")):
        return False
    # 수를 우리말로 바꿔 쓴 꼴('네 분', '두 명')은 리더 답에 그대로 있을 때만 — 전례: '4명 팀원'을 '팀장 네 분'으로 풀었다(11/13 운영)
    return all(re.sub(r"\s+", "", m.group(0)) in ans for m in _KOR_COUNT_RE.finditer(sentence or ""))


# (2026-11-18 P14f-2) 모른다는 답을 되받은 받는 말 — p14e Jessica 전환 턴: '설문 항목을 어떻게 구성했는지는 기억이 안 난다고 하셨군요.'
_NO_RECALL_ECHO_RE = re.compile(r"기억(이|은|도)?\s*(잘\s*)?(안\s*[나난날납]|나지\s*않|에\s*없)|떠오르지\s*않|안\s*떠오|모르겠|모른다고|생각(이|은)?\s*(잘\s*)?(안\s*[나난날납]|나지\s*않)")


def echoes_no_recall(sentence: str | None) -> bool:
    """받는 말이 '기억이 안 난다·모르겠다'는 리더의 말을 되받았는가 — 전환 턴에서는 이 받는 말 대신 고정 받기를 쓴다."""
    from diag_project.services.bei_engine import is_no_recall_text
    return bool(is_no_recall_text(sentence) or _NO_RECALL_ECHO_RE.search(sentence or ""))


def strip_lead_address(sentence: str | None) -> str:
    """(P14b-2 → P14c-3) 받는 말 문장 머리의 '리더님,/리더님은/리더님이/리더님께서'를 뗀다(모든 끝맺음) — 받는 말은 주어 없이 쓴다."""
    return _LEAD_ADDRESS_RE.sub("", (sentence or "").strip(), count=1)


def check_receive(sentence: str | None, answer: str | None, *, kind: str = "probe", formal: bool = False, avoid_endings: list[str] | None = None,
                  no_quote: bool = False) -> tuple[bool, str]:
    """(통과 여부, 사유: ok | empty | meta | question | ending | long | overlap | ban | praise | words | dup)"""
    from diag_project.services.turn_checks import is_self_talk, receive_allowed, receive_ban_reason, receive_shared_words
    s = (sentence or "").strip()
    if not s:
        return False, "empty"
    if _META_RE.search(s) or is_self_talk(s):
        # (P14e-1) 설명·고쳐 쓰기가 섞인 문장('… — no, must avoid …', '혹은 더 정확히는', '낱말은 …입니다')
        # (P14f-5) 공통 혼잣말 표지('…꼴로 맺어 한 문장으로 말합니다') · 60자를 넘으면서 쉼표 3개 이상
        return False, "meta"
    if is_question(s):
        return False, "question"
    if kind in ("smalltalk", "role"):
        if len(s.split()) > SMALL_MAX_EOJEOL:
            return False, "long"
        if receive_ban_reason(s):
            return False, "ban"
        return (True, "ok") if words_from_answer(s, answer) else (False, "words")
    ok, why = receive_allowed(s, answer, formal=formal, max_eojeol=(ALIGN_MAX_EOJEOL if kind == "align" else PROBE_CHECK_EOJEOL))
    if not ok:
        return False, why
    if kind == "align" and len(receive_shared_words(s, answer)) < ALIGN_MIN_SHARED:
        return False, "overlap"
    if receive_ban_reason(s):
        return False, "ban"
    from diag_project.services.output_guard import find_praise
    ans_ns = re.sub(r"\s+", "", answer or "")
    if find_praise(s) or any(re.sub(r"\s+", "", m.group(0)) not in ans_ns for m in _EVAL_WORD_RE.finditer(s)):
        return False, "praise"
    if s.count("말씀") >= 2:
        return False, "dup"
    # (P14c-1 → P14e-3) '가장 많이 쓴 꼴은 쓰지 않는다'·'인용꼴 1/3 이하'는 지시문에만 둔다 — 어겨도 탈락시키지 않는다(p14d: 멀쩡한 문장 8건 탈락).
    #   쏠림은 회귀 점검의 끝맺음 분포로만 본다.
    return True, "ok"


async def _one(llm, prompt: str) -> str | None:
    out = await llm._generate_with_retry(prompt=prompt, max_tokens=120, thinking_budget=0, call_type="receive_render", temperature=0.4)
    text = re.sub(r"\s*\n+\s*", " ", (out or "").strip().strip('"“”'))
    ss = [x.strip() for x in split_sentences(text) if x.strip()]
    if not ss:
        return None
    return ss[0] if ss[0][-1] in ".!?…" else ss[0] + "."      # (P14c-5) 끝 부호가 없으면 마침표 — 질문과 붙을 때 문장이 이어 붙지 않게


def _pre(leader_answer: str | None, prev_answer: str | None, kind: str, llm) -> str | None:
    """부르기 전 판정 — 부르지 않을 까닭(모드 문자열)이 있으면 돌려준다."""
    if kind == "probe" and not receivable(leader_answer, prev_answer):
        return "skip:empty"
    if not (leader_answer or "").strip():
        return "skip:empty"
    if os.getenv("FM_LLM_STUB"):
        return "stub"
    if llm is None:
        return "miss:no_llm"
    return None


async def _attempt(llm, *, leader_answer: str, persona_name: str | None, kind: str, avoid_endings: list[str] | None, no_quote: bool,
                   note: str | None, trace: list | None, prev: str | None = None) -> tuple[str | None, str, str | None]:
    """한 번 쓰고 확인한다. (통과한 문장 | None, 사유: ok | error | <확인 탈락 사유>, 떨어진 문장 | None)"""
    from diag_project.services.persona_register import register_of
    from diag_project.services.turn_checks import fix_leader_address
    try:
        s = await _one(llm, build_receive_prompt(leader_answer=leader_answer, persona_name=persona_name, kind=kind, avoid_endings=avoid_endings,
                                                 retry_note=note, no_quote=no_quote, retry_prev=prev))
    except Exception as e:  # noqa: BLE001
        logger.warning("receive render failed: %s", e)
        return None, "error", None
    s = strip_lead_address(fix_leader_address(s or ""))
    ok, why = check_receive(s, leader_answer, kind=kind, formal=register_of(persona_name) == "formal", avoid_endings=avoid_endings, no_quote=no_quote)
    if not ok and trace is not None:
        trace.append([f"receive:{kind}", why, (s or "")[:200]])      # (P14d-4) 탈락한 문장과 사유를 턴 기록에 남긴다
    return (s if ok else None), ("ok" if ok else why), (None if ok else (s or None))


def _retry_args(why: str, kind: str, failed: str | None) -> dict:
    """다시 쓰기에 넘길 사유와(길이로 떨어졌을 때만) 앞 문장."""
    return {"note": retry_note(why, kind), "prev": (failed if why == "long" else None)}


def _no_quote(kind: str, session_keys: list[str] | None) -> bool:
    keys = [k for k in (session_keys or []) if k]
    return kind == "probe" and len(keys) >= 2 and (sum(1 for k in keys if k.startswith("말씀")) + 1) / (len(keys) + 1) > QUOTE_SHARE_MAX


async def render_receive(llm, *, leader_answer: str, persona_name: str | None, kind: str = "probe", avoid_endings: list[str] | None = None,
                         prev_answer: str | None = None, session_keys: list[str] | None = None, trace: list | None = None) -> tuple[str | None, str]:
    """(받는 말 한 문장 | None, 모드). 모드 'llm' | 'llm_retry' | 'stub' | 'skip:empty' | 'miss:<사유>'.
    확인에서 떨어지면 사유를 한 줄로 넘겨 한 번 더 쓴다(P14e-2 — P14b 에서 뺐던 본론 받는 말의 다시 쓰기를 되살렸다)."""
    pre = _pre(leader_answer, prev_answer, kind, llm)
    if pre:
        return None, pre
    nq = _no_quote(kind, session_keys)
    why = "empty"
    extra: dict = {"note": None, "prev": None}
    for attempt in (0, 1):
        s, why, failed = await _attempt(llm, leader_answer=leader_answer, persona_name=persona_name, kind=kind, avoid_endings=avoid_endings, no_quote=nq,
                                        trace=trace, **extra)
        if s:
            return s, ("llm_retry" if attempt else "llm")
        if why == "error":
            return None, "miss:error"
        extra = _retry_args(why, kind, failed)
    return None, f"miss:{why}"
