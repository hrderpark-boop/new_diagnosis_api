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
ALIGN_MIN_SHARED = 3
SMALL_MAX_EOJEOL = 12
_KIND_WHAT: dict[str, str] = {
    "probe": ("리더가 방금 한 말에서 가장 구체적인 대목 하나를 집어 한 문장으로 다시 말한다. 답 전체를 줄여 옮기지 않는다 — 대목 하나만.",),
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
    "same_ending": "바로 앞에서 쓴 끝맺음과 같았다",
    "empty": "문장이 없었다",
}


def receivable(answer: str | None, prev_answer: str | None = None) -> bool:
    """받을 내용이 있는 답인가 — 내용 낱말이 둘 미만이거나, 떠오르지 않는다는 답이거나, 바로 앞 답과 같으면 부르지 않는다."""
    from diag_project.services.bei_engine import is_no_recall_text
    a = re.sub(r"\s+", " ", (answer or "").strip())
    if len([c for c in _content_chunks(a) if len(c) >= 2]) < 2:
        return False
    if is_no_recall_text(a) and len(a) < 40:
        return False
    return not (prev_answer and re.sub(r"\s+", "", prev_answer) == re.sub(r"\s+", "", a))


def build_receive_prompt(*, leader_answer: str, persona_name: str | None, kind: str = "probe", avoid_endings: list[str] | None = None,
                         retry_note: str | None = None) -> str:
    from diag_project.services.persona_register import register_hint
    from diag_project.services.turn_checks import RECEIVE_ENDING_HINT
    ans = re.sub(r"\s+", " ", (leader_answer or "").strip())[-ANSWER_TAIL_CHARS:]
    avoid = [x for x in (avoid_endings or []) if x][:2]
    limit = ALIGN_MAX_EOJEOL if kind == "align" else 12
    return (
        "당신은 리더십 코치입니다. 리더가 방금 한 말을 한 문장으로 받습니다.\n\n"
        f"[리더가 방금 한 말]\n{ans}\n\n"
        f"[규칙]\n- {_KIND_WHAT.get(kind, _KIND_WHAT['probe'])[0]}\n"
        "- 평서문 한 문장만 쓴다. 물음과 앞으로 무엇을 할지 알리는 말은 쓰지 않는다.\n"
        "- 리더가 쓴 낱말로만 쓴다. 평가·짐작·감상·칭찬을 보태지 않는다. 리더가 말하지 않은 사실은 넣지 않는다.\n"
        f"- {limit}어절을 넘기지 않는다.\n"
        + (f"- 끝은 리더의 말을 다시 말하는 꼴로 맺는다 — {RECEIVE_ENDING_HINT} 가운데 하나.\n" if kind in ("probe", "align") else "")
        + ("- 바로 앞에서 쓴 끝맺음: " + ", ".join(avoid) + " — 이것과 다른 끝맺음으로 맺는다.\n" if avoid and kind in ("probe", "align") else "")
        + "- 누가 한 일인지 분명하지 않으면 높이지 않고 '-다는 말씀이네요' 꼴로 옮긴다. 높임은 리더에게만 쓴다.\n"
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


def check_receive(sentence: str | None, answer: str | None, *, kind: str = "probe", formal: bool = False, avoid_endings: list[str] | None = None) -> tuple[bool, str]:
    """(통과 여부, 사유: ok | empty | question | ending | long | overlap | ban | words | same_ending)"""
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
    ok, why = receive_allowed(s, answer, formal=formal, max_eojeol=(ALIGN_MAX_EOJEOL if kind == "align" else None))
    if not ok:
        return False, why
    if kind == "align" and len(receive_shared_words(s, answer)) < ALIGN_MIN_SHARED:
        return False, "overlap"
    if receive_ban_reason(s):
        return False, "ban"
    av = [x for x in (avoid_endings or []) if x][:2]
    if len(av) == 2 and av[0] == av[1] == receive_ending_key(s):
        return False, "same_ending"
    return True, "ok"


async def _one(llm, prompt: str) -> str | None:
    out = await llm._generate_with_retry(prompt=prompt, max_tokens=120, thinking_budget=0, call_type="receive_render", temperature=0.4)
    text = re.sub(r"\s*\n+\s*", " ", (out or "").strip().strip('"“”'))
    ss = [x.strip() for x in split_sentences(text) if x.strip()]
    return ss[0] if ss else None


async def render_receive(llm, *, leader_answer: str, persona_name: str | None, kind: str = "probe", avoid_endings: list[str] | None = None,
                         prev_answer: str | None = None) -> tuple[str | None, str]:
    """(받는 말 한 문장 | None, 모드). 모드 'llm' | 'llm_retry' | 'stub' | 'skip:empty' | 'miss:<사유>'.
    'miss:<사유>' 의 사유는 마지막 확인에서 떨어진 까닭 또는 no_llm·error."""
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
    note = None
    why = "empty"
    for attempt in (0, 1):
        try:
            s = await _one(llm, build_receive_prompt(leader_answer=leader_answer, persona_name=persona_name, kind=kind, avoid_endings=avoid_endings, retry_note=note))
        except Exception as e:  # noqa: BLE001
            logger.warning("receive render failed: %s", e)
            return None, "miss:error"
        s = fix_leader_address(s or "")
        ok, why = check_receive(s, leader_answer, kind=kind, formal=formal, avoid_endings=avoid_endings)
        if ok or (attempt == 1 and why == "same_ending"):      # 끝맺음만 겹친 것은 두 번째에는 그대로 쓴다(받는 말이 없는 것보다 낫다)
            return s, ("llm_retry" if attempt else "llm")
        note = RETRY_NOTES.get(why, "쓸 수 없는 문장이었다")
    return None, f"miss:{why}"
