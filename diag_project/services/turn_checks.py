"""(2026-11-12 P11) 코치 턴 결정론 검사 — 받는 문장 금지 꼴, 예고 문장, 하지 않은 말 귀속, 때 이른 감사, 질문 완결성, 받기 겹침.

11/12 운영 Daniel 세션(반말·초단답 리더) 검토에서 나온 문장들을 꼴로 잡는다. 전부 순수 함수(LLM 없음)이고 턴 핸들러가 재생성 예산 1회와 함께 쓴다.
  받는 문장   리더가 질문한 것처럼 쓰는 말 · 리더의 말투를 언급하는 말 · 해석형 받기
  예고 문장   질문이 아닌데 다음에 무엇을 할지만 알리는 문장
  귀속       따옴표 인용이나 '방금·앞서 말씀하신 ○○' 의 ○○ 이 이번 세션 리더 말에 없다
  감사       사례를 닫는 턴이 아닌데 사례를 들려줘서 고맙다고 한다
  질문       접속·조건어로 시작 / 무엇을 묻는지 없는 조각 / 두 질문
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
    r"|반말|말을\s*놓|말투|말씀을\s*(편하게|짧게)|짧은\s*(답|말씀)"
    # (시뮬 p11b) '"네, 맞아요"라고 짧게 확인해 주셨는데, … 아직 잘 보이지 않습니다' — 답이 짧다고 말하거나 답이 모자란다고 평하는 문장
    r"|짧게\s*[가-힣]{0,6}\s*주셨|라고만?\s*(짧게|간단히)|아직\s*(잘\s*)?보이지\s*않|닿았는지는")
_INTERPRET_RE = re.compile(
    r"(으로|처럼|같이|라고|다고)\s*(들리|들립|들려|읽히|읽힙|읽혀)|(들리네요|들립니다|들려요|읽히네요|읽힙니다|읽혀요)[.!…]*$"
    r"|흥미롭|흥미로(운|워|웠)|셈이(네요|군요|에요|죠)|셈입니다|뜻(이군요|이네요|이겠네요|이겠군요)"
    # (시뮬 p11a) 리더가 말하지 않은 것을 짐작해 보태는 받기('…있었을 것 같습니다', '…고민이 있으셨을 것 같습니다') · 감상('…과정이 그려지네요')
    r"|(을|였을|었을|셨을|했을|겠을)\s*것\s*같(습니다|아요|네요)[.!…]*$|것\s*같(습니다|아요|네요)[.!…]*$|그려지(네요|는군요)|그려집니다"
    # (시뮬 p11b) '…무겁게 보셨기 때문이겠지요' — 리더가 말하지 않은 까닭을 짐작해 붙이는 받기
    r"|겠(지요|죠)[.!…]*$|때문이겠습니다[.!…]*$")
# (시뮬 p11b) '…상황을 받겠습니다', '…점을 받겠습니다' — 지시문의 말('받는 문장')을 문장으로 옮긴 꼴
_META_RECV_RE = re.compile(r"받(겠습니다|을게요|아\s*두겠습니다|고\s*가겠습니다|아\s*보겠습니다)[.!…]*$")


# (2026-11-12 P11e-3) 리더의 답이 모자라다고 평하는 말 — p11d(나): '그렇게 말씀하시면 그때 상황이 잘 그려지지 않습니다', '…로만 남아 있는 것이 조금 걸립니다'
_JUDGES_ANSWER_RE = re.compile(r"(그려지지\s*않|보이지\s*않|조금\s*걸립|걸리네요|걸리는군요|(으|)로만\s*남아|만으로는\s*(알기|부족|어렵)|충분하지\s*않|모자라|"
                               r"그렇게\s*(말씀|답)하시면|구체적이지\s*않|막연하|두루뭉술)")


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
    if _META_RECV_RE.search(s):
        return "meta"
    if _JUDGES_ANSWER_RE.search(s):
        return "judges_answer"
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
_Q_BAD_START_RE = re.compile(r"^(그리고|혹은|또는|또|그렇다면|있었다면|있으셨다면|있다면|없었다면|없으셨다면|그랬다면|그러셨다면|아니라면|아니면|특히|그중에서도)[,，]?\s+")
_FRAGMENT_RE = re.compile(r"[가-힣]+(였|이었)는지(가|도|를)?\s*(궁금|알고\s*싶|듣고\s*싶)")
# (2026-11-12 P11d-2) '가리키는 말의 대상 없음' 검사(그 변화·그 과정·그때 → 직전 답에 낱말이 있어야 한다)는 삭제 — p11c 재생성 9턴 중 4턴이
#   이 검사였고 3턴은 다시 써도 안 풀려 기본 질문으로 끝났다. 가리키는 말을 쓰지 말라는 것은 프롬프트 규칙으로만 둔다.


def question_issues(question: str | None, last_user_text: str | None = None) -> list[str]:
    """질문 한 문장의 완결성 위반 — 'dangling_start' | 'fragment' | 'two_questions'. (last_user_text 는 호환용 — 쓰지 않는다)"""
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


_WEAK_TOPIC_HEADS = frozenset({"상태", "상황", "일", "것", "때", "부분", "경우", "정도", "생각", "문제", "방식", "결과", "과정", "이유", "기준", "점", "쪽", "말",
                                "이야기", "얘기", "사람", "팀", "팀원", "자리", "내용", "방향", "변화", "효과", "먼저", "다음", "처음"})


def default_slot_question(slot: str | None, *, formal: bool, topic_text: str | None = None) -> str:
    """그 슬롯의 기본 질문. topic_text(사례의 상황 인용 또는 직전 리더 답)에서 핵심 명사구를 뽑아 머리에 붙인다 — 없으면 머리 없이."""
    pair = _DEFAULT_Q.get(slot or "") or _DEFAULT_Q["action"]
    np_ = key_noun_phrase(topic_text or "")
    # (2026-11-12 P11e-6) 머리 낱말을 못 고르면 머리 없이 질문만 — p11d: "말씀하신 '상태' 건에서 …". 뜻이 넓은 한 낱말은 머리로 쓰지 않는다
    if np_ and (len(np_.replace(" ", "")) < 2 or np_.strip() in _WEAK_TOPIC_HEADS):
        np_ = ""
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


# ════════════════════════════════════════════════════════════════════════════
# (2026-11-12 P11b) 재시뮬 전 추가 — 전부 삭제·치환(재생성 없음)
# ════════════════════════════════════════════════════════════════════════════

# ── 2. 안내 중복 ────────────────────────────────────────────────────────────
_INTRO_ANNOUNCE_RE = re.compile(r"(안내|설명|소개)(해\s*)?(드리|드릴|하겠|할게)|말씀드리겠|말씀드릴게|시작하겠|시작할게|진행하겠|넘어가겠|이어가겠|흐름부터|순서부터")


def is_intro_announce(sentence: str | None) -> bool:
    """진단 안내 턴의 LLM 받기가 안내를 예고하는 문장인가('네, 그러면 오늘 흐름부터 안내드리겠습니다.') — 고정 안내의 첫 문장과 겹친다."""
    return bool(_INTRO_ANNOUNCE_RE.search((sentence or "").strip()))


# ── 3. 내용 없는 연결 문구 ──────────────────────────────────────────────────
# "방금 말씀하신 '자원'과도 이어지는 부분입니다만, …" — 리더가 실제로 한 말이어도 틀 자체를 지운다. 출처는 문체 제약 프롬프트의 예시였다
# (style_tracker '연결 한 절' 규칙, 2026-09-17) — 그 규칙도 함께 뺐다.
_LINK_CLAUSE_RE = re.compile(
    r"(말씀하신|말씀해\s*주신|말씀하셨던|언급하신|얘기하신|이야기하신|들려주신|짚어\s*주신)[^,，.?!]{1,40}?"
    r"(과도|와도|과|와|하고도|이랑도|에서도|에도|이|가)\s*(이어지|이어져|닿아|맞닿|연결되|연결돼|통하|통합니다|관련(이|되|돼)|겹치|맞물)"
    r"|(그\s*)?(결|연장선|맥락|흐름)(에서|으로)\s*(이어서?\s*)?(여쭙|여쭤|묻|질문)"
    r"|(이어서|연결해서?|연결\s*지어)\s*(여쭙|여쭤|묻겠|질문드)")


def strip_link_frames(text: str | None, keep: set[str] | None = None) -> tuple[str, int]:
    """리더의 말과 다음 질문을 잇기만 하는 절을 지운다 — 쉼표로 나뉜 절 단위(뒤 질문은 남긴다). 그 절뿐인 평서문은 문장째 지운다. (결과, 지운 수)"""
    keep = keep or set()
    n = 0
    out_lines: list[str] = []
    for line in (text or "").split("\n"):
        sents = [x.strip() for x in split_sentences(line) if x.strip()]
        if not sents:
            out_lines.append(line)
            continue
        kept: list[str] = []
        for s in sents:
            if _norm(s) in keep or not _LINK_CLAUSE_RE.search(s):
                kept.append(s)
                continue
            clauses = [c.strip() for c in re.split(r"[,，]\s*", s) if c.strip()]
            rest = [c for c in clauses if not _LINK_CLAUSE_RE.search(c)]
            n += 1
            if rest and len(rest) < len(clauses) and len(_compact(" ".join(rest))) >= 8:
                kept.append(", ".join(rest))
        if kept:
            out_lines.append(" ".join(kept))
    if not n:
        return (text or ""), 0
    out = re.sub(r"\n{3,}", "\n\n", "\n".join(out_lines)).strip()
    return (out, n) if out else ((text or ""), 0)


# 진행 해설 — "…을 살펴보는 대목입니다", "…을 어떻게 하시는지 살펴보겠습니다". 사례를 여는 턴(EPISODE_OPEN·SWEEP_ANCHOR)에서 지운다.
#   영역 첫 소개 턴(정의 질문 앞의 범위 문장)은 호출자가 부르지 않는다.
_COMMENTARY_RE = re.compile(
    r"(살펴보|들여다보|짚어\s*보|알아보|확인하|보)(는|려는|고자\s*하는)\s*(대목|부분|자리|순서|차례|지점|쪽)(입니다|이에요|예요|이죠|입니다만|인데요)"
    r"|(살펴보겠습니다|살펴볼게요|살펴보려고\s*(합니다|해요)|살펴보려\s*합니다|들여다보겠습니다|들여다볼게요|짚어\s*보겠습니다|짚어\s*볼게요|알아보겠습니다|알아볼게요|"
    r"보겠습니다|볼게요|보려고\s*(합니다|해요))[.!…]*$")


def is_progress_commentary(sentence: str | None) -> bool:
    s = (sentence or "").strip()
    return bool(s) and not s.endswith("?") and bool(_COMMENTARY_RE.search(s))


def strip_progress_commentary(text: str | None) -> tuple[str, int]:
    """진행 해설 문장을 지운다 — 질문이 남을 때만. 질문 문장 앞 절이 해설이면('…살펴보는 대목입니다만, 최근에 …?') 그 절만 뗀다. (결과, 지운 수)"""
    src = text or ""
    n = 0
    out_lines: list[str] = []
    for line in src.split("\n"):
        sents = [x.strip() for x in split_sentences(line) if x.strip()]
        if not sents:
            out_lines.append(line)
            continue
        kept: list[str] = []
        for s in sents:
            if is_progress_commentary(s):
                n += 1
                continue
            if s.endswith("?") and _COMMENTARY_RE.search(s):
                clauses = [c.strip() for c in re.split(r"[,，]\s*", s) if c.strip()]
                rest = [c for c in clauses if not _COMMENTARY_RE.search(c)]
                if rest and len(rest) < len(clauses) and rest[-1].endswith("?"):
                    kept.append(", ".join(rest))
                    n += 1
                    continue
            kept.append(s)
        if kept:
            out_lines.append(" ".join(kept))
    out = re.sub(r"\n{3,}", "\n\n", "\n".join(out_lines)).strip()
    if not n or not out or not any(is_question(x) for x in split_sentences(out)):
        return src, 0
    return out, n


# ── 6. 여는 문장의 머리 — 앞 문맥에 기대는 말 ────────────────────────────────
_LEAN_START_RE = re.compile(r"^(하다\s*보면|그러다\s*보면|이러다\s*보면|그렇게\s*하다\s*보면|그러다\s*보니|그러다가|그리고|그러면|그럼|그렇다면|또한|또|한편|아울러|"
                            r"그\s*과정에서|그런\s*가운데|이와\s*함께|이어서)[,，]?\s+")


def strip_lean_start(sentence: str | None) -> tuple[str, bool]:
    """'하다 보면 팀원에게 …' → '팀원에게 …'. 남는 것이 너무 짧으면 그대로."""
    s = (sentence or "").strip()
    rest = _LEAN_START_RE.sub("", s, count=1).strip()
    return (rest, True) if (rest != s and len(_compact(rest)) >= 8) else (s, False)


# ── 5. 받는 문장의 '리더님께서' 머리 · 답 전체를 되풀이하는 받기 ─────────────
RECEIVE_REPEAT_MAX = 0.6            # 리더 답 내용 어절 가운데 받기에 다시 나온 비율 — 이 이상이고
RECEIVE_REPEAT_MIN_CHUNKS = 10      # 받기의 내용 어절이 이만큼 이상이면 구절 인용 받기로 바꾼다(p11a 16턴 중 4턴)
RECEIVE_MAX_EOJEOL = 12             # (P11e-5) 탐침 턴의 질문 앞 평서문이 이 어절 수를 넘으면 삭제
LEADER_PREFIX_SESSION_MAX = 2
_LEADER_PREFIX_RE = re.compile(r"^리더님께서(는|도)?\s+")
_OTHER_SUBJECT_RE = re.compile(
    r"(?:[가-힣A-Za-z]{1,6}\s?(?:님|씨|선임|책임|수석|대리|과장|차장|부장|팀장|실장|본부장|매니저|프로|사원|주임|기획|운영|파트장)|팀원(?:들)?|구성원(?:들)?|두\s*사람|두\s*분|"
    r"그분(?:들)?|상대(?:방)?|강사(?:들|분)?|대표|본부|고객(?:사)?|담당자)(?:님)?(?:이|가|께서)\s")


def starts_with_leader_prefix(sentence: str | None) -> bool:
    return bool(_LEADER_PREFIX_RE.match((sentence or "").strip()))


def leader_prefix_wrong_subject(sentence: str | None) -> bool:
    """'리더님께서 억울해하던 이기획님이 표를 보고 …' — '리더님께서' 뒤의 첫 절에 다른 사람이 주어로 온다."""
    s = (sentence or "").strip()
    m = _LEADER_PREFIX_RE.match(s)
    if not m:
        return False
    first_clause = re.split(r"[,，]", s[m.end():], maxsplit=1)[0]
    return bool(_OTHER_SUBJECT_RE.search(first_clause + " "))


def strip_leader_prefix(sentence: str | None) -> str:
    return _LEADER_PREFIX_RE.sub("", (sentence or "").strip(), count=1)


# ── 6. 한 문장 안의 두 질문 ─────────────────────────────────────────────────
_SLOT_Q_WORDS: dict[str, re.Pattern] = {
    "context": re.compile(r"(언제|누구와|누구랑|어디서|어떤\s*상황|계기|배경)"),
    "action": re.compile(r"(직접|하신\s*말|하신\s*행동|꺼내신|어떻게\s*(하셨|대응|움직)|무엇을\s*(하셨|먼저)|먼저\s*하신)"),
    "reaction": re.compile(r"(반응|받아들|태도|표정|뭐라고|어떻게\s*나왔)"),
    "result": re.compile(r"(결과|달라|변화|바뀌|이후|그\s*뒤)"),
    "criterion": re.compile(r"(기준|이유|왜\s|판단|근거|까닭|고르신|택하신|선택하신)"),
    "reflection": re.compile(r"(돌아보|다시\s*(한다면|하신다면|하면)|배우신|배운|바꾸고\s*싶|아쉬)"),
}
_CONNECT_END_RE = re.compile(r"(고|며|으며|는지|은지|인지|었는지|였는지|했는지|셨는지)$")
_CLAUSE_TO_Q: list[tuple[str, str, str]] = [        # (이음 어미, 합쇼체 질문, 해요체 질문)
    (r"(셨|했|였|었|았|겠)(고|으며)$", r"\1습니까?", r"\1어요?"),
    (r"(하시|이시|으시|시)(고|며)$", r"\1ㅂ니까?", r"\1나요?"),
    (r"((?:는|은|인|었는|였는|했는|셨는)지)$", r"\1 말씀해 주시겠습니까?", r"\1 들려주시겠어요?"),
]


_DIRECT_Q_END_RE = re.compile(r"(습니까|[가-힣]니까|나요|가요|까요|어요|아요|죠)$")
_INDIRECT_END_RE = re.compile(r"(는지|은지|인지|을지)$")
_COND_START_RE = re.compile(r"^(있었다면|있으셨다면|있다면|그랬다면|그러셨다면|그렇다면|아니면|혹은|또는|그리고)\s")


def inline_question_clauses(question: str | None) -> list[str]:
    """한 문장 안에 쉼표로 이어진 질문 덩어리들. 둘 이상이면 두 질문이다. 아니면 빈 목록.
      ① 의문사 절이 둘 이상이고 앞 절이 이음 어미로 끝난다   '무엇을 확인하려 하셨고, … 판단 기준은 무엇이었습니까?'
      ② 앞 절이 이미 질문으로 끝났다                         '반응은 어떠했습니까, … 달라진 것이 있었습니까?'   (시뮬 p11b)
      ③ '~는지' 절 뒤에 조건·선택어로 다시 묻는다            '…나서신 일이 있으셨는지, 있었다면 무엇을 먼저 하셨는지 …'   (시뮬 p11b)"""
    q = (question or "").strip()
    if not q or not is_question(q):
        return []
    body = re.sub(r"['‘“\"][^'’”\"\n]{0,80}['’”\"]", lambda m: m.group(0).replace(",", "‚"), q)
    clauses = [c.strip().replace("‚", ",") for c in re.split(r"[,，]\s*", body) if c.strip()]
    if len(clauses) < 2:
        return []
    wh = [i for i, c in enumerate(clauses) if _WH_RE.search(c)]
    cut: set[int] = set()                       # 이 절 뒤에서 끊는다
    if len(wh) >= 2:
        for i in wh[:-1]:
            if _CONNECT_END_RE.search(clauses[i]):
                cut.add(i)
    for i, c in enumerate(clauses[:-1]):
        if _DIRECT_Q_END_RE.search(c) and len(_compact(" ".join(clauses[i + 1:]))) >= 6:
            cut.add(i)
        if _INDIRECT_END_RE.search(c) and _COND_START_RE.match(clauses[i + 1] + " "):
            cut.add(i)
    if not cut:
        return []
    out: list[str] = []
    start = 0
    for i in sorted(cut):
        out.append(", ".join(clauses[start:i + 1]))
        start = i + 1
    out.append(", ".join(clauses[start:]))
    return [p for p in out if p]


def keep_slot_question(question: str | None, slot: str | None, *, formal: bool) -> tuple[str, bool]:
    """한 문장 안 두 질문 → 그 턴의 슬롯에 해당하는 질문 하나만. 앞 절을 남길 때는 이음 어미를 질문 어미로 바꾸고, 표에 없는 꼴이면 마지막 절을 남긴다.
    (결과, 잘랐는가)"""
    q = (question or "").strip()
    parts = inline_question_clauses(q)
    if len(parts) < 2:
        return q, False
    pat = _SLOT_Q_WORDS.get(slot or "")
    pick = next((i for i, p in enumerate(parts) if pat is not None and pat.search(p)), len(parts) - 1)
    if any(_COND_START_RE.match(p + " ") for p in parts[1:]):
        pick = len(parts) - 1                    # '…있으셨는지, 있었다면 무엇을 …' — 앞 절은 있었는지 확인일 뿐, 묻는 것은 뒤 절이다
    if pick != len(parts) - 1:
        from diag_project.services.conjugation import attach_b, bad_form
        cand = None
        p = parts[pick].rstrip(" ,")
        if _DIRECT_Q_END_RE.search(p):
            cand = p + "?"                      # 앞 절이 이미 질문 어미로 끝났다 — 물음표만 붙인다
        for pat_c, rep_f, rep_p in ([] if cand else _CLAUSE_TO_Q):
            m = re.search(pat_c, p)
            if not m:
                continue
            if "ㅂ니까" in rep_f:
                stem = p[: m.start()] + m.group(1)
                cand = (attach_b(stem, "니까") + "?") if formal else (stem + "나요?")
            else:
                cand = re.sub(pat_c, rep_f if formal else rep_p, p)
            break
        if cand and not bad_form(cand):
            return cand, True
        pick = len(parts) - 1
    last = re.sub(r"^(그리고|또는|또|그래서|혹은|아니면|있었다면|있으셨다면|있다면|그랬다면|그러셨다면|그렇다면)[,，]?\s+", "", parts[pick].strip())
    return (last if (last.endswith("?") or is_question(last)) else last + "?"), True


_GENERIC_Q_WORDS = ("말씀", "리더님", "리더", "들려", "주시", "주실", "이야기", "얘기", "무엇", "어떻게", "어떤", "언제", "누구", "있었", "있으셨", "있습", "궁금",
                    "하셨", "했는", "그때", "자리", "장면", "직접", "먼저", "처음", "가장", "하나", "한 가지", "부분", "점이", "떠오르", "기억", "혹시", "당시", "그날")


def _q_chunks(text: str | None) -> set[str]:
    return {c for c in _content_chunks(text or "") if len(c) >= 2 and not c.startswith(_GENERIC_Q_WORDS)}


def _shares(a: str, pool: set[str]) -> bool:
    return any(a == b or a.startswith(b) or b.startswith(a) or a[:2] == b[:2] for b in pool)


# ── (2026-11-12 P11c-4) 사례 없음 뒤의 재질문 · 같은 질문 ─────────────────────
_REFRAME_EXIST_RE = re.compile(r"(있으셨|있었|있으세요|있나요|있을까요|있으신가요|있습니까|있으십니까|있는지|떠오르|기억(나|에 남)|겪으신 적|하신 적|해 ?보신 적)")
_REFRAME_PRESUPPOSE_RE = re.compile(r"(언제\s*누구와|누구와\s*있었던|언제였|언제\s*있었던|하셨을 때|받으셨을 때|했을 때|때 어떻게|때 무엇을|직접 하신 말이나 행동|"
                                    r"어떻게 받아들였|무엇이 달라졌|정하신 기준|다르게 하고 싶은)")


def reframe_question_ok(question: str | None) -> bool:
    """사례가 없다는 답 뒤의 재질문이 '그런 일이 있었는지'를 다른 각도로 묻는 꼴인가 — 사례가 있다고 전제한 질문('언제 누구와 있었던 일인지')은 아니다."""
    q = (question or "").strip()
    return bool(q) and bool(_REFRAME_EXIST_RE.search(q)) and not _REFRAME_PRESUPPOSE_RE.search(q)


def same_question(a: str | None, b: str | None) -> bool:
    """낱말만 바꾼 같은 질문인가 — 글자 순서가 80% 이상 같거나, 내용 낱말(어간 앞 두 글자)의 70% 이상이 겹친다."""
    import difflib
    na, nb = _compact(a or ""), _compact(b or "")
    if not na or not nb:
        return False
    if difflib.SequenceMatcher(None, na, nb).ratio() >= 0.8:
        return True
    # 묻는 몸통(마지막 쉼표 뒤)이 거의 같으면 앞의 상황 절만 바꾼 같은 질문이다 — '…떠올려 보시면, 언제쯤이었고 누구와 함께 있었는지 …'
    ta, tb = _compact(re.split(r"[,，]", a or "")[-1]), _compact(re.split(r"[,，]", b or "")[-1])
    if min(len(ta), len(tb)) >= 10 and difflib.SequenceMatcher(None, ta, tb).ratio() >= 0.75:
        return True
    ca, cb = {c[:2] for c in _q_chunks(a)}, {c[:2] for c in _q_chunks(b)}
    if len(ca) < 2 or len(cb) < 2:
        return False
    return len(ca & cb) / len(ca | cb) >= 0.7


# ── (2026-11-12 P11e) 사례 없음 뒤 재질문·이미 닫힌 사례 ─────────────────────
_CASE_GENERIC = frozenset(("팀원", "팀장", "회의", "최근", "올해", "작년", "지난", "이번", "리더", "사람", "그때", "직접", "먼저", "이유", "설명", "자리", "구성", "조직", "방향", "우리", "상황", "경우", "때였"))
_LIKE_CASE_RE = re.compile(r"(처럼|때처럼|같은|같이|당시|그때)")


def mentions_closed_case(question: str | None, case_contexts: list[str] | None) -> str | None:
    """재질문 문장이 앞에서 닫힌 사례를 끌어왔으면 겹친 낱말들('교육 체계 개편처럼 …' → '교육·체계·개편'). 아니면 None.
    case_contexts = 닫힌 사례마다 리더가 말한 상황 인용. 그 인용의 내용 낱말(앞 두 글자, 때를 가리키는 말·흔한 말 제외)이 질문에 3개 이상 나오거나,
    '…처럼'·'그때' 같은 말과 함께 2개 이상 나올 때."""
    q = {c[:2] for c in _content_chunks(question or "") if len(c) >= 2}
    like = bool(_LIKE_CASE_RE.search(question or ""))
    for ctx in case_contexts or []:
        c = {x[:2] for x in _content_chunks(ctx or "") if len(x) >= 2 and not re.match(r"\d", x)} - _CASE_GENERIC
        hit = sorted(q & c)
        if len(hit) >= 3 or (like and len(hit) >= 2):
            return "·".join(hit)
    return None


def is_new_fact(quote: str | None, original_text: str | None) -> bool:
    """(P11e-2) 다시 말한 답에서 나온 인용이 원래 사례에 없던 사실인가 — 인용의 내용 낱말(앞 두 글자) 가운데 원래 사례에서 리더가 한 말에 있는 것이 60% 미만일 때."""
    a = {c[:2] for c in _content_chunks(quote or "") if len(c) >= 2}
    if len(a) < 2:
        return False
    e = {c[:2] for c in _content_chunks(original_text or "") if len(c) >= 2}
    return len(a & e) / len(a) < 0.6


_BACKREF_RE = re.compile(r"(아까|앞서|앞에서|방금|이미)\s*(말씀드린|말씀드렸|말한|말했|얘기한|이야기한)|같은\s*(일|사례|건)|그\s*일(에서|이요|인데)")


def same_incident(answer: str | None, closed_texts: dict | None) -> object | None:
    """리더 답이 이번 영역에서 이미 닫힌 사례와 같은 사건이면 그 사례의 표지(사례 번호 또는 'sweepN'). 아니면 None.
    답의 내용 낱말(어간 앞 두 글자) 가운데 그 사례에서 리더가 한 말과 겹치는 비율이 60% 이상이고 5개 이상 겹치거나,
    '아까 말씀드린 그 일' 처럼 앞 이야기를 가리키면서 3개 이상 겹칠 때."""
    a = {c[:2] for c in _content_chunks(answer or "") if len(c) >= 2}
    if len(a) < 3:
        return None
    backref = bool(_BACKREF_RE.search(answer or ""))
    best, best_n = None, 0
    for tag, txt in (closed_texts or {}).items():
        e = {c[:2] for c in _content_chunks(txt or "") if len(c) >= 2}
        n = len(a & e)
        if ((n >= 5 and n / len(a) >= 0.6) or (backref and n >= 3)) and n > best_n:
            best, best_n = tag, n
    return best
