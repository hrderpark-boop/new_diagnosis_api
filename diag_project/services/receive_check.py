"""(2026-11-04 P3-1) 되받기 필수 — 모든 대화 턴은 [되받기 1~2문장] + [질문].

되받기(receive)는 질문 앞의 평서문이고, 리더 직전 답의 명사구를 최소 1개 인용해야 한다("현업 활용", "한 과정 시범").
  - lead_cap_for: 리더 답 150자 이상이면 되받기 2문장, 미만이면 1문장.
  - check_receive: (되받기 있음, 리더 명사구 인용함).
  - quote_phrase: 폴백·재생성 지시에 쓸 리더 명사구(연속 명사 2어절 우선).
  - receive_fallback: "'[명사구]'까지 말씀해 주셨네요."(페르소나 격식에 맞춤). 명사구가 없으면 일반 되받기.
  - splice_receive: 본문의 되받기 부분만 새 되받기로 바꾸고 질문부(사다리·슬롯 질문 포함)는 그대로 둔다.
전부 순수 함수. 린트(tools/transcript_lint.py)와 턴 파이프라인(8-w)이 같은 판정을 쓴다.
"""
from __future__ import annotations

import re

from diag_project.services.output_guard import _sentence_nouns, is_question, split_sentences

LONG_ANSWER_CHARS = 150
RECEIVE_REQUIRED_INSTRUCTIONS = frozenset({
    "STAR_INCOMPLETE", "CONTINUE_NORMAL", "CONTRARY_NEEDED", "STAR_COMPLETE_NEW_EVENT",
    "ABSENCE_PROBE", "CHAPTER_NO_YIELD_ULTIMATUM",
})
_FORMAL = {"Jessica", "Daniel", "Lucas"}
_GENERIC_RECEIVE = {"Jessica": "말씀하신 내용, 잘 들었습니다.", "Daniel": "말씀하신 내용, 잘 들었습니다.", "Lucas": "알겠습니다.",
                    "Michael": "네, 잘 들었어요.", "Olivia": "네, 잘 들었어요.", "Ella": "네, 말씀 잘 들었어요."}
_QUOTE_STOP = {"그래서", "그리고", "그런데", "하지만", "그때", "당시", "저희", "우리", "제가", "저는", "저도", "팀원", "팀원들",
               "사람", "자신", "본인", "진행", "상황", "문제", "정도", "이후", "나중", "결국", "먼저", "다시", "계속", "조금", "많이"}


def _key(persona_name: str | None) -> str:
    return (persona_name or "").split(" ")[0] or "Ella"


def _compact(t: str) -> str:
    return re.sub(r"[\s.,!?~'\"“”‘’…·()]+", "", t or "")


def lead_cap_for(user_text: str | None) -> int:
    """리더 답 150자 이상 → 되받기 2문장, 미만 → 1문장."""
    return 2 if len((user_text or "").strip()) >= LONG_ANSWER_CHARS else 1


def receive_statements(text: str | None) -> list[str]:
    """첫 질문 앞의 평서문(되받기)들."""
    out = []
    for s in split_sentences(text or ""):
        s = s.strip()
        if not s:
            continue
        if is_question(s):
            break
        out.append(s)
    return out


def leader_nouns(user_text: str | None) -> list[str]:
    """리더 답의 명사 후보(2자 이상, 조사·활용형 제거, 상투어 제외). 순서 보존·중복 제거."""
    seen: set[str] = set()
    out: list[str] = []
    for n in _sentence_nouns(user_text or ""):
        if n in _QUOTE_STOP or n in seen or len(n) < 2:
            continue
        seen.add(n)
        out.append(n)
    return out


def quoted_nouns(receive_text: str | None, user_text: str | None) -> list[str]:
    """되받기 평서문에 들어 있는 리더 명사."""
    body = _compact(" ".join(receive_statements(receive_text) or [s for s in split_sentences(receive_text or "") if not is_question(s)]))
    return [n for n in leader_nouns(user_text) if _compact(n) in body]


def check_receive(text: str | None, user_text: str | None) -> tuple[bool, bool]:
    """(되받기 평서문이 있는가, 리더 명사구를 인용했는가). 리더 답에 명사가 없으면 인용 요건은 면제(True)."""
    stmts = receive_statements(text)
    if not stmts:
        return False, False
    nouns = leader_nouns(user_text)
    if not nouns:
        return True, True
    return True, bool(quoted_nouns(text, user_text))


def quote_phrase(user_text: str | None) -> str | None:
    """폴백에 인용할 명사구 — 리더 답에서 연속한 명사 2어절(예: '현업 활용')을 우선, 없으면 가장 긴 명사 1개."""
    words = [re.sub(r"[.!?…,\"'“”‘’()]", "", w) for w in (user_text or "").split()]
    nouns = set(leader_nouns(user_text))
    def _stem(w: str) -> str | None:
        for n in sorted(nouns, key=len, reverse=True):
            if w == n or (w.startswith(n) and len(w) - len(n) <= 2):
                return n
        return None
    stems = [_stem(w) for w in words]
    pair = bare_pair = None
    for i in range(len(stems) - 1):
        if stems[i] and stems[i + 1] and words[i] == stems[i]:        # 앞 어절은 조사 없이 명사 그대로일 때만 두 어절 구
            pair = f"{stems[i]} {stems[i + 1]}"                         # 마지막 구 우선 — 답의 끝쪽이 다음 질문이 이어받는 내용
            if words[i + 1] == stems[i + 1]:
                bare_pair = pair                                        # 두 어절 다 조사 없는 구('현업 활용')를 '활용 설문(으로)'보다 우선
    if bare_pair or pair:
        return bare_pair or pair
    return max(nouns, key=len) if nouns else None


def receive_fallback(persona_name: str | None, phrase: str | None) -> str:
    """백엔드 폴백 되받기. 명사구가 있으면 그것을 인용, 없으면 페르소나 일반 되받기."""
    k = _key(persona_name)
    if phrase:
        return f"'{phrase}'까지 말씀해 주셨습니다." if k in _FORMAL else f"'{phrase}'까지 말씀해 주셨네요."
    return _GENERIC_RECEIVE.get(k, _GENERIC_RECEIVE["Ella"])


def splice_receive(reply: str, new_receive: str, cap: int = 1, keep_fixed: list[str] | None = None) -> str:
    """본문의 되받기(첫 질문 앞 평서문)를 new_receive 의 평서문(최대 cap)으로 바꾼다. 질문부는 그대로.
    keep_fixed 에 있는 고정 문장(슬롯 응원·관찰·전환 다리)이 되받기 자리에 있었으면 새 되받기 뒤에 보존한다."""
    sents = [s.strip() for s in split_sentences(reply or "") if s.strip()]
    qi = next((i for i, s in enumerate(sents) if is_question(s)), len(sents))
    old_stmts, rest = sents[:qi], sents[qi:]
    fixed_norm = {_compact(f) for f in (keep_fixed or []) if f}
    kept = [s for s in old_stmts if _compact(s) in fixed_norm or any(f and _compact(f) in _compact(s) for f in (keep_fixed or []))]
    new_stmts = [s.strip() for s in split_sentences(new_receive or "") if s.strip() and not is_question(s)][:cap]
    return " ".join(new_stmts + kept + rest).strip()
