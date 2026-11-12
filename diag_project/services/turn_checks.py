"""(2026-11-12 P11) 코치 턴 결정론 검사 — 받는 문장 금지 꼴, 예고 문장, 하지 않은 말 귀속, 때 이른 감사, 질문 완결성, 받기 겹침.

11/12 운영 Daniel 세션(반말·초단답 리더) 검토에서 나온 문장들을 꼴로 잡는다. 전부 순수 함수(LLM 없음)이고 턴 핸들러가 재생성 예산 1회와 함께 쓴다.
  받는 문장   리더가 질문한 것처럼 쓰는 말 · 리더의 말투를 언급하는 말 · 해석형 받기
  예고 문장   질문이 아닌데 다음에 무엇을 할지만 알리는 문장
  귀속       따옴표 인용이나 '방금·앞서 말씀하신 ○○' 의 ○○ 이 이번 세션 리더 말에 없다
  감사       사례를 닫는 턴이 아닌데 사례를 들려줘서 고맙다고 한다
  질문       접속·조건어로 시작 / 무엇을 묻는지 없는 조각 / 두 질문 / 가리키는 말의 대상이 직전 답에 없다
"""
from __future__ import annotations

import re

from diag_project.services.output_guard import (
    _WH_RE, _compact, _content_chunks, _quote_from_user, count_question_markers, is_question, key_noun_phrase, split_sentences,
)

# ── 받는 문장 금지 꼴 ───────────────────────────────────────────────────────
_ASKED_BY_LEADER_RE = re.compile(r"(여쭤\s*봐|여쭈어\s*봐|물어\s*봐|질문해|질문을\s*해|되물어)\s*주(신|셔서|셨|시는|시니)")
_SPEECH_STYLE_RE = re.compile(
    r"(편하게|편히|편안하게|짧게|간단히|간결하게|솔직하게|담백하게)\s*(말씀|얘기|이야기|답|답변)(해|을\s*해)?\s*주(셔서|신|시니|셨|시는)"
    r"|반말|말을\s*놓|말투|말씀을\s*(편하게|짧게)|짧은\s*(답|말씀)")
_INTERPRET_RE = re.compile(
    r"(으로|처럼|같이|라고|다고)\s*(들리|들립|들려|읽히|읽힙|읽혀)|(들리네요|들립니다|들려요|읽히네요|읽힙니다|읽혀요)[.!…]*$"
    r"|흥미롭|흥미로(운|워|웠)|셈이(네요|군요|에요|죠)|셈입니다|뜻(이군요|이네요|이겠네요|이겠군요)"
    # (시뮬 p11a) 리더가 말하지 않은 것을 짐작해 보태는 받기('…있었을 것 같습니다', '…고민이 있으셨을 것 같습니다') · 감상('…과정이 그려지네요')
    r"|(을|였을|었을|셨을|했을|겠을)\s*것\s*같(습니다|아요|네요)[.!…]*$|것\s*같(습니다|아요|네요)[.!…]*$|그려지(네요|는군요)|그려집니다")


def receive_ban_reason(sentence: str | None) -> str | None:
    """받는 문장(평서문)에 쓰면 안 되는 꼴 — 'asked_by_leader' | 'speech_style' | 'interpretive' | None. 질문 문장은 보지 않는다."""
    s = (sentence or "").strip()
    if not s or s.endswith("?"):
        return None
    if _ASKED_BY_LEADER_RE.search(s):
        return "asked_by_leader"
    if _SPEECH_STYLE_RE.search(s):
        return "speech_style"
    if _INTERPRET_RE.search(s):
        return "interpretive"
    return None


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def _drop(text: str | None, pred, keep: set[str] | None = None) -> tuple[str, list[str]]:
    """pred 에 걸리는 문장을 지운다(keep = 공백 뗀 고정 문장 집합은 제외). 전부 지워지면 원문을 그대로 둔다. (결과, 지운 문장)"""
    keep = keep or set()
    out_lines: list[str] = []
    removed: list[str] = []
    for line in (text or "").split("\n"):
        sents = [x.strip() for x in split_sentences(line) if x.strip()]
        if not sents:
            out_lines.append(line)
            continue
        kept = []
        for s in sents:
            if _norm(s) not in keep and pred(s):
                removed.append(s)
            else:
                kept.append(s)
        if kept:
            out_lines.append(" ".join(kept))
    out = re.sub(r"\n{3,}", "\n\n", "\n".join(out_lines)).strip()
    if not removed or not out:
        return (text or ""), []
    return out, removed


def drop_banned_receives(text: str | None, keep: set[str] | None = None) -> tuple[str, list[str]]:
    """금지 꼴 받는 문장을 지운다. (결과, 사유 목록)"""
    reasons: list[str] = []

    def _pred(s: str) -> bool:
        r = receive_ban_reason(s)
        if r:
            reasons.append(r)
        return bool(r)
    out, removed = _drop(text, _pred, keep)
    return out, (reasons if removed else [])


# ── 예고 문장 ───────────────────────────────────────────────────────────────
_ANNOUNCE_RE = re.compile(
    r"(여쭤보겠습니다|여쭙겠습니다|여쭤볼게요|여쭤보려고\s*(합니다|해요)|여쭤보려고요|여쭙고자\s*합니다|묻겠습니다|물어볼게요|질문드리겠습니다|질문드릴게요|"
    r"듣고\s*싶습니다|듣고\s*싶어요|듣겠습니다|들어보겠습니다|들어볼게요|듣고자\s*합니다|"
    r"이어가겠습니다|이어갈게요|이어가\s*보겠습니다|이어가\s*볼게요|넘어가겠습니다|넘어갈게요|넘어가\s*보겠습니다|"
    r"짚어보겠습니다|짚어볼게요|살펴보겠습니다|살펴볼게요|들여다보겠습니다|들여다볼게요)[.!…]*$")


def is_announcement(sentence: str | None) -> bool:
    """질문이 아닌 예고 문장인가 — '…를 여쭤보겠습니다.', '…를 조금 더 듣고 싶습니다.', '…로 이어가겠습니다.'"""
    s = (sentence or "").strip()
    return bool(s) and not s.endswith("?") and bool(_ANNOUNCE_RE.search(s))


def drop_announcements(text: str | None, keep: set[str] | None = None) -> tuple[str, list[str]]:
    """예고 문장을 지운다 — 그 턴에 진짜 질문(예고가 아닌 질문 문장)이 따로 있을 때만. keep 은 시스템 고정 문장(다리·여는 문장·슬롯)."""
    sents = [x.strip() for x in split_sentences(text or "") if x.strip()]
    if not any(is_question(x) and not is_announcement(x) for x in sents):
        return (text or ""), []
    return _drop(text, is_announcement, keep)


# ── 하지 않은 말 귀속 ───────────────────────────────────────────────────────
_ATTR_LEAD = r"(?:방금|앞서|아까|조금\s*전|좀\s*전|전에)\s*(?:말씀하신|말씀해\s*주신|말씀하셨던|언급하신|얘기하신|이야기하신|들려주신)"
_ATTR_BARE_RE = re.compile(_ATTR_LEAD + r"\s+([가-힣A-Za-z0-9]{2,14})")
_QUOTE_RE = re.compile(r"['‘’\"“”]([^'‘’\"“”\n]{1,40})['‘’\"“”]")
_ATTR_GENERIC = {"내용", "것", "거", "부분", "이야기", "얘기", "사례", "장면", "일", "상황", "말씀", "대로", "바", "그", "이", "점", "대목", "때", "경험",
                 "답", "답변", "건", "것처럼", "바와", "대로라면", "그대로"}
_JOSA_RE = re.compile(r"(과도|와도|이랑|에서|으로|처럼|이라는|라는|에게|과|와|은|는|이|가|을|를|도|에|의|로|만)$")


def _bare_stem(word: str) -> str:
    w = word
    for _ in range(2):
        w2 = _JOSA_RE.sub("", w)
        if w2 == w or len(w2) < 2:
            break
        w = w2
    return w


def unsaid_spans(sentence: str | None, leader_texts: list[str] | None, exempt: list[str] | None = None) -> list[str]:
    """문장이 리더 말로 돌린 낱말(따옴표 인용 · '방금/앞서 말씀하신 ○○') 중 이번 세션 리더 발화에 없는 것."""
    s = sentence or ""
    u = _compact(" ".join(t or "" for t in (leader_texts or [])))
    ex = [_compact(e) for e in (exempt or []) if e]
    out: list[str] = []
    for m in _QUOTE_RE.finditer(s):
        span = m.group(1).strip()
        c = _compact(span)
        if not c or any(c == e or c in e or (len(e) >= 2 and e in c) for e in ex):
            continue
        if not _quote_from_user(c, u):
            out.append(span)
    for m in _ATTR_BARE_RE.finditer(s):
        stem = _bare_stem(m.group(1))
        if stem in _ATTR_GENERIC or len(stem) < 2 or any(stem == e or stem in e for e in ex):
            continue
        c = _compact(stem)
        if c not in u and not (len(c) >= 3 and c[:-1] in u):
            out.append(stem)
    return out


_ATTR_CLAUSE_RE = re.compile(r"^(?P<head>.*?)[,，]\s*(?P<rest>[^,，]{6,}\?)\s*$")


def strip_unsaid_attribution(text: str | None, leader_texts: list[str] | None, exempt: list[str] | None = None,
                             keep: set[str] | None = None) -> tuple[str, list[str], bool]:
    """리더가 하지 않은 말을 리더 말로 돌린 문장을 지운다. (결과, 걸린 낱말, 질문을 잃었는가).
    평서문은 문장째 지운다. 질문 문장은 귀속 절이 쉼표 앞에 있으면 그 절만 떼고('방금 말씀하신 '○○'과도 이어지는 부분입니다만, …?' → '…?'),
    귀속이 질문 몸통 안에 있으면 질문째 지우고 질문을 잃었다고 알린다 — 호출자가 기본 질문으로 메운다."""
    keep = keep or set()
    hits: list[str] = []
    lost_q = False
    out_lines: list[str] = []
    for line in (text or "").split("\n"):
        sents = [x.strip() for x in split_sentences(line) if x.strip()]
        if not sents:
            out_lines.append(line)
            continue
        kept: list[str] = []
        for s in sents:
            if _norm(s) in keep:
                kept.append(s)
                continue
            bad = unsaid_spans(s, leader_texts, exempt)
            if not bad:
                kept.append(s)
                continue
            hits.extend(bad)
            if is_question(s):
                m = _ATTR_CLAUSE_RE.match(s)
                if m and unsaid_spans(m.group("head"), leader_texts, exempt) and not unsaid_spans(m.group("rest"), leader_texts, exempt):
                    kept.append(m.group("rest").strip())
                else:
                    lost_q = True
        if kept:
            out_lines.append(" ".join(kept))
    if not hits:
        return (text or ""), [], False
    out = re.sub(r"\n{3,}", "\n\n", "\n".join(out_lines)).strip()
    return out, hits, lost_q and not any(is_question(x) for x in split_sentences(out))


# ── 때 이른 감사 ────────────────────────────────────────────────────────────
_THANKS_RE = re.compile(r"(들려주셔서|말씀해\s*주셔서|나눠\s*주셔서|이야기해\s*주셔서|얘기해\s*주셔서|공유해\s*주셔서|꺼내\s*주셔서|답해\s*주셔서)\s*"
                        r"(정말\s*|진심으로\s*|대단히\s*)?(감사|고맙)")


def is_thanks_sentence(sentence: str | None) -> bool:
    return bool(_THANKS_RE.search((sentence or "").strip()))


def drop_premature_thanks(text: str | None, keep: set[str] | None = None) -> tuple[str, list[str]]:
    """사례를 닫는 턴이 아닌데 나온 '…들려주셔서 감사합니다' 류 문장을 지운다(호출자가 닫는 턴이 아닐 때만 부른다)."""
    return _drop(text, is_thanks_sentence, keep)


# ── 질문 완결성 ─────────────────────────────────────────────────────────────
_Q_BAD_START_RE = re.compile(r"^(그리고|혹은|또는|또|그렇다면|있었다면|있으셨다면|있다면|없었다면|없으셨다면|그랬다면|그러셨다면|아니라면|아니면)[,，]?\s+")
_FRAGMENT_RE = re.compile(r"[가-힣]+(였|이었)는지(가|도|를)?\s*(궁금|알고\s*싶|듣고\s*싶)")
# 가리키는 말 + 낱말 — 그 낱말(또는 같은 뜻의 말)이 직전 리더 답에 있어야 한다
_DEMO_NOUN_RE = re.compile(r"그\s?(변화|과정|결정|선택|반응|대화|회의|결과|방식|갈등|피드백|면담|평가|제안|계획|목표|기준|이유|태도|표정|조치|약속|원칙|차이)")
_DEMO_EVENT_RE = re.compile(r"(그때|그\s?당시|그날|그\s?시점|그\s?자리|그\s?순간|그\s?장면|그\s?일(?![가-힣])|그\s?상황|그\s?뒤|그\s?후|그\s?이후)")
_DEMO_ALIAS: dict[str, tuple[str, ...]] = {
    "변화": ("변화", "바뀌", "바꾸", "바꿨", "달라", "변했", "변하", "줄였", "늘렸", "없앴", "도입", "새로", "개편", "전환"), "과정": ("과정", "단계", "하면서", "동안", "고 나서", "다음에", "먼저", "차례"),
    "결정": ("결정", "정했", "정하", "하기로", "결론"), "선택": ("선택", "골랐", "고르", "택했", "하기로"),
    "반응": ("반응", "했어요", "했습니다", "하더", "라고", "말했", "표정", "받아들"), "대화": ("대화", "이야기", "얘기", "말했", "면담", "물었", "라고"),
    "회의": ("회의", "미팅", "모여", "모였"), "결과": ("결과", "됐", "되었", "늘었", "줄었", "달라", "끝났", "마무리"),
    "방식": ("방식", "방법", "식으로", "하는 식"), "갈등": ("갈등", "부딪", "다퉜", "반대", "싸", "충돌", "불만"),
    "피드백": ("피드백", "말해 줬", "지적", "조언", "짚어"), "면담": ("면담", "1:1", "일대일", "따로 만나", "따로 불러"),
    "평가": ("평가", "등급", "고과", "점수"), "제안": ("제안", "하자고", "건의", "제시"), "계획": ("계획", "일정", "로드맵", "플랜"),
    "목표": ("목표", "KPI", "타깃", "지표"), "기준": ("기준", "원칙", "잣대"), "이유": ("이유", "때문", "라서", "해서"),
    "태도": ("태도", "자세", "표정", "말투"), "표정": ("표정", "얼굴", "눈빛"), "조치": ("조치", "대응", "처리"), "약속": ("약속", "하기로"),
    "원칙": ("원칙", "기준", "룰", "규칙"), "차이": ("차이", "달랐", "다르", "불일치", "안 맞"),
}
EVENT_ANSWER_MIN_CHARS = 15


def dangling_references(question: str | None, last_user_text: str | None) -> list[str]:
    """질문의 가리키는 말('그 변화', '그 과정', '그때') 중 직전 리더 답에 가리킬 낱말이 없는 것."""
    q = question or ""
    u = last_user_text or ""
    uc = _compact(u)
    out: list[str] = []
    for m in _DEMO_NOUN_RE.finditer(q):
        noun = m.group(1)
        if not any(_compact(a) in uc for a in _DEMO_ALIAS.get(noun, (noun,))):
            out.append(m.group(0))
    if _DEMO_EVENT_RE.search(q):
        from diag_project.services.short_input import is_contentless_answer
        if len(uc) < EVENT_ANSWER_MIN_CHARS or is_contentless_answer(u):
            out.append(_DEMO_EVENT_RE.search(q).group(0))
    return out


def question_issues(question: str | None, last_user_text: str | None) -> list[str]:
    """질문 한 문장의 완결성 위반 — 'dangling_start' | 'fragment' | 'two_questions' | 'dangling_ref'."""
    q = (question or "").strip()
    if not q:
        return []
    out: list[str] = []
    if _Q_BAD_START_RE.match(q):
        out.append("dangling_start")
    if _FRAGMENT_RE.search(q) and not _WH_RE.search(q):
        out.append("fragment")
    if count_question_markers(q) > 1:
        out.append("two_questions")
    if dangling_references(q, last_user_text):
        out.append("dangling_ref")
    return out


def strip_question_start(question: str | None) -> str:
    """질문 머리의 접속·조건어를 뗀다('그리고 …?', '그렇다면 …?', '있었다면 …?'). 남는 것이 질문이 아니면 원문 그대로."""
    q = (question or "").strip()
    rest = q
    for _ in range(2):
        rest2 = _Q_BAD_START_RE.sub("", rest).strip()
        if rest2 == rest:
            break
        rest = rest2
    return rest if (rest != q and len(_compact(rest)) >= 8 and is_question(rest) == is_question(q)) else q


# 슬롯 기본 질문 — 재생성 뒤에도 질문이 완결되지 않을 때 그 슬롯의 질문으로 바꾼다. (합쇼체, 해요체). {topic} = 리더가 쓴 말로 만든 머리('○○' 때).
_DEFAULT_Q: dict[str, tuple[str, str]] = {
    "context": ("{topic}언제 누구와 있었던 일인지 말씀해 주시겠습니까?", "{topic}언제 누구와 있었던 일인지 들려주시겠어요?"),
    "action": ("{topic}리더님이 직접 하신 말이나 행동은 무엇이었습니까?", "{topic}리더님이 직접 하신 말이나 행동은 무엇이었어요?"),
    "reaction": ("{topic}상대는 리더님의 말을 어떻게 받아들였습니까?", "{topic}상대는 리더님의 말을 어떻게 받아들였어요?"),
    "result": ("{topic}그 일이 끝난 뒤에 무엇이 달라졌습니까?", "{topic}그 일이 끝난 뒤에 무엇이 달라졌어요?"),
    "criterion": ("{topic}그렇게 하기로 정하신 기준은 무엇이었습니까?", "{topic}그렇게 하기로 정하신 기준은 무엇이었어요?"),
    "reflection": ("{topic}지금 돌아보면 다르게 하고 싶은 점이 있습니까?", "{topic}지금 돌아보면 다르게 하고 싶은 점이 있으세요?"),
}


def default_slot_question(slot: str | None, *, formal: bool, topic_text: str | None = None) -> str:
    """그 슬롯의 기본 질문. topic_text(사례의 상황 인용 또는 직전 리더 답)에서 핵심 명사구를 뽑아 머리에 붙인다 — 없으면 머리 없이."""
    pair = _DEFAULT_Q.get(slot or "") or _DEFAULT_Q["action"]
    np_ = key_noun_phrase(topic_text or "")
    topic = f"말씀하신 '{np_}' 건에서 " if np_ else ""       # (시뮬 p11a) "'등급' 일에서 …" 는 어색했다
    return pair[0 if formal else 1].format(topic=topic)


# ── 두 질문 가운데 남길 것 · 요청형 질문 ─────────────────────────────────────
_ALT_Q_RE = re.compile(r"(는지|은지|인지|을지|나요|습니까|까요|어요)[,，?]?\s*(아니면|혹은|또는)\s")
_REQ_Q_TAIL_RE = re.compile(r"((?:는|은|인|을|였는|었는|했는|셨는)지)(?:를|가|도)?\s*(?:꼭\s*|한번\s*|조금\s*더\s*)?(여쭙고\s*싶습니다|여쭤보고\s*싶습니다|듣고\s*싶습니다|알고\s*싶습니다|"
                            r"여쭙고\s*싶어요|여쭤보고\s*싶어요|듣고\s*싶어요|알고\s*싶어요|여쭙니다|묻고\s*싶습니다)[.!…]*$")


def prefer_open_question(text: str | None) -> tuple[str, int]:
    """질문 문장이 둘 이상일 때 — 무엇을·어떻게 묻는 열린 질문이 있고 다른 하나가 고르게 하는 질문('…였는지, 아니면 …였는지')이거나 의문사 없는 덧붙임이면
    열린 질문만 남긴다. (시뮬 p11a: '…어떻게 받아들였는지 궁금합니다. 반발이 있었는지, 아니면 수긍하는 쪽이었는지 들려주시겠습니까?' 에서 뒤 질문의
    끝 절만 남아 '수긍하는 쪽이었는지 들려주시겠습니까?' 가 나갔다.) (결과, 지운 질문 수)"""
    sents = [x.strip() for x in split_sentences(text or "") if x.strip()]
    qi = [i for i, x in enumerate(sents) if is_question(x)]
    if len(qi) < 2:
        return (text or ""), 0
    open_q = [i for i in qi if _WH_RE.search(sents[i]) and not _ALT_Q_RE.search(sents[i])]
    if not open_q or len(open_q) == len(qi):
        return (text or ""), 0
    keep_i = open_q[-1]
    kept = [x for i, x in enumerate(sents) if i not in qi or i == keep_i]
    return " ".join(kept).strip(), len(qi) - 1


def request_to_question(sentence: str | None, *, formal: bool) -> str | None:
    """'…무엇이었는지 여쭙고 싶습니다.' → '…무엇이었는지 말씀해 주시겠습니까?' — 예고 꼴로 끝난 질문을 묻는 꼴로. 해당 꼴이 아니면 None."""
    s = (sentence or "").strip()
    m = _REQ_Q_TAIL_RE.search(s)
    if not m:
        return None
    return s[: m.start()] + m.group(1) + (" 말씀해 주시겠습니까?" if formal else " 들려주시겠어요?")


def reask_candidate_ok(candidate: str | None, original: str | None) -> bool:
    """다시 묻기 턴의 새 질문이 직전 질문을 다시 물은 것인가 — 직전 질문과 내용 낱말을 하나는 나누고, 고르게 하는 질문('…인지, 아니면 …')이 아니다."""
    c = (candidate or "").strip()
    if not c or not is_question(c) or _ALT_Q_RE.search(c) or count_question_markers(c) > 1:
        return False
    if re.search(r"(지\s*않으셨|지\s*않았|안\s*하셨|못\s*하셨)(는지|습니까|나요|어요)", c):
        return False                                   # '…나누지 않으셨는지' — 직전 질문을 뒤집어 예·아니오로 묻는 꼴
    generic = ("말씀", "리더님", "리더", "들려", "주시", "이야기", "얘기", "그때", "자리", "무엇", "어떻게", "어떤")
    cc = {x for x in _content_chunks(c) if len(x) >= 2 and not x.startswith(generic)}
    oc = {x for x in _content_chunks(original or "") if len(x) >= 2 and not x.startswith(generic)}
    return bool(oc) and any(a == b or a.startswith(b) or b.startswith(a) for a in cc for b in oc)


# ── 받기 겹침 ───────────────────────────────────────────────────────────────
def receive_overlap(receive: str | None, user_text: str | None) -> tuple[float, float, int]:
    """(받기 어절 중 리더 답에서 온 비율, 리더 답 어절 중 받기에 다시 나온 비율, 받기의 내용 어절 수).
    앞의 값이 높고 받기가 길면 답을 통째로 되풀이한 받기다."""
    rc = [c for c in _content_chunks(receive or "") if len(c) >= 2]
    ucs = [c for c in _content_chunks(user_text or "") if len(c) >= 2]
    if not rc or not ucs:
        return 0.0, 0.0, len(rc)

    def _hit(c: str, pool: list[str]) -> bool:
        return any(c == o or (len(o) >= 2 and (c.startswith(o) or o.startswith(c))) for o in pool)
    from_user = sum(1 for c in rc if _hit(c, ucs))
    covered = sum(1 for c in set(ucs) if _hit(c, rc))
    return round(from_user / len(rc), 2), round(covered / len(set(ucs)), 2), len(rc)
