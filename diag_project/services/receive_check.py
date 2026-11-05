"""(2026-11-04 P3-1) 되받기 필수 — 모든 대화 턴은 [되받기 1~2문장] + [질문].

되받기(receive)는 질문 앞의 평서문이고, 리더 직전 답의 명사구를 최소 1개 인용해야 한다("현업 활용", "한 과정 시범").
  - lead_cap_for: 리더 답 150자 이상이면 되받기 2문장, 미만이면 1문장.
  - check_receive: (되받기 있음, 리더 명사구 인용함).
  - quote_phrase: 폴백·재생성 지시에 쓸 리더 명사구(연속 명사 2어절 우선).
  - splice_receive: 본문의 되받기 부분만 새 되받기로 바꾸고 질문부(사다리·슬롯 질문 포함)는 그대로 둔다.
전부 순수 함수. 린트(tools/transcript_lint.py)와 턴 파이프라인(8-w)이 같은 판정을 쓴다.
"""
from __future__ import annotations

import re

from diag_project.services.output_guard import _SUGGESTION_RE, is_question, split_sentences

LONG_ANSWER_CHARS = 150
# (2026-11-04 BEI) 되받기 필수 턴 = 사례 탐침·여는 턴·SWEEP 턴 전부. 폴백 문장은 없다 — 재생성 2회 뒤에도 없으면 그대로 내보내고
#   guard_log receive_miss 로 남긴다(린트 '되받기 없는 턴' 0 기준).
RECEIVE_REQUIRED_INSTRUCTIONS = frozenset({"EPISODE_OPEN", "EPISODE_PROBE", "EPISODE_RETRY", "SWEEP_ANCHOR", "SWEEP_FOLLOWUP"})
_QUOTE_STOP = {"그래서", "그리고", "그런데", "하지만", "그때", "당시", "저희", "우리", "제가", "저는", "저도", "팀원", "팀원들",
               "사람", "자신", "본인", "진행", "상황", "문제", "정도", "이후", "나중", "결국", "먼저", "다시", "계속", "조금", "많이",
               # (2026-11-04 2차) p3q 1차 인용구 '아니라 교육'·'특히 교육'·'구성해야 하니' — 부사·접속사·활용형이 명사로 잡혔다
               "아니라", "특히", "가장", "미리", "아직", "우선", "모든", "다른", "어떻게", "얼마나", "단순히", "실제", "실제로", "직접",
               "중간중간", "어떤", "그냥", "함께", "같이", "매우", "바로", "예전", "처음", "그렇게", "이렇게", "오히려", "거의", "전혀",
               "항상", "자주", "가끔", "벌써", "이미", "이제", "지금", "당장", "역시", "물론", "아마", "혹시", "만약", "비록", "하나",
               "어느", "여러", "각자", "서로", "스스로", "어디", "무엇", "뭔가", "무언가", "무엇인가", "전체", "일부", "대부분", "경우",
               "정말", "너무", "아주", "조금씩", "일단", "결과적", "최종적", "기본적", "충분히", "제대로", "꾸준히", "굳이", "다만"}
# 활용형·연결어미로 끝나는 어절은 명사가 아니다(_sentence_nouns 의 동사 필터가 놓치는 것들).
_NON_NOUN_END_RE = re.compile(r"(는데|은데|하니|으니|니까|이라서|라서|해야|하기|되기|보기|도록|해서|어서|아서|면서|로서|거나|든지|지만|으며|더니|려고|고자|"
                              r"하면|되면|이면|라면|다면|하고|되고|했고|겠다|습니다|합니다|입니다|했는지|하는지|되는지|인지|보다|까지|부터|처럼|마다|뿐|들)$")
_TAIL_PARTICLE_RE = re.compile(r"(에서는|에서도|에서|에게|에는|에도|으로는|으로도|으로|로는|로도|로|과|와|은|는|이|가|을|를|의|에|도|만|뿐|까지|부터|처럼|보다|마다)$")


# 동사·형용사 활용 어미(어절 끝). output_guard._sentence_nouns 의 필터에서 '서'를 뺐다 — '부서·현업에서'를 지우던 원인.
_VERB_END_RE = re.compile(r"(하는|되는|한|된|할|될|하셨|셨|였|있|없|했|던|시|겠|죠|요|네|다|지|고|면|며|워|운|웠|해|써|봐|줘|니|라|야|게|히|져|려|뤄|쳐|친|낀)$")
_VERB_STEM_STOP = {"마치", "만드", "바꾸", "나누", "느끼", "세우", "높이", "줄이", "살피", "고치", "맞추", "비추", "다루", "거치", "미루",
                   "이루", "꺼내", "보내", "지내", "건네", "드리", "달리", "돌리", "올리", "내리", "들이", "붙이", "모으", "따르"}


# '질문하는·활용하는지도·포함하도록' 처럼 조사와 겹치는 활용형 — 뒤에 조사가 붙어도 동사다.
_VERB_COMPOUND_RE = re.compile(r"(하는|되는|하고|되고|하며|되며|하면|되면|하니|되니|했|됐|해서|해야|하는지|되는지|한지|된지|이라|이며|이고|하기|되기|하도록|되도록|하자|되자)"
                               r"(도|만|는|은|를|을|가|이|에|로)?$")
# 2자 어절은 조사·어미를 떼면 1자라 어차피 못 쓴다 — 끝이 조사·어미면 통째로 버린다('되는·점이·중에').
_TWO_CHAR_BAD_END_RE = re.compile(r"(는|은|이|가|을|를|의|도|에|로|과|와|고|다|지|요|네|죠|겠|해|야|니|서|며|면|워|웠|써|봐|줘|시|던|할|될|한|된|낀|눠|져|린|친|쳐|려|뤄|떤|른|긴|킨|낸|렸|킬|릴|울|을)$")


_BOUND_NEXT = {"수", "것", "게", "줄", "때", "적", "쪽", "지", "뿐", "데", "바", "채", "듯", "만큼", "탓", "것도", "것은", "것이", "수도", "적이", "적도", "때가", "때는"}


def _noun_ok(w: str) -> str | None:
    """명사 후보 정제: 활용형 제외 → 조사 제거 → 복수 '들'·상투어·연결어미 제외. 통과하면 정제된 명사, 아니면 None."""
    w0 = re.sub(r"[^가-힣a-zA-Z0-9]", "", w or "")
    if len(w0) < 2 or _VERB_COMPOUND_RE.search(w0):
        return None
    if len(w0) == 2:
        return None if _TWO_CHAR_BAD_END_RE.search(w0) or w0 in _QUOTE_STOP or w0 in _VERB_STEM_STOP else w0
    if _VERB_END_RE.search(w0) and not _TAIL_PARTICLE_RE.search(w0):
        return None
    w1 = _TAIL_PARTICLE_RE.sub("", w0) if len(w0) >= 3 else w0
    if len(w1) > 2 and w1.endswith("들"):
        w1 = w1[:-1]
    if len(w1) < 2 or w1 in _QUOTE_STOP or w1 in _VERB_STEM_STOP or _NON_NOUN_END_RE.search(w1) or _VERB_END_RE.search(w1) and w1 != w0:
        return None
    return w1


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
    words = re.sub(r"[.!?…,\"'“”‘’()\[\]:;]", " ", user_text or "").split()
    for i, n0 in enumerate(words):
        if i + 1 < len(words) and words[i + 1] in _BOUND_NEXT:
            continue   # '줄일 수 있는'·'느낀 적'·'만드는 쪽' — 의존명사 앞 어절은 관형형(동사)이다
        n = _noun_ok(n0)
        if not n or n in seen:
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



def splice_receive(reply: str, new_receive: str, cap: int = 1, keep_fixed: list[str] | None = None) -> str:
    """본문의 되받기(첫 질문 앞 평서문)를 new_receive 의 평서문(최대 cap)으로 바꾼다. 질문부는 그대로.
    keep_fixed 에 있는 고정 문장(슬롯 응원·관찰·전환 다리)이 되받기 자리에 있었으면 새 되받기 뒤에 보존한다."""
    sents = [s.strip() for s in split_sentences(reply or "") if s.strip()]
    qi = next((i for i, s in enumerate(sents) if is_question(s)), len(sents))
    old_stmts, rest = sents[:qi], sents[qi:]
    fixed_norm = {_compact(f) for f in (keep_fixed or []) if f}
    kept = [s for s in old_stmts if _compact(s) in fixed_norm or any(f and _compact(f) in _compact(s) for f in (keep_fixed or []))]
    # (3차) LLM 권유 평서문('…떠올려 주셔도 좋아요.')은 되받기가 아니다 — 상한 밖
    new_stmts = [s.strip() for s in split_sentences(new_receive or "") if s.strip() and not is_question(s) and not _SUGGESTION_RE.search(s.strip())][:cap]
    return " ".join(new_stmts + kept + rest).strip()
