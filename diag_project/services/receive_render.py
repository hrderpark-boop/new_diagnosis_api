"""(2026-11-16 P14-1·3) 받는 말 전용 호출 — 리더가 방금 한 말을 한 문장으로 받는다.

11/16 운영 Lucas(조직관리·성과관리): 받는 말이 없는 턴이 절반이었다. 본 호출이 받는 말과 질문을 함께 쓰고 허용 목록이 받는 말을 지웠기 때문이다
(p13g: 탈락 9~11건). P13f 는 사례를 닫는 턴에만 전용 호출을 썼다 — P14 는 본론의 모든 턴(탐침·첫 꼬리·훑는 질문)과 라포·영역 정의 턴으로 넓힌다.
받는 말은 리더의 직전 답만 있으면 쓸 수 있어 슬롯 판정 호출과 동시에 돈다. 본 호출과 첫 꼬리 전용 호출은 질문만 쓴다.

  kind      쓰는 것                                                확인
  probe     답에서 가장 구체적인 대목 하나를 집어 다시 말하는 한 문장      허용 끝맺음 · 12어절 이하 · 리더 답과 겹치는 내용 낱말 2개 이상 · 금지 꼴 아님
  align     리더의 정의에서 구절 하나를 그대로 집어 다시 말하는 한 문장    허용 끝맺음 · 16어절 이하 · 겹치는 내용 낱말 3개 이상
  smalltalk 짧은 답의 낱말 하나를 받아 한 문장                       내용 낱말이 모두 리더 답에 있는 낱말일 것
  role      낱말 나열 답의 낱말을 그대로 넣어 다시 말하는 한 문장          내용 낱말이 모두 리더 답에 있는 낱말일 것

확인에서 떨어지면 사유를 한 줄로 넘겨 한 번 더 쓴다. 그래도 떨어지면 None — 호출자는 받는 말 없이(라포·영역 정의는 고정 받기로) 내보낸다.
받을 내용이 없는 답('네', '없어요', 떠오르지 않는다는 답)에는 부르지 않는다.
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
# (P14b-2) 리더가 아닌 사람이 주어인 절에 높임이 붙은 꼴 — '팀원들이 … 우려하셨다는', '강사분들이 … 내셨다는'
# (2026-11-17 P14c-3) '…셨다' 꼴만 잡던 것을 넓혔다 — 주어가 제3자이고 같은 절(쉼표 앞)의 서술어에 높임이 있으면 탈락
#   (p14b: '강사분들이 … 제안하기 시작하셨군요', '팀원이 … 동의하셨군요', '팀원들은 … 걱정하셨지만')
_THIRD_HONORIFIC_RE = re.compile(r"(팀원|강사|교육생|직원|담당자|구성원|그분|그\s?사람|동료|상사|후배)[가-힣]{0,3}(이|가|은|는|도|께서)\s[^.,]{0,40}?"
                                 r"([가-힣]셨|[가-힣]시(는|고|며|면|던|지)|하신|으신)")
_LEAD_ADDRESS_RE = re.compile(r"^리더님(께서는|께서|이|은|,)?\s*")
PROBE_CHECK_EOJEOL = 12            # (P14c-6 → P14d-3) 10어절로 낮췄다가 12어절로 되돌렸다(p14c: 길이 탈락 25건). 지시문은 9어절 이내 그대로
# (P14d-1) 받는 말 안의 평가·칭찬 낱말 — 리더가 쓴 낱말이면 그대로 옮긴 것이라 보지 않는다(p14c Daniel: '…제안이 핵심이라고 짚으셨습니다')
_EVAL_WORD_RE = re.compile(r"핵심|인상|훌륭|대단|좋은|멋진|탁월|뛰어난|의미\s*있|돋보")
ALIGN_MIN_SHARED = 3
SMALL_MAX_EOJEOL = 12
_KIND_WHAT: dict[str, str] = {
    # (2026-11-16 P14b-2) 대목 하나 → 낱말 하나. p14: 답 전체를 옮겨 12어절을 넘긴 탈락이 10건 중 9건, 받는 말과 질문 앞 절이 같은 내용을 되풀이했다.
    "probe": ("리더가 방금 한 말에서 가장 구체적인 낱말 하나만 집어 짧은 한 문장으로 다시 말한다. 답 전체를 옮기지 않는다.",),
    "align": ("리더가 방금 말한 뜻풀이에서 구절 하나를 그대로 집어 한 문장으로 다시 말한다. 뜻풀이 전체를 줄여 옮기지 않는다.",),
    "smalltalk": ("리더의 짧은 답에서 낱말 하나를 그대로 받아 한 문장으로 다시 말한다. 리더가 쓰지 않은 낱말을 보태지 않는다.",),
    "role": ("리더가 늘어놓은 낱말을 그대로 넣어 한 문장으로 다시 말한다. 숫자와 직함은 리더가 쓴 그대로 쓰고 다른 뜻으로 풀지 않는다.",),
}
RETRY_NOTES: dict[str, str] = {
    "ending": "끝맺음이 리더의 말을 다시 말하는 꼴이 아니었다",
    "long": "문장이 너무 길었다",
    "overlap": "리더가 쓴 낱말이 모자랐다",
    "ban": "평가·짐작·감상이 섞였다",
    "question": "묻는 문장이었다",
    "words": "리더가 쓰지 않은 낱말이 들어갔다",
    "same_ending": "이번에 쓰지 않기로 한 끝맺음을 썼다",
    "praise": "평가하거나 칭찬하는 낱말이 들어갔다",
    "third_honorific": "리더가 아닌 사람이 한 일에 높임을 붙였다",
    "dup": "'말씀'을 두 번 썼다",
    "quote_cap": "'-다는 말씀이네요' 꼴을 너무 자주 썼다",
    "empty": "문장이 없었다",
}


def receivable(answer: str | None, prev_answer: str | None = None) -> bool:
    """받을 내용이 있는 답인가 — 내용 낱말이 둘 미만이거나, 떠오르지 않는다는 답이거나, 바로 앞 답과 같으면 부르지 않는다."""
    from diag_project.services.bei_engine import is_no_recall_text
    a = re.sub(r"\s+", " ", (answer or "").strip())
    if len([c for c in _content_chunks(a) if len(c) >= 2]) < 2:
        return False
    if is_no_recall_text(a):      # (P14b-2) 모른다·기억나지 않는다는 답은 되받지 않는다(길이와 무관)
        return False
    return not (prev_answer and re.sub(r"\s+", "", prev_answer) == re.sub(r"\s+", "", a))


def build_receive_prompt(*, leader_answer: str, persona_name: str | None, kind: str = "probe", avoid_endings: list[str] | None = None,
                         retry_note: str | None = None, no_quote: bool = False) -> str:
    from diag_project.services.persona_register import register_hint
    from diag_project.services.turn_checks import RECEIVE_ENDING_HINT
    ans = re.sub(r"\s+", " ", (leader_answer or "").strip())[-ANSWER_TAIL_CHARS:]
    from diag_project.services.turn_checks import RECEIVE_KEY_HINT
    avoid = [RECEIVE_KEY_HINT.get(x, x) for x in (avoid_endings or []) if x][:2]
    limit = ALIGN_MAX_EOJEOL if kind == "align" else (PROBE_PROMPT_EOJEOL if kind == "probe" else 12)
    return (
        "당신은 리더십 코치입니다. 리더가 방금 한 말을 한 문장으로 받습니다.\n\n"
        f"[리더가 방금 한 말]\n{ans}\n\n"
        f"[규칙]\n- {_KIND_WHAT.get(kind, _KIND_WHAT['probe'])[0]}\n"
        "- 평서문 한 문장만 쓴다. 물음과 앞으로 무엇을 할지 알리는 말은 쓰지 않는다.\n"
        "- 리더가 쓴 낱말로만 쓴다. 평가·짐작·감상·칭찬을 보태지 않는다. 리더가 말하지 않은 사실은 넣지 않는다.\n"
        f"- {limit}어절을 넘기지 않는다.\n"
        + (f"- 끝은 리더의 말을 다시 말하는 꼴로 맺는다 — {RECEIVE_ENDING_HINT} 가운데 하나.\n" if kind in ("probe", "align") else "")
        + ("- 이번에는 끝을 " + ", ".join(avoid) + " 꼴로 맺지 않는다 — 다른 꼴로 맺는다.\n" if avoid and kind in ("probe", "align") else "")
        + ("- 이번에는 '-다는 말씀이네요', '-다는 말씀이군요' 꼴을 쓰지 않는다.\n" if no_quote and kind == "probe" else "")
        + "- 높임은 리더에게만 쓴다. 팀원·강사·교육생처럼 리더가 아닌 사람이 한 말·걱정·반응을 다시 말할 때는 그 사람을 주어로 밝혀 쓰고 "
        "높임 어미를 붙이지 않는다. 주어를 빼서 리더가 한 일처럼 읽히게 쓰지 않는다.\n"
        "- 문장을 '리더님'으로 시작하지 않는다. '말씀'이라는 낱말은 한 번만 쓴다.\n"
        "- 리더를 부를 때는 '리더님'이라고만 한다.\n"
        f"- 말투: {register_hint(persona_name)}\n"
        + (f"- 앞서 쓴 문장은 쓸 수 없었다 — {retry_note}. 그 점을 고쳐 새로 쓴다.\n" if retry_note else "")
        + "\n출력: 평서문 한 문장만."
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


def strip_lead_address(sentence: str | None) -> str:
    """(P14b-2 → P14c-3) 받는 말 문장 머리의 '리더님,/리더님은/리더님이/리더님께서'를 뗀다(모든 끝맺음) — 받는 말은 주어 없이 쓴다."""
    return _LEAD_ADDRESS_RE.sub("", (sentence or "").strip(), count=1)


def check_receive(sentence: str | None, answer: str | None, *, kind: str = "probe", formal: bool = False, avoid_endings: list[str] | None = None,
                  no_quote: bool = False) -> tuple[bool, str]:
    """(통과 여부, 사유: ok | empty | question | ending | long | overlap | ban | words | third_honorific | dup | quote_cap | same_ending)"""
    from diag_project.services.turn_checks import receive_allowed, receive_ban_reason, receive_ending_key, receive_shared_words
    s = (sentence or "").strip()
    if not s:
        return False, "empty"
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
    if _THIRD_HONORIFIC_RE.search(s):
        return False, "third_honorific"
    if s.count("말씀") >= 2:
        return False, "dup"
    key = receive_ending_key(s) or ""
    if no_quote and key.startswith("말씀"):
        return False, "quote_cap"
    if key and key in [x for x in (avoid_endings or []) if x]:      # (P14c-1) 이번 세션에서 가장 많이 쓴 꼴은 쓰지 않는다
        return False, "same_ending"
    return True, "ok"


async def _one(llm, prompt: str) -> str | None:
    out = await llm._generate_with_retry(prompt=prompt, max_tokens=120, thinking_budget=0, call_type="receive_render", temperature=0.4)
    text = re.sub(r"\s*\n+\s*", " ", (out or "").strip().strip('"“”'))
    ss = [x.strip() for x in split_sentences(text) if x.strip()]
    if not ss:
        return None
    return ss[0] if ss[0][-1] in ".!?…" else ss[0] + "."      # (P14c-5) 끝 부호가 없으면 마침표 — 질문과 붙을 때 문장이 이어 붙지 않게


async def render_receive(llm, *, leader_answer: str, persona_name: str | None, kind: str = "probe", avoid_endings: list[str] | None = None,
                         prev_answer: str | None = None, session_keys: list[str] | None = None, trace: list | None = None) -> tuple[str | None, str]:
    """(받는 말 한 문장 | None, 모드). 모드 'llm' | 'llm_retry' | 'stub' | 'skip:empty' | 'miss:<사유>'.
    'miss:<사유>' 의 사유는 마지막 확인에서 떨어진 까닭 또는 no_llm·error.
    (P14b-2) 본론 받는 말(kind probe)은 다시 쓰지 않는다 — 확인에서 떨어지면 그 턴은 받는 말 없이. 라포·영역 정의는 종전대로 한 번 더 쓴다.
    session_keys = 이번 세션에서 나간 받는 말의 끝맺음 갈래 — 인용꼴이 1/3 을 넘으면 이번에는 그 꼴을 쓰지 않게 한다."""
    from diag_project.services.persona_register import register_of
    from diag_project.services.turn_checks import fix_leader_address
    if kind == "probe" and not receivable(leader_answer, prev_answer):
        return None, "skip:empty"
    if not (leader_answer or "").strip():
        return None, "skip:empty"
    if os.getenv("FM_LLM_STUB"):
        return None, "stub"
    if llm is None:
        return None, "miss:no_llm"
    formal = register_of(persona_name) == "formal"
    keys = [k for k in (session_keys or []) if k]
    no_quote = kind == "probe" and len(keys) >= 2 and (sum(1 for k in keys if k.startswith("말씀")) + 1) / (len(keys) + 1) > QUOTE_SHARE_MAX
    note = None
    why = "empty"
    for attempt in ((0,) if kind == "probe" else (0, 1)):
        try:
            s = await _one(llm, build_receive_prompt(leader_answer=leader_answer, persona_name=persona_name, kind=kind, avoid_endings=avoid_endings,
                                                     retry_note=note, no_quote=no_quote))
        except Exception as e:  # noqa: BLE001
            logger.warning("receive render failed: %s", e)
            return None, "miss:error"
        s = strip_lead_address(fix_leader_address(s or ""))
        ok, why = check_receive(s, leader_answer, kind=kind, formal=formal, avoid_endings=avoid_endings, no_quote=no_quote)
        if ok or (attempt == 1 and why == "same_ending"):      # 끝맺음만 겹친 것은 두 번째에는 그대로 쓴다(라포·영역 정의)
            return s, ("llm_retry" if attempt else "llm")
        if trace is not None:
            trace.append([f"receive:{kind}", why, (s or "")[:200]])      # (P14d-4) 탈락한 문장과 사유를 턴 기록에 남긴다
        note = RETRY_NOTES.get(why, "쓸 수 없는 문장이었다")
    return None, f"miss:{why}"
