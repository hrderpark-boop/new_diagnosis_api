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


# (2026-11-17 P14c-5) 지시어(그·이·저) 바로 뒤에 서술어가 온 꼴 — 사이의 말이 지워져 문장이 깨졌다
#   (p14b Ella: '…가늠하셨는지, 그 들려주시겠어요?' — 금지 문구 '판단의 근거를'을 낱말만 들어낸 결과)
DEMONSTRATIVE_GAP_RE = re.compile(r"(?<![가-힣])(그|이|저)\s+((들려|말씀해|알려|짚어|설명해|전해|옮겨|떠올려)\s*주|하셨|했|되었|됐|있었|있으셨)")


def question_issues(question: str | None, last_user_text: str | None = None) -> list[str]:
    """질문 한 문장의 완결성 위반 — 'dangling_start' | 'fragment' | 'two_questions'. (last_user_text 는 호환용 — 쓰지 않는다)"""
    q = (question or "").strip()
    if not q:
        return []
    out: list[str] = []
    if _Q_BAD_START_RE.match(q):
        out.append("dangling_start")
    if (_FRAGMENT_RE.search(q) and not _WH_RE.search(q)) or DEMONSTRATIVE_GAP_RE.search(q):
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
    "reaction": ("{topic}그 말을 들은 분은 어떻게 받아들였습니까?", "{topic}그 말을 들은 분은 어떻게 받아들였어요?"),
    "result": ("{topic}그 일이 끝난 뒤에 무엇이 달라졌습니까?", "{topic}그 일이 끝난 뒤에 무엇이 달라졌어요?"),
    "criterion": ("{topic}그렇게 하기로 정하신 기준은 무엇이었습니까?", "{topic}그렇게 하기로 정하신 기준은 무엇이었어요?"),
    "reflection": ("{topic}지금 돌아보면 다르게 하고 싶은 점이 있습니까?", "{topic}지금 돌아보면 다르게 하고 싶은 점이 있으세요?"),
}


_WEAK_TOPIC_HEADS = frozenset({"상태", "상황", "일", "것", "때", "부분", "경우", "정도", "생각", "문제", "방식", "결과", "과정", "이유", "기준", "점", "쪽", "말",
                                "이야기", "얘기", "사람", "팀", "팀원", "자리", "내용", "방향", "변화", "효과", "먼저", "다음", "처음"})


def default_slot_question(slot: str | None, *, formal: bool, topic_text: str | None = None) -> str:
    """그 슬롯의 기본 질문 — 머리 없이 질문만. (2026-11-13 P12-1) '말씀하신 '○○' 건에서' 머리는 삭제했다(topic_text 는 쓰지 않는다 — 호출부 호환용)."""
    pair = _DEFAULT_Q.get(slot or "") or _DEFAULT_Q["action"]
    return pair[0 if formal else 1].format(topic="")


# ── (2026-11-15 P13c-1) 사례의 첫 꼬리 질문 확인 — 리더가 직접 한 말·조치를 묻는가 ──────────────
#   합격 = (가) 리더의 말·행동을 묻는 표지가 하나 이상 있고 (나) 때·장면·반응·판단 기준·결과를 묻는 표지가 없다. 앞에 놓인 때 절('…하셨을 때,')은 보지 않는다.
#   불합격이면 다시 쓰지 않고 말투별 대체 문장으로 바꾼다(intro_messages.first_probe_fallback).
#   (2026-11-15 P13d-2) (나)에 "시점"·"어떤 생각"·"어떤 마음" 추가 — p13c Daniel: '…어떤 생각이 드셨는지, 그리고 이야기를 꺼내신 시점이 …'이 '꺼내신'으로 통과했다.
FIRST_PROBE_ACTION_MARKS = ("직접", "하신 말·말씀·일·행동·조치", "한/하신/꺼내신/건네신/전하신 (첫) 말·말씀·마디", "말씀하셨", "말씀을 하셨/꺼내셨/건네셨/나누셨",
                            "꺼내신·꺼내셨", "건네신·건네셨", "전하신·전하셨", "조치", "첫마디", "뭐라고·무엇이라고", "어떤 말·무슨 말", "어떻게 움직이셨",
                            "…하셨(생각·판단·고민·예상·기대·가늠·정·느끼·기억 뒤는 제외)",
                            # (2026-11-15 P13e-1) 조치·순서·준비 쪽 표지
                            "어떤 조치·일·행동", "무엇을/무엇부터 …셨", "어떻게 진행·처리·정리·준비하셨", "어떤 순서·순서로·순서대로·차례로", "먼저 무엇",
                            "준비하신·준비하셨", "확인하신·확인하셨", "점검하신·점검하셨", "챙기신·챙기셨", "미리",
                            "어떤 방식으로", "어떻게 … 찾으셨/찾아가셨/풀어 가셨")
FIRST_PROBE_OFF_MARKS = ("언제", "시점", "어떤 생각", "어떤 마음", "누구와", "누가 함께/같이", "어떤/어느/떠오르는/기억나는/기억에 남는 장면·상황·순간", "장면·상황은 무엇/어땠",
                         "어떤 반응", "반응은 어땠/어떻게/보였", "어떻게 받아들", "어떻게 보였/들었/느꼈",
                         "어떤 기준·판단·근거", "기준·근거는 무엇/어떻게", "이유·까닭은 무엇", "왜",
                         "달라졌·달라진", "어떤 결과·변화", "결과·변화는 어땠/무엇", "어떻게 됐/바뀌/이어졌")
_FP_ACTION_RE = re.compile(
    r"직접|하신\s*(말|말씀|일|행동|조치)|(한|하신|건넨|건네신|꺼낸|꺼내신|전한|전하신)\s*(첫\s*)?(말|말씀|마디)"
    r"|말씀(을|이|은)?\s*(먼저\s*)?(하셨|꺼내셨|건네셨|나누셨|드리셨)|말씀하셨|꺼내(신|셨)|건네(신|셨)|전하(신|셨)|조치|첫\s?마디|뭐라고|무엇이라고"
    r"|(어떤|무슨)\s*말|어떻게\s*움직이셨"
    r"|(?<!생각)(?<!판단)(?<!고민)(?<!예상)(?<!기대)(?<!가늠)(?<!느끼)(?<!기억)(?<!정)하셨"
    r"|(어떤|무슨)\s*(일|행동)|(무엇|뭘)(을|부터)?\s*[^,?]{0,14}셨|어떻게\s*(진행|처리|정리|준비|풀어|나누)[가-힣]{0,3}셨|어떤\s*순서|순서로|순서대로|차례(로|는)|먼저\s*(무엇|뭘|어떤)"
    r"|(준비|확인|점검)하(신|셨)|챙기(신|셨)|미리"
    r"|어떤\s*방식으로|어떻게\s*[^,?]{0,14}(찾으셨|찾아\s*가셨|풀어\s*가셨|풀어내셨)")      # (P13f-3) p13e Olivia: '어떤 방식으로 … 찾아가셨나요'가 떨어졌다
_FP_OFF_RE = re.compile(
    r"언제|시점|(어떤|무슨)\s*(생각|마음)|누구와|누가\s*(함께|같이)|(어떤|어느|떠오르는|기억나는|기억에\s*남는)\s*(장면|상황|순간)|(장면|상황)(은|이|을)?\s*(무엇|어땠|어떠|떠올)"
    r"|어떤\s*반응|반응(은|이|을|이나)?\s*[^,]{0,8}(어땠|어떠|어떻게|무엇|보였|보이)|어떻게\s*받아들|어떻게\s*(보였|들었|느꼈)"
    r"|어떤\s*(기준|판단|근거)|(기준|근거)(은|이|을)?\s*[^,]{0,6}(무엇|어떻게|어떤|세우)|(이유|까닭)(는|가|를|이)?\s*[^,]{0,6}(무엇|뭐|어떤|말씀|들려|알려)|왜\s"
    r"|달라졌|달라진|(어떤|무슨)\s*(결과|변화)|(결과|변화)(는|가|를)?\s*[^,]{0,6}(어땠|어떠|무엇|어떻게)|어떻게\s*(됐|되었|바뀌|이어졌)")
_FP_SUB_RE = re.compile(r"(때|뒤|후|전|동안|순간|시점)(에|에는|에도|는|도)?[,，]?\s|(는데|은데|지만|면서|고서|다가)[,，]?\s")


def first_probe_asking_part(question: str | None) -> str:
    """질문 문장에서 앞에 놓인 때·배경 절('…하셨을 때,', '…한 뒤', '…는데')을 뗀 나머지 — 실제로 묻는 자리."""
    q = (question or "").strip()
    end = 0
    for m in _FP_SUB_RE.finditer(q):
        end = m.end()
    return q[end:].strip() or q


# (2026-11-15 P13e-1) 예/아니오로 답하게 되는 꼴 — 의문사도 청하는 말도 없이 '…있었나요?', '…하셨습니까?'로 끝나는 질문(p13d: Ella·Jessica·Michael 1건씩)
_FP_WH_RE = re.compile(r"무엇|무슨|뭐|뭘|어떤|어떻게|어느|어디|누구|누가|얼마|몇\s|왜")
_FP_ASK_FOR_RE = re.compile(r"(들려|말씀해|알려|짚어|전해|옮겨|설명해|풀어|떠올려|나눠|꺼내)\s*주|궁금|여쭙|여쭤")
# (2026-11-15 P13e-4) 맺지 않은 문장 — 말줄임표로 끝나거나 '…습니다만', '…지만', '…는데'로 끝난다(p13d Lucas: '…짚어 주시겠습니다만…')
_FP_UNFINISHED_RE = re.compile(r"(…|\.{2,})\s*$|(습니다만|니다만|지만|는데|은데|인데)[.?!]*\s*$|[,，]\s*$")


# (2026-11-15 P13f-1 → P13g-1) 질문에 넣은 상대 — '○○에게/○○들에게/○○께/○○한테'.
#   P13f: 리더가 말을 건넨 상대로 말한 사람이 아니면 질문을 통째로 대체 문장으로 바꿨다 → 멀쩡한 질문도 떨어졌다(p13f 대체 4/9·4/10).
#   P13g: 그 어절(앞의 꾸밈말 포함)만 지우고 나머지 질문은 그대로 내보낸다. 통과 기준도 넓혔다 — ○○이 리더 직전 답에 사람으로 나오면 합격(주어로만 나와도).
#   다만 리더가 그 사람을 말을 건넨 상대로 말하지 않았고 ○○이 제3자 목록(가르친 사람·고객)에 있으면 지운다. 답에 없는 사람도 지운다.
THIRD_PARTY_WORDS: tuple[str, ...] = ("교육생", "수강생", "참가자", "참석자", "학습자", "고객사", "고객", "수료생", "신입사원", "학생")      # tools/regression_table.py 의 목록과 같다
_FP_TO_RE = re.compile(r"(?<![가-힣])(?P<mod>(?:(?:그|이|저|해당|각|모든|여러|몇몇)\s+)?(?:[가-힣]{1,6}의\s+)?)(?P<who>[가-힣]{1,8}?)(?:분)?(?:들)?(?:에게|한테|(?<!함)께(?!서))\s*")
_FP_TO_SKIP = frozenset(("리더님", "리더", "본인", "자신", "스스로", "저", "제"))
_FP_PRONOUN = frozenset(("그", "이"))
_FP_PERSON_RE = re.compile("|".join(THIRD_PARTY_WORDS) + "|팀원|직원|구성원|강사|동료|상사|후배|선배|담당자|팀장|임원|부서장")


def _addressee_keep(who: str, answer: str) -> bool:
    w = re.escape(who)
    if re.search(rf"{w}(?:분)?(?:들)?(?:에게|한테|께(?!서)|와|과|이랑|랑|하고)|{w}(?:분)?(?:들)?(?:을|를)\s*(?:따로\s*)?(?:불러|만나)", answer):
        return True                                   # 리더가 말을 건넨 상대로 말했다
    return who in answer and who not in THIRD_PARTY_WORDS


_FP_BARE_ADV = frozenset(("직접", "먼저", "따로", "바로", "처음", "다시", "그때", "당시", "모두", "함께", "실제로", "특히", "결국"))
_FP_JOSA_END = "을를이가은는에도로때서고며면지게히과와만의다요까든써럼터"


def first_probe_addressee_fix(question: str | None, leader_answer: str | None) -> tuple[str, list[str], bool]:
    """첫 꼬리 질문에서 걸린 상대 어절만 지운다(앞에 붙은 꾸밈말 — 지시어·'○○의'·조사 없는 앞 명사 — 포함).
    반환 (고친 질문, 지운 어절 목록, 온전한가). 걸린 것이 없으면 (질문 그대로, [], True).
    지운 자리 앞에 꾸미는 절('…하는', '…한')이 남으면 온전하지 않다(False) — 호출자가 한 번 더 쓴다."""
    q = (question or "").strip()
    ans = leader_answer or ""
    removed: list[str] = []
    out = []
    pos = 0
    clean = True
    for m in _FP_TO_RE.finditer(q):
        who = m.group("who")
        if who in _FP_TO_SKIP:
            continue
        if who in _FP_PRONOUN:                         # '그분께'·'그들에게' — 질문 안에서 바로 앞에 나온 사람 낱말로 판단한다(없으면 둔다)
            prev = [x.group(0) for x in _FP_PERSON_RE.finditer(q[:m.start()])]
            keep = _addressee_keep(prev[-1], ans) if prev else True
        else:
            keep = _addressee_keep(who, ans)
        if keep:
            continue
        start = m.start()
        head = q[pos:start]
        prev = re.search(r"([가-힣]+)\s+$", head)          # 조사 없이 앞에 붙은 명사('거래처 담당자에게')는 함께 지운다
        if prev and prev.group(1) not in _FP_BARE_ADV and prev.group(1)[-1] not in _FP_JOSA_END:
            start = pos + prev.start()
            head = q[pos:start]
        elif re.search(r"[가-힣](는|은|던|한|된|인|할|을|의)\s+$", head):
            clean = False                                    # 꾸미는 절이 남는다('수업을 듣는 ○○에게')
        out.append(head)
        removed.append(q[start:m.end()].strip())
        pos = m.end()
    if not removed:
        return q, [], True
    out.append(q[pos:])
    fixed = re.sub(r"\s{2,}", " ", "".join(out)).strip()
    fixed = re.sub(r"^[,，]\s*", "", fixed)
    return fixed, removed, clean


# (2026-11-15 P13g-2·3) 혼잣말·지시문 낱말이 섞인 질문, 코치 자신이 주어인 동사에 묻는 어미가 붙은 꼴
_FP_META_RE = re.compile(r"규칙|지시|한\s*문장이어야|—|아니,")
_FP_SELF_VERB_RE = re.compile(r"(여쭙고|여쭤보고|묻고|듣고|알고)\s*싶습니까|여쭙겠습니까|묻겠습니까|궁금합니까|궁금하십니까")
_FP_WONDER_END_RE = re.compile(r"(궁금하네요|궁금합니다|궁금해요|궁금하군요)[.?!]*\s*$|여쭤(봐)?도\s*될까요\??\s*$|여쭙고\s*싶습니다[.?!]*\s*$")
_FP_HONORIFIC_RE = re.compile(r"셨|세요|십시오|시(겠|는|고|며|면|어|나|지|던|ㄹ)|하신|으신|[가-힣]신\s|실\s|실까|실래|리더님")
FIRST_PROBE_RETRY_NOTES: dict[str, str] = {
    "closed": "그렇다·아니다로 답하게 되는 꼴이었다",
    "off": "리더 본인이 한 것이 아니라 때·다른 사람의 반응·기준·결과를 물었다",
    "no_action": "리더 본인이 한 말이나 조치를 묻지 않았다",
    "unfinished": "문장을 끝맺지 않았다",
    "meta": "질문 말고 다른 말이 섞였거나 문장이 둘 이상이었다",
    "self_verb": "코치 자신이 하는 일에 묻는 어미를 붙였다",
    "no_question": "질문 문장이 없었다",
    "who": "리더가 말을 건넨 상대로 말하지 않은 사람을 질문에 넣었다",
    "wonder": "묻는 꼴이 아니라 궁금하다거나 여쭤봐도 되느냐는 말로 끝났다",
    "no_honorific": "리더가 한 일을 높임 없이 적었다",
}


def first_probe_retry_note(why: str | None) -> str:
    return FIRST_PROBE_RETRY_NOTES.get(str(why or "").split(":")[0], "질문으로 쓸 수 없는 문장이었다")


def first_probe_question_ok(question: str | None, leader_answer: str | None = None) -> tuple[bool, str]:
    """사례의 첫 꼬리 질문이 리더가 직접 한 말·조치를 묻는가.
    (합격 여부, 사유: ok | no_question | meta | self_verb | unfinished | closed | no_action | off:<걸린 말>)
    leader_answer 를 주면 (나) 표지가 리더 답에 그대로 있는 낱말 하나일 때는 표지로 보지 않는다(P13f-3).
    질문에 넣은 상대는 여기서 보지 않는다 — 호출자가 first_probe_addressee_fix 로 그 어절만 지운 뒤 이 확인을 부른다(P13g-1)."""
    q = (question or "").strip()
    if not q:
        return False, "no_question"
    from diag_project.services.output_guard import split_sentences as _ss_fp
    if _FP_META_RE.search(q) or len([x for x in _ss_fp(q) if x.strip()]) >= 2:
        return False, "meta"
    if _FP_SELF_VERB_RE.search(q):
        return False, "self_verb"
    if _FP_UNFINISHED_RE.search(q):
        return False, "unfinished"
    part = first_probe_asking_part(q)
    off = None
    for m in _FP_OFF_RE.finditer(part):
        word = m.group(0).strip()
        # (P13f-3) 리더가 쓴 낱말 그대로면 표지가 아니다 — p13e: 리더의 '중간 점검 시점'이 질문에 들어가 '시점'에 걸렸다. 의문사가 붙은 표지('어떤 반응')는 그대로 본다.
        if leader_answer and " " not in word and word in leader_answer:
            continue
        off = m
        break
    if off:
        return False, f"off:{off.group(0).strip()}"
    if not _FP_WH_RE.search(q) and not _FP_ASK_FOR_RE.search(q):
        return False, "closed"
    if not _FP_ACTION_RE.search(part):
        return False, "no_action"
    if _FP_WONDER_END_RE.search(q):
        return False, "wonder"          # (P14-4) '…궁금하네요.', '…여쭤봐도 될까요?' — 묻는 꼴로 다시 쓴다
    if not _FP_HONORIFIC_RE.search(q):
        return False, "no_honorific"    # (P14-4) 리더 높임('-시-')이 하나도 없다(p13g: '본인이 … 건넸는지', '리더가 … 취한 조치는')
    return True, "ok"


# ── (2026-11-15 P13e-1) 첫 꼬리 질문의 각도 넷 ─────────────────────────────────────────
#   said 그때 한 말 · did 직접 취한 조치 · order 일을 진행한 순서.
#   리더의 여는 답에 이미 나온 각도와, 이번 세션에서 직전에 쓴 각도는 피한다. 남은 것 가운데 세션에서 가장 적게 쓴 각도를 고른다(코드가 고른다 —
#   전용 호출에는 고른 각도 하나만 넘긴다. 기록 first_probe_angle).
# (2026-11-15 P13f-2) '그 전에 준비하거나 확인한 것'(prep) 각도는 삭제 — p13e: 두 코치 모두 '준비한 것이 없다'는 답이 돌아와 한 턴이 비었다. 각도는 셋.
FIRST_PROBE_ANGLES: tuple[str, ...] = ("said", "did", "order")
FIRST_PROBE_ANGLE_LABELS: dict[str, str] = {"said": "그때 한 말", "did": "직접 취한 조치", "order": "일을 진행한 순서"}
_ANGLE_IN_ANSWER: dict[str, re.Pattern] = {
    "said": re.compile(r"자고\s?(제안|했|말|이야기|얘기|요청|청했)|(라고|다고|냐고|달라고)\s?(말|했|이야기|얘기|물|요청|설명)|말씀드렸|이야기했|얘기했|물었|물어봤|물어보고|설명했|설명하고|[\"“”]"),
    "did": re.compile(r"맡겼|미뤘|나눴|나누고|바꿨|줄였|늘렸|만들었|골랐|조정했|반영했|반영하면서|도입했|배정했|넘겼|시범\s?운영(했|하고)|진행하도록\s?했|쓰기로\s?했|다시\s?잡았"),
    "order": re.compile(r"먼저[^.]{0,40}(뒤|다음|이후|나서)|[가-힣]\s?뒤(에)?[ ,]|고\s?나서|그다음|그\s다음|이후(에)?\s"),
}


def first_probe_angles_in(answer: str | None) -> list[str]:
    """리더 답에 이미 나온 각도(낱말 기준)."""
    t = answer or ""
    return [a for a in FIRST_PROBE_ANGLES if _ANGLE_IN_ANSWER[a].search(t)]


def pick_first_probe_angle(answer: str | None, used: list[str] | None = None) -> str:
    """이번 첫 꼬리 질문의 각도 — 답에 이미 나온 각도와 직전에 쓴 각도를 뺀 것 가운데 세션에서 가장 적게 쓴 것(같으면 목록 순서).
    다 빠지면 직전 각도만 피한다."""
    used = [u for u in (used or []) if u in FIRST_PROBE_ANGLES]
    last = used[-1] if used else None
    present = set(first_probe_angles_in(answer))
    cand = [a for a in FIRST_PROBE_ANGLES if a not in present and a != last] or [a for a in FIRST_PROBE_ANGLES if a != last]
    return min(cand, key=lambda a: (used.count(a), FIRST_PROBE_ANGLES.index(a)))


# ── (2026-11-15 P13e-4) 문장 마무리 — 뜻을 바꾸지 않는 부호 수선만 ─────────────────────────
_WONDER_Q_RE = re.compile(r"(궁금(해요|합니다|하네요|했어요|했습니다))\?")
_ASK_END_STRICT_RE = re.compile(r"(까요|나요|니까|는지요|실래요|인가요|던가요|[을를]\s*수\s*있(을까요|나요|습니까|겠습니까))$")


# (2026-11-15 P13g-3) p13f Daniel: '…말씀해 주십시오?'(청하는 말에 물음표), '…순서를 여쭙겠습니다: …'(쌍점 머리말)
_REQUEST_Q_RE = re.compile(r"(주십시오|주세요|주시기\s*바랍니다|주시지요|바랍니다)\?")
_COLON_HEAD_RE = re.compile(r"(?:^|(?<=[.?!]\s))[^.?!:：\n]{0,60}(?:여쭙겠습니다|여쭤보겠습니다|묻겠습니다|질문드리겠습니다|여쭙니다)\s*[:：]\s*")


def finish_sentence_marks(text: str | None) -> tuple[str, int]:
    """① '…궁금해요?'·'…궁금합니다?' 의 물음표를 마침표로 ② 묻는 어미로 끝나는데 끝 부호가 없으면 물음표를 붙인다. (고친 글, 고친 수)"""
    t = (text or "")
    n = 0
    t2, k = _WONDER_Q_RE.subn(r"\1.", t)
    n += k
    t2, k = _REQUEST_Q_RE.subn(r"\1.", t2)          # (P13g-3) 청하는 꼴에는 물음표를 붙이지 않는다
    n += k
    t2, k = _COLON_HEAD_RE.subn("", t2)             # (P13g-3) '…여쭙겠습니다: ' 같은 쌍점 머리말은 쌍점까지 지운다
    n += k
    tail = t2.rstrip()
    if tail and tail[-1] not in ".?!…\"'”’)" and _ASK_END_STRICT_RE.search(tail):
        t2 = tail + "?"
        n += 1
    return t2, n


# ── (2026-11-13 P12-1·4) 질문이 스스로 서는가 · 질문 끝맺음 ─────────────────────────────
_OVERLAP_GENERIC = frozenset(("리더", "어떻", "어떤", "무엇", "무슨", "누가", "누구", "언제", "어디", "그때", "그것", "그게", "이것", "직접", "먼저", "가장",
                              "실제", "혹시", "조금", "하나", "말씀", "이야", "얘기", "생각", "기억", "처음", "다음", "지금", "최근", "당시", "순간", "자리",
                              "결정", "상황", "과정", "결과", "부분", "방식", "기준", "이유", "변화", "반응", "행동", "있었", "있으", "하셨", "했는", "됐는",
                              "들려", "떠올", "알려", "짚어", "궁금", "여쭙", "여쭤", "주시", "주실", "주세", "어땠", "되었", "보셨", "느끼", "드셨"))


def question_overlap(question: str | None, answer: str | None) -> list[str]:
    """질문 문장에 리더의 답과 겹치는 내용 낱말(앞 두 글자 기준) — 지시어·의문사·흔한 낱말은 세지 않는다. 겹친 낱말(질문 쪽 표기) 목록.
    지시어('그때'·'그 결정')를 보는 검사가 아니다 — 겹치는 낱말이 하나라도 있는지만 본다."""
    a = {c[:2] for c in _content_chunks(answer or "") if len(c) >= 2} - _OVERLAP_GENERIC
    out: list[str] = []
    for c in _content_chunks(question or ""):
        if len(c) >= 2 and c[:2] in a and c[:2] not in _OVERLAP_GENERIC and c not in out:
            out.append(c)
    return out


def answer_has_words(answer: str | None) -> bool:
    """겹침을 따질 만한 낱말이 답에 있는가(흔한 낱말을 뺀 내용 낱말 2개 이상)."""
    return len({c[:2] for c in _content_chunks(answer or "") if len(c) >= 2} - _OVERLAP_GENERIC) >= 2


_REQ_END_RE = re.compile(
    r"((?:말씀|이야기|얘기|설명)해\s*|들려\s*|떠올려\s*|알려\s*|짚어\s*|꺼내\s*|나눠\s*|풀어\s*|옮겨\s*)"
    r"(주실\s*수\s*있(?:을까요|으실까요|으세요|겠습니까|습니까|나요|으신가요)|주시겠(?:어요|습니까)|주실래요|주실까요|주세요|주십시오|주시죠|"
    r"주시면\s*(?:좋겠|감사하겠|됩니다|돼요)[가-힣]*|줄\s*수\s*있(?:을까요|나요))[?.!…\s]*$")
# (2026-11-15 P13d-1) 같은 끝맺음 4회째면 다시 쓰던 검사(QUESTION_ENDING_MAX)는 삭제했다 — 끝맺음 세기는 프롬프트에 넘기는 목록과 점검표에만 쓴다


def request_ending_key(question: str | None) -> str | None:
    """청하는 꼴로 끝나는 질문의 끝맺음('떠올려 주실 수 있을까요', '들려주세요') — 띄어쓰기를 뺀 꼴. 바로 묻는 질문('무엇이었나요?')은 None."""
    m = _REQ_END_RE.search((question or "").strip())
    if not m:
        return None
    return re.sub(r"\s+", "", m.group(1) + m.group(2))


def ending_label(key: str | None) -> str:
    """끝맺음 키를 읽기 좋은 꼴로(프롬프트·보고용)."""
    k = key or ""
    k = re.sub(r"^(말씀해|이야기해|얘기해|설명해|떠올려|알려|짚어|꺼내|나눠|풀어|옮겨)(?=주)", r"\1 ", k)
    return k.replace("주실수있", "주실 수 있").replace("줄수있", "줄 수 있").replace("주시면", "주시면 ")


def tail_key(question: str | None) -> str:
    """질문의 끝 두 어절(문장부호 제외) — 사전 질문의 꼬리 변형을 가르는 데 쓴다. 청하는 꼴이면 그 끝맺음 키."""
    k = request_ending_key(question)
    if k:
        return k
    toks = re.sub(r"[.?!…~\"'”’]+$", "", (question or "").strip()).split()
    return " ".join(toks[-2:])


def ending_counts(questions: list[str] | None) -> dict:
    out: dict = {}
    for q in questions or []:
        k = request_ending_key(q)
        if k:
            out[k] = out.get(k, 0) + 1
    return out


# ── 두 질문 가운데 남길 것 · 요청형 질문 ─────────────────────────────────────
_ALT_Q_RE = re.compile(r"(는지|은지|인지|을지|나요|습니까|까요|어요)[,，?]?\s*(아니면|혹은|또는)\s")
_REQ_Q_TAIL_RE = re.compile(r"((?:는|은|인|을|였는|었는|했는|셨는)지)(?:를|가|도)?\s*(?:꼭\s*|한번\s*|조금\s*더\s*)?(여쭙고\s*싶습니다|여쭤보고\s*싶습니다|듣고\s*싶습니다|알고\s*싶습니다|"
                            r"여쭙고\s*싶어요|여쭤보고\s*싶어요|듣고\s*싶어요|알고\s*싶어요|여쭙니다|묻고\s*싶습니다)[.!…]*$")
# (2026-11-15 P13 중간 판정 5) '…를/…인지 묻겠습니다·여쭙겠습니다·짚겠습니다' 로 끝난 문장은 질문으로 세지 않는다(묻는 꼴로 바꾸지도 않는다) — 질문 보장 단계가 지우고 기본 질문을 붙인다
ANNOUNCE_ASK_RE = re.compile(r"(묻겠습니다|여쭙겠습니다|여쭤보겠습니다|짚겠습니다|짚어\s*보겠습니다|여쭤볼게요|물어볼게요|짚어\s*볼게요)[.!…]*$")


def is_announce_ask(sentence: str | None) -> bool:
    """묻겠다고 알리기만 하는 문장인가('이제 판단 기준을 묻겠습니다.', '…무엇이었는지 여쭙겠습니다.') — 질문이 아니다(질문 수에 넣지 않는다)."""
    return bool(ANNOUNCE_ASK_RE.search((sentence or "").strip()))


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


# ── (2026-11-15 P13d-3) 받는 말 허용 목록 ───────────────────────────────────────
#   탐침 턴·여는 턴의 받는 말(질문 앞 평서문)은 세 가지를 모두 갖출 때만 남긴다 — ① 끝맺음이 되짚는 꼴 ② 리더 직전 답과 겹치는 내용 낱말 2개 이상
#   ③ 12어절 이하. 아니면 그 문장만 지운다(다시 쓰지 않는다). 추측·평가 어미('…겠습니다', '…것으로 보입니다', '…싶습니다', '…들었습니다')는
#   끝맺음 목록에 없어 저절로 떨어진다. 영역 종료 요약·영역 시작의 고정 받기·다시 묻기의 사과 문장은 대상이 아니다(호출부가 가른다).
RECEIVE_ALLOWED_ENDINGS: dict[str, tuple[str, ...]] = {
    # 모든 코치 공통 — 받는 말은 합쇼체 코치도 '…군요/…네요' 꼴 그대로 둔다(말투 교정은 질문 문장에만 건다)
    "common": ("…셨군요", "…셨네요", "…다는/라는 말씀이군요", "…다는/라는 말씀이네요", "…다는/라는 말씀이시군요", "…다는/라는 말씀이시네요",
               "…거군요", "…거네요", "…거죠", "…것이군요", "…것이네요", "…것이죠", "…다고 하셨군요", "…다고 하셨네요"),
    # 합쇼체 코치(Jessica·Daniel)만 더 — 리더가 한 일을 그대로 되짚는 평서 꼴
    "formal": ("…셨습니다", "…다고 하셨습니다", "…다는/라는 말씀이십니다"),
}
_RECV_END_COMMON_RE = re.compile(r"(셨(군요|네요|지요|죠)|말씀이(시)?(군요|네요|지요|죠)|(거|것이)(군요|네요|죠|지요))[.!…]*$")      # (P14-1) '…셨지요/셨죠', '…말씀이지요' 추가
_RECV_END_FORMAL_RE = re.compile(r"(셨습니다|말씀이십니다)[.!…]*$")
RECEIVE_MIN_SHARED = 2             # 리더 직전 답과 겹치는 내용 낱말 수


def receive_shared_words(receive: str | None, user_text: str | None) -> list[str]:
    """받는 말의 내용 낱말 가운데 리더 직전 답에도 있는 것(앞 두 글자 기준, 흔한 낱말 제외)."""
    return question_overlap(receive, user_text)


# (2026-11-16 P14-1) 받는 말 전용 호출의 지시문에 넣는 끝맺음 꼴(어미만 — 따옴표로 묶은 완성 문장 꼴은 넣지 않는다)
RECEIVE_ENDING_HINT = "-셨군요, -셨네요, -셨지요, -다는 말씀이군요, -다는 말씀이네요, -신 거군요, -신 거네요"
# (2026-11-17 P14c-1) 끝맺음 갈래 → 지시문에 적는 꼴
RECEIVE_KEY_HINT: dict[str, str] = {"셨군요": "-셨군요", "셨네요": "-셨네요", "셨지요": "-셨지요", "말씀이군요": "-다는 말씀이군요", "말씀이네요": "-다는 말씀이네요",
                                    "말씀이지요": "-다는 말씀이지요", "거군요": "-신 거군요", "거네요": "-신 거네요", "거죠": "-신 거죠", "셨습니다": "-셨습니다",
                                    "말씀이십니다": "-말씀이십니다"}


def most_used_receive_ending(keys: list[str] | None) -> str | None:
    """(P14c-1) 이번 세션에서 가장 많이 쓴 받는 말 끝맺음 — 이번 턴에는 쓰지 않게 한다. 동률이면 가장 최근에 쓴 것. 쓴 적이 없으면 None."""
    ks = [k for k in (keys or []) if k]
    if not ks:
        return None
    cnt: dict[str, int] = {}
    for k in ks:
        cnt[k] = cnt.get(k, 0) + 1
    top = max(cnt.values())
    return next(k for k in reversed(ks) if cnt[k] == top)


def receive_streak(coach_texts_latest_first: list[str] | None) -> int:
    """(P14c-2) 직전 코치 턴부터 거슬러 받는 말(되짚는 끝맺음의 첫 평서문)이 이어진 턴 수."""
    from diag_project.services.output_guard import is_question as _iq_s, split_sentences as _ss_s
    n = 0
    for t in (coach_texts_latest_first or []):
        first = (_ss_s(t or "") or [""])[0].strip()
        if first and not _iq_s(first) and receive_ending_key(first):
            n += 1
        else:
            break
    return n


RECEIVE_STREAK_MAX = 3
_RECV_KEY_RES: tuple[tuple[str, re.Pattern], ...] = (
    ("말씀이군요", re.compile(r"말씀이(시)?군요[.!…]*$")), ("말씀이네요", re.compile(r"말씀이(시)?네요[.!…]*$")), ("말씀이지요", re.compile(r"말씀이(시)?(지요|죠)[.!…]*$")),
    ("셨군요", re.compile(r"셨군요[.!…]*$")), ("셨네요", re.compile(r"셨네요[.!…]*$")), ("셨지요", re.compile(r"셨(지요|죠)[.!…]*$")),
    ("거군요", re.compile(r"(거|것이)군요[.!…]*$")), ("거네요", re.compile(r"(거|것이)네요[.!…]*$")), ("거죠", re.compile(r"(거|것이)(죠|지요)[.!…]*$")),
    ("셨습니다", re.compile(r"셨습니다[.!…]*$")), ("말씀이십니다", re.compile(r"말씀이십니다[.!…]*$")),
)


def receive_ending_key(sentence: str | None) -> str | None:
    """받는 말의 끝맺음 갈래(셨군요·셨네요·셨지요·말씀이군요·말씀이네요·말씀이지요·거군요·거네요·거죠·셨습니다·말씀이십니다). 목록 밖이면 None."""
    t = (sentence or "").strip()
    return next((k for k, rx in _RECV_KEY_RES if rx.search(t)), None)


# ── (2026-11-16 P14b-1) 한 턴에 리더 말을 되짚는 것은 한 번 — 받아 둔 받는 말을 붙일지는 질문이 나온 뒤 정한다 ──────────
#   (가) A  질문이 리더 직전 답의 내용을 담은 앞 절로 시작한다(앞 절과 리더 답의 내용 낱말이 2개 이상 겹친다) → 붙이지 않는다
#   (나) B  질문이 10어절 미만이거나 '그/이/그때/그렇게'로 시작해 맥락이 없다 → 붙인다
#   (다) C  사례를 닫고 다음으로 넘어가는 턴 → 붙인다(호출자가 정한다)
#   (라) D  그 밖 → 직전 코치 턴에 받는 말이 나갔으면 붙이지 않고(D-), 아니면 붙인다(D+)
RECV_ATTACH_SHORT_EOJEOL = 10
_BARE_START_RE = re.compile(r"^(그|이|그때|그렇게|그런|그러면|그럼|그래서|그것|그걸|그건)(\s|$)")


def question_front_clause(question: str | None) -> str:
    """질문 문장에서 실제로 묻는 자리 앞에 놓인 절('…하셨을 때,', '…하신 뒤')."""
    q = (question or "").strip()
    part = first_probe_asking_part(q)
    return q[:len(q) - len(part)].strip() if part and part != q else ""


def receive_attach_rule(question: str | None, leader_answer: str | None, *, prev_had_receive: bool = False) -> tuple[bool, str]:
    """(붙이는가, 규칙: A | B | D+ | D-). 사례를 닫는 턴(C)은 호출자가 따로 정한다."""
    q = (question or "").strip()
    front = question_front_clause(q)
    if front and len(question_overlap(front, leader_answer)) >= 2:
        return False, "A"
    if len(q.split()) < RECV_ATTACH_SHORT_EOJEOL or _BARE_START_RE.search(q):
        return True, "B"
    return (False, "D-") if prev_had_receive else (True, "D+")


# ── (2026-11-16 P14b-3) 구체화 질문 확인 — 숫자·횟수·기간이나 실제 있었던 장면 하나를 청하는가 ─────────────────────
SPECIFY_MARKS = ("얼마나", "어느 정도", "몇 …", "예를 들어·예로", "한 가지", "하나만", "하나를", "구체적으로 어떤/무엇", "어떤 장면·한 장면·장면 하나",
                 "숫자·수치·횟수·기간", "며칠·몇 주·몇 달")
_SPECIFY_RE = re.compile(r"얼마나|어느\s*정도|몇\s?[가-힣]|예를\s*들|예로|한\s*가지|하나만|하나를|구체적으로\s*(어떤|무엇|뭐)|(어떤|한)\s*장면|장면\s*하나|숫자|수치|횟수|기간|며칠")
_SPECIFY_OFF_RE = re.compile(r"반응|받아들|어떻게\s*(보였|답했|말했)|왜\s|이유|까닭|기준|근거|어떤\s*(생각|마음)|우려|걱정")


def specify_question_ok(question: str | None) -> tuple[bool, str]:
    """(합격 여부, 사유: ok | no_question | meta | unfinished | off:<걸린 말> | no_mark). 묻는 자리(앞 절 제외)만 본다."""
    q = (question or "").strip()
    if not q:
        return False, "no_question"
    from diag_project.services.output_guard import split_sentences as _ss_sp
    if _FP_META_RE.search(q) or len([x for x in _ss_sp(q) if x.strip()]) >= 2:
        return False, "meta"
    if _FP_UNFINISHED_RE.search(q):
        return False, "unfinished"
    part = first_probe_asking_part(q)
    off = _SPECIFY_OFF_RE.search(part)
    if off:
        return False, f"off:{off.group(0).strip()}"
    if not _SPECIFY_RE.search(part):
        return False, "no_mark"
    return True, "ok"


# (2026-11-16 P14-3) 라포에서 리더가 코치에게 되묻거나 되받아친 말 — '그게 왜 궁금함?', '왜 물어?', '그건 왜요?'
_COUNTER_Q_RE = re.compile(r"왜\s*[^.!]{0,10}(궁금|물어|묻|여쭤|질문|알고\s*싶)|(그게|그건|그걸|이게|이건)\s*왜|왜요\s*\??\s*$|^\s*왜\s*\??\s*$|뭐가\s*궁금|뭘\s*(물어|묻)")


def is_counter_question(text: str | None) -> bool:
    return bool(_COUNTER_Q_RE.search(text or ""))


# (2026-11-16 P14-1) 호칭은 '리더님' — 출력의 '리더께서'·'리더가'를 '리더님께서'·'리더님이'로 바꾼다(11/16 운영 Lucas·p13g Daniel)
_LEADER_BARE_RE = re.compile(r"(?<![가-힣])리더(?=(께서|가)(?![가-힣]))")


def fix_leader_address(text: str | None) -> str:
    t = text or ""
    t = _LEADER_BARE_RE.sub("리더님", t)
    return t.replace("리더님가", "리더님이")


RECEIVE_KEEP_LONG_MAX = 20      # (P13g-4) 남은 질문이 8어절 미만일 때 길이만으로 떨어진 받는 말을 남기는 상한
SHORT_QUESTION_EOJEOL = 8


def receive_allowed(sentence: str | None, user_text: str | None, *, formal: bool = False, max_eojeol: int | None = None) -> tuple[bool, str]:
    """받는 말을 남겨도 되는가. (남김 여부, 사유: ok | ending | overlap | long). max_eojeol 을 주면 길이 상한만 그 값으로 본다."""
    s = (sentence or "").strip()
    if not (_RECV_END_COMMON_RE.search(s) or (formal and _RECV_END_FORMAL_RE.search(s))):
        return False, "ending"
    if len(s.split()) > (max_eojeol or RECEIVE_MAX_EOJEOL):
        return False, "long"
    if len(receive_shared_words(s, user_text)) < RECEIVE_MIN_SHARED:
        return False, "overlap"
    return True, "ok"


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


INCIDENT_CANDIDATE_MIN = 0.3


def incident_candidates(answer: str | None, closed_texts: dict | None) -> list:
    """(2026-11-14 P12e-4) '같은 사건' 판정의 예비 거름 — 답의 내용 낱말(앞 두 글자) 가운데 그 이야기에서 리더가 한 말과 겹치는 비율이 30% 이상인
    닫힌 이야기의 표지(많이 겹치는 순). 최종 판정은 슬롯 판정 호출이 한다(judge_slots 의 same_as). 낱말 겹침만으로 정하던 종전 방식은
    실세션 답에서 여유가 얇았다(같은 프로젝트의 다른 장면이 52% 겹침)."""
    a = {c[:2] for c in _content_chunks(answer or "") if len(c) >= 2}
    if len(a) < 3:
        return []
    out = []
    for tag, txt in (closed_texts or {}).items():
        e = {c[:2] for c in _content_chunks(txt or "") if len(c) >= 2}
        r = len(a & e) / len(a)
        if r >= INCIDENT_CANDIDATE_MIN:
            out.append((r, tag))
    return [t for _, t in sorted(out, key=lambda x: -x[0])]


def same_incident(answer: str | None, closed_texts: dict | None) -> object | None:
    """리더 답이 이번 영역에서 이미 닫힌 사례와 같은 사건이면 그 사례의 표지(사례 번호 또는 'sweepN'). 아니면 None.
    답의 내용 낱말(어간 앞 두 글자) 가운데 그 사례에서 리더가 한 말과 겹치는 비율이 60% 이상이고 5개 이상 겹치거나,
    '아까 말씀드린 그 일' 처럼 앞 이야기를 가리키면서 4개 이상·30% 이상 겹칠 때.
    (2026-11-13 P12b-3) 같은 프로젝트의 다른 사건(같은 개편 안의 예산 부족·양식 통일·일정 도구)은 같은 사건이 아니다 — 앞 이야기를 가리키는 말이 있어도
    겹치는 낱말이 프로젝트 이름 몇 개뿐이면(종전 기준 3개) 걸리지 않게 올렸다."""
    a = {c[:2] for c in _content_chunks(answer or "") if len(c) >= 2}
    if len(a) < 3:
        return None
    backref = bool(_BACKREF_RE.search(answer or ""))
    best, best_n = None, 0
    for tag, txt in (closed_texts or {}).items():
        e = {c[:2] for c in _content_chunks(txt or "") if len(c) >= 2}
        n = len(a & e)
        if ((n >= 5 and n / len(a) >= 0.6) or (backref and n >= 4 and n / len(a) >= 0.3)) and n > best_n:
            best, best_n = tag, n
    return best
