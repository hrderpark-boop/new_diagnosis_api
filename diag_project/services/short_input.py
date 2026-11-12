"""(2026-11-12 P11-A·H) 짧은 입력 판정 — 동의·거절 사전, 되묻기, 받을 내용이 없는 답. 순수 함수, LLM 없음.

11/12 운영 Daniel 세션(반말·초단답 리더):
  동의  'ㅇㅋ' 가 동의로 읽히지 않아 "'네'라고 답해 주십시오" 재요청이 나갔다 — 동의 판정식이 다섯 군데에 따로 있었고 어느 것도 자모·반말을 몰랐다.
  되묻기 '뭔소리야' 는 답으로 읽혀 슬롯 판정으로 넘어갔다(코치가 무시한 것처럼 보인다).
  내용 없는 답 '네, 맞아요' 뒤에 받을 말이 없는데 받는 문장을 요구했다.
여기 한 곳에 사전을 두고 input_anomaly·instruction_decider·layer3_state·avoidance_detector·bei_engine 이 함께 읽는다.
"""
from __future__ import annotations

import re

# 한 낱말이 통째로 동의·거절인 것만(문장 안의 '아니'·'고' 는 보지 않는다). 겹쳐 쓴 꼴('네네', 'ㅇㅋㅇㅋ', '고고')도 받는다.
CONSENT_WORDS: tuple[str, ...] = (
    "네", "예", "넵", "넹", "넴", "응", "어", "그래", "그래요", "그럼요", "좋아", "좋아요", "좋습니다", "알겠어요", "알겠습니다", "알겠어",
    "괜찮아요", "오케이", "오키", "콜", "계속", "고", "ㅇㅋ", "ㅇㅇ", "ㅇ", "ok", "okay", "yes", "y", "go",
)
DECLINE_WORDS: tuple[str, ...] = (
    "놉", "ㄴㄴ", "ㄴ", "아니", "아니요", "아뇨", "아니오", "싫어", "싫어요", "싫습니다", "안해", "안할래", "no", "nope", "노",
    # (2026-11-12 P11e-1) 있었느냐는 질문에 '없다'는 답 — p11d(나): 재질문에 "없어." 라고 답했는데 내용 없는 답으로 읽혀 한 번 더 물었다
    "없어", "없어요", "없습니다", "없음", "없다", "없었어", "없었어요", "없었습니다", "딱히", "별로", "글쎄", "글쎄요",
)
_PUNCT_RE = re.compile(r"[\s.,!?~^…]+")
WORD_MAX_CHARS = 12


def _core(text: str | None) -> str:
    return _PUNCT_RE.sub("", (text or "")).lower()


def _all_from(text: str | None, words: tuple[str, ...]) -> bool:
    t = _core(text)
    if not t or len(t) > WORD_MAX_CHARS:
        return False
    ws = sorted(words, key=len, reverse=True)
    i = 0
    while i < len(t):
        for w in ws:
            if t.startswith(w, i):
                i += len(w)
                break
        else:
            return False
    return True


def is_consent_word(text: str | None) -> bool:
    """입력 전체가 동의 낱말(들)뿐인가 — 'ㅇㅋ', '넵', '콜', 'ok', '계속', '고'."""
    return _all_from(text, CONSENT_WORDS)


def is_decline_word(text: str | None) -> bool:
    """입력 전체가 거절 낱말(들)뿐인가 — '놉', 'ㄴㄴ', '아니', '싫어', 'no'."""
    return _all_from(text, DECLINE_WORDS)


# 되묻기 — 직전 질문이 무슨 말인지 모르겠다는 입력. 긴 답 속의 '뭐라고'(팀원이 뭐라고 했는지…)는 보지 않는다(25자 이하만).
_CLARIFY_RE = re.compile(
    r"(뭔\s*소리|무슨\s*소리|뭔\s*말|무슨\s*말|뭐라고|뭐라는|뭐래|이해\s*(가|를)?\s*(안|못)|못\s*알아듣|알아듣지\s*못|무슨\s*뜻|뭔\s*뜻|"
    r"질문이\s*(무슨|뭔|뭐|이해|어렵)|다시\s*(말해|말씀해|물어|설명)|쉽게\s*(말해|말씀해|설명|물어)|뭘\s*(묻는|물어|말하는)|무엇을\s*묻는|어렵게\s*(말|물))")
_QMARK_ONLY_RE = re.compile(r"^[\s?？]+$")
_SHORT_ECHO_Q_RE = re.compile(r"^(네|예|뭐|응|어|엥|음)\s*[?？]+$")
CLARIFY_MAX_CHARS = 25


def is_clarify_request(text: str | None) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if _QMARK_ONLY_RE.match(t) or _SHORT_ECHO_Q_RE.match(t):
        return True
    return len(_PUNCT_RE.sub("", t)) <= CLARIFY_MAX_CHARS and bool(_CLARIFY_RE.search(t))


# 받을 내용이 없는 답 — 동의·맞장구뿐이라 받는 문장에 넣을 낱말이 없다.
_CONTENTLESS_RE = re.compile(
    r"^(네|예|넵|응|음|아|뭐|어)?[,.\s]*(맞아요|맞습니다|맞아|맞죠|맞지|그렇죠|그렇습니다|그래요|그래|그런\s*것\s*같아요|그런\s*듯(해요|합니다)?|"
    r"그냥\s*그럼|그냥\s*그래요?|그냥요|그럼요|그쵸|그치|당연하죠|물론이죠|그랬죠|그랬어요|그랬지)[\s.,!~]*$")
CONTENTLESS_MAX_CHARS = 15


def is_contentless_answer(text: str | None) -> bool:
    t = (text or "").strip()
    if not t:
        return False
    if is_consent_word(t):
        return True
    return len(_PUNCT_RE.sub("", t)) <= CONTENTLESS_MAX_CHARS and bool(_CONTENTLESS_RE.match(t))
