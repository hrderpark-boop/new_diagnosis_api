"""코치 출력 후처리 가드 (2026-09-16, Daniel 재주행 검토 5건) — 순수 함수, LLM/DB 없음.

프롬프트 지시만으로는 지켜지지 않는 것들을 백엔드가 출력 단계에서 강제한다.
  1) ALIGN 이중 질문: 정의 제시가 질문으로 끝나면 그 문장을 지우고 템플릿 앵커를 붙인다.
  2) 전환 환각: 종료 권한이 없는 턴에서 "다음 챕터로 넘어가겠습니다" 류를 지운다.
  3) 앵커 턴 이름 노출·오타겟: 26개 하위역량 이름이 나오거나 이미 asked 된 하위역량의
     질문과 명사 어절이 겹치면 현재 타겟의 템플릿 앵커로 교체한다.
  4) 평가적 칭찬 금지(BEI 원칙 — 평가자가 원하는 신호를 주면 답을 포장한다): 6명 공통 금지
     목록. 포함 문장을 지운다. 인정은 사실 확인("그 결정을 내리셨군요")까지.
  5) 되받기 정리: 허용 턴 = [요약 한 줄] + [질문] / 금지 턴 = [대체 한 줄] + [질문]. 겹치지 않게.
호출 순서(diagnoses.py 8-i): 위반 감지 → 재생성 1회 → 남은 위반은 여기서 하드 교정.
"""
import re

from diag_project.services.style_tracker import (
    _BRIDGE_RE,
    _content_chunks, _first_sentence, echoes_user, is_recap_opening, starts_with_ne_recap,
)

# ── 문장 분리 ──
_SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+")


def split_sentences(text: str) -> list[str]:
    t = (text or "").strip()
    if not t:
        return []
    return [s for s in _SENT_SPLIT.split(t) if s.strip()]


def is_question(sentence: str) -> bool:
    s = (sentence or "").strip()
    return s.endswith("?") or bool(re.search(r"(까요|습니까|을까요|나요|시겠어요|시겠습니까|실까요)[.!?…]?$", s))


# ── 1) ALIGN: 꼬리 질문 제거 ──
def strip_trailing_question(text: str) -> tuple[str, int]:
    """마지막 문장(들)이 질문이면 지운다. 최소 한 문장은 남긴다. (결과, 지운 수)"""
    sents = split_sentences(text)
    removed = 0
    while len(sents) > 1 and is_question(sents[-1]):
        sents.pop()
        removed += 1
    if removed == 0:
        return text, 0
    # 원문의 문단 구조를 최대한 살린다: 지운 문장을 원문 끝에서 걷어낸다
    out = text.rstrip()
    for _ in range(removed):
        m = list(_SENT_SPLIT.finditer(out))
        if m:
            out = out[: m[-1].start()].rstrip()
        else:
            break
    return out, removed


# ── 2) 전환 환각 ──
_TRANSITION_RE = re.compile(
    r"(다음\s*(챕터|영역|단계|주제)(로|으로)?\s*(넘어|이어|가|이동)|넘어가겠습니다|넘어가 보겠습니다|"
    r"이어가겠습니다|이어가 보겠습니다|(영역|챕터)(을|를|은|는)?\s*(마무리|정리|마치)|"
    r"충분히 (들었|여쭤|나눴|이야기)|여기서 (마무리|정리|매듭)|다음 (영역|챕터)(에서|으로) (뵙|만나))"
)
TRANSITION_ALLOWED_INSTRUCTIONS = frozenset({
    "CHAPTER_READY_TO_END", "CHAPTER_CONTINUE_CONFIRMED", "MAX_TURNS_REACHED",
    "USER_REQUESTS_PAUSE", "CHAPTER_NO_YIELD_ULTIMATUM", "ABORT_CONFIRM", "ABORT_DISENGAGED",
})


def has_transition_claim(text: str) -> bool:
    return bool(_TRANSITION_RE.search(text or ""))


def strip_transition_sentences(text: str) -> tuple[str, int]:
    """전환 선언 문장을 지운다. 질문이 남지 않으면 원문 유지(호출자가 폴백 판단)."""
    sents = split_sentences(text)
    kept = [s for s in sents if not _TRANSITION_RE.search(s)]
    removed = len(sents) - len(kept)
    if removed == 0 or not kept:
        return text, 0
    return " ".join(kept), removed


# ── 3) 앵커 턴: 하위역량 이름 노출 · 오타겟 ──
def name_variants(names: list[str]) -> list[str]:
    """'변화관리(변화지향)' → ['변화관리(변화지향)', '변화관리', '변화지향'] 등 괄호 제거 변형."""
    out: list[str] = []
    for n in names or []:
        n = (n or "").strip()
        if not n:
            continue
        out.append(n)
        base = re.sub(r"\s*\([^)]*\)", "", n).strip()
        if base and base != n:
            out.append(base)
        for inner in re.findall(r"\(([^)]*)\)", n):
            inner = inner.strip()
            if len(inner) >= 2:
                out.append(inner)
    # 길이 긴 것부터(부분 문자열 중복 방지는 호출자가 any 로 보므로 순서만)
    return sorted(set(out), key=len, reverse=True)


def find_sub_names(text: str, names: list[str]) -> list[str]:
    """출력에 포함된 하위역량 이름(변형 포함). 2자 이하 변형은 오탐 방지로 제외."""
    t = text or ""
    return [v for v in name_variants(names) if len(v) >= 3 and v in t]


def off_target_overlap(text: str, asked_questions: list[str], min_hits: int = 3) -> tuple[bool, str]:
    """이미 asked 된 하위역량의 템플릿 질문과 명사 어절이 min_hits 개 이상 겹치면 오타겟.

    유사도는 단순 명사 어절 겹침(style_tracker._content_chunks)으로 판정한다.
    """
    q_sents = [s for s in split_sentences(text) if is_question(s)] or [text or ""]
    mine = set()
    for s in q_sents:
        mine |= set(_content_chunks(s))
    best = ""
    for q in asked_questions or []:
        hits = mine & set(_content_chunks(q))
        if len(hits) >= min_hits:
            return True, q
        if not best:
            best = q
    return False, ""


def template_anchor(question: str, lead: str = "다른 이야기를 하나 여쭤볼게요.") -> str:
    return f"{lead} {question}".strip()


# ── 4) 평가적 칭찬 금지 (6명 공통) ──
BANNED_PRAISE = [
    "훌륭한", "훌륭하", "매우 인상 깊", "인상 깊", "인상적", "깊은 통찰", "통찰력", "참으로 의미 있",
    "의미 있는 성과", "깊이 다가옵니다", "깊이 다가오", "본질을 정확히 짚", "정확히 짚어주셨",
    "탁월", "뛰어난", "뛰어나", "감탄", "대단하", "대단한", "존경", "모범적", "귀감", "완벽하",
    "놀라운", "놀랍", "역량이 돋보", "돋보입니다", "돋보이", "리더십이 빛", "빛나는", "귀한 경험",
    "소중한 경험", "값진", "멋진", "멋지", "훌륭", "깊이 공감합니다", "전적으로 공감",
    # 2026-09-17 보강(마무리 총평에서 재발): 인상적·돋보·선명하게 그려지는 등 평가적 총평
    "돋보", "인상적", "선명하게 그려", "그려지는 듯", "기준이 선명", "면모", "리더십이 느껴", "역량이 느껴",
    "저력", "내공", "진정한 리더", "리더로서의 자질",
]
_PRAISE_RE = re.compile("|".join(re.escape(p) for p in sorted(set(BANNED_PRAISE), key=len, reverse=True)))


def find_praise(text: str) -> list[str]:
    return sorted(set(m.group(0) for m in _PRAISE_RE.finditer(text or "")))


def strip_praise(text: str) -> tuple[str, int]:
    """금지 표현이 든 문장을 지운다. 질문만 남거나 전부 지워지면 마지막 질문 문장은 보존."""
    sents = split_sentences(text)
    if not sents:
        return text, 0
    kept = [s for s in sents if not _PRAISE_RE.search(s)]
    removed = len(sents) - len(kept)
    if removed == 0:
        return text, 0
    if not kept:
        # 전부 칭찬이면 질문 문장만이라도 칭찬 구절을 걷어내 남긴다
        qs = [s for s in sents if is_question(s)]
        base = qs[-1] if qs else sents[-1]
        base = _PRAISE_RE.sub("", base)
        base = re.sub(r"[ \t]{2,}", " ", base).strip(" ,")
        return base, removed
    # (2026-09-29) 문장을 제자리에서 지운다 — 다시 이어 붙이면 문단·목록 줄바꿈이 사라진다(ALIGN 서식 파손)
    out = text
    for x in sents:
        if _PRAISE_RE.search(x):
            out = out.replace(x, "", 1)
    out = re.sub(r"[ \t]{2,}", " ", out)
    out = re.sub(r"[ \t]+\n", "\n", out)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out, removed


# ── 5) (2026-09-22 폐지) 되받기 리드 삭제 trim_lead_sentences — 자른 문장이 어색하다. 되받기는 프롬프트 한 줄이 맡는다. ──


def first_lead(text: str) -> str:
    return _first_sentence(text)


# ── (2026-09-22 폐지) 연결 한 절 템플릿(bridge_keyword·template_anchor_bridged) — 인용 어절 오류("'일들이'와도")가 잦았고,
#    LLM 의 되받기 한 문장이 다리 역할을 한다. 폴백은 template_anchor(질문)만 쓴다. ──


def cap_lead_sentences(text: str) -> tuple[str, int]:
    """첫 질문 앞의 리드를 최대 1문장으로(2026-09-22 결정). 2문장 이상이면 첫 문장만 남긴다.
    첫 질문부터는 절대 건드리지 않는다(postprocess_pipeline 원칙). 질문이 없는 출력은 그대로. (결과, 지운 문장 수)"""
    sents = split_sentences(text)
    qi = next((i for i, s in enumerate(sents) if is_question(s)), None)
    if qi is None or qi <= 1:
        return text, 0
    return " ".join([sents[0]] + sents[qi:]).strip(), qi - 1


# ── Result 탐침 문장 반복(2026-09-17): 같은 문장은 한 챕터에 한 번 ──
_GENERIC_RESULT_RE = re.compile(r"그렇게\s*(하니|하니까|해서|하셔서|하시니)\s*어떻게\s*(됐|되었|되셨)")


def norm_sentence(s: str) -> str:
    return re.sub(r"[\s.,!?…'\"()]", "", s or "")


def find_repeated_result_probe(text: str, used_sentences: list[str]) -> str | None:
    """출력의 문장이 (a) 상투형 '그렇게 하니 어떻게 됐습니까' 이거나 (b) 이 챕터에서 이미 쓴 결과 질문과
    같으면 그 문장을 돌려준다(교체 대상). 없으면 None."""
    used = {norm_sentence(u) for u in (used_sentences or []) if u}
    for sent in split_sentences(text):
        if not is_question(sent):
            continue
        if _GENERIC_RESULT_RE.search(sent) or norm_sentence(sent) in used:
            return sent
    return None


_JOSA_AFTER_BUBUN = {"를": "을", "가": "이", "는": "은", "와": "과", "나": "이나", "로": "으로", "란": "이란", "라는": "이라는"}


def strip_sub_name_mentions(text: str, names: list[str]) -> tuple[str, int]:
    """비앵커 프로브 턴의 하위역량 이름 노출을 걷어낸다(2026-09-18, 09-21 보강).
    (a) "'변화관리'와 관련하여, " / "변화관리 측면에서 " 처럼 관련 구절이 따르면 구절째 삭제.
    (b) 따옴표로 이름 전체만 감싼 "'팀워크'이나 장기 성과" 는 '그 부분'으로 치환(조사는 받침에 맞춰 교정 — "팀의 이나" 같은 파손 방지).
    긴 인용구 안의 부분 일치("'프로세스 표준화 작업이 정착'되는")는 건드리지 않는다 — 걷어내면 따옴표가 깨진다."""
    t = text or ""
    n = 0
    _REL = r"(관련하여|관련해서|관련해|측면에서|부분에서|이야기와|말씀과)"
    _JOSA = r"(이나|나|이라는|라는|이란|란|으로|로|과|와|에|의|을|를|은|는|도|이|가)?"
    for v in name_variants(names):
        if len(v) < 3 or v not in t:
            continue
        quoted_rel = re.compile(r"['\"“‘]" + re.escape(v) + r"['\"”’]\s*" + _JOSA + r"\s*" + _REL + r"[,\s]*")
        bare_rel = re.compile(re.escape(v) + r"\s*" + _JOSA + r"\s*" + _REL + r"[,\s]*")
        for pat in (quoted_rel, bare_rel):
            t2, k = pat.subn("", t)
            if k:
                n += k
                t = t2
        quoted = re.compile(r"['\"“‘]" + re.escape(v) + r"['\"”’]" + _JOSA)

        def _rep(m: re.Match) -> str:
            j = m.group(1) or ""
            return "그 부분" + _JOSA_AFTER_BUBUN.get(j, j)
        t2, k = quoted.subn(_rep, t)
        if k:
            n += k
            t = t2
    t = re.sub(r"[ \t]{2,}", " ", t).strip()
    return t, n


_Q_NOISE_RE = re.compile(r"(방금|앞서|아까|조금 전)?\s*(말씀하신|말씀해 ?주신|언급하신)\s*['\"“‘][^'\"”’]{1,10}['\"”’]\s*(과도|와도|과|와)?\s*(이어지는데요|이어지는 부분입니다만|이어서|이어지는데)?[,\s]*"
                          r"|혹시|혹|리더님께서는|리더님은|리더님|그렇다면|그럼|그 결에서 이어 여쭙니다만|그러한 관점에서|최근에|근래에|요즘")


def _question_core(sentence: str) -> str:
    return norm_sentence(_Q_NOISE_RE.sub("", sentence or ""))


def same_question_as_previous(text: str, prev_coach_text: str | None) -> str | None:
    """이번 출력의 질문 문장이 직전 코치 턴의 질문과 (연결 절·'혹시'·호칭을 뺀 뒤) 같으면 그 문장을 돌려준다(2026-09-21).
    사람관리 리플레이 21·22턴: 템플릿 앵커 뒤 LLM 이 같은 앵커를 '혹시'만 바꿔 되물었다."""
    if not prev_coach_text:
        return None
    prev = {_question_core(q) for q in split_sentences(prev_coach_text) if is_question(q)}
    prev = {q for q in prev if len(q) >= 8}
    for q in split_sentences(text or ""):
        if is_question(q) and _question_core(q) in prev:
            return q
    return None


def has_question(text: str) -> bool:
    return any(is_question(x) for x in split_sentences(text))


# ── 2026-09-29 자기관리 재주행: 지시어 허공·억지 다리·정의→앵커 다리 ──
_NP_STOP = {"리더", "자신", "저", "제", "저희", "우리", "팀원", "팀원들", "아무도", "다들", "요즘", "그냥", "정말", "진짜",
            "사실", "원래", "오히려", "모두", "다", "뭐", "그거", "이거", "그게", "이게", "그런것", "그런거", "경우", "때"}
# 감정·상태 형용사 어간 — '서운했죠'의 '서운'은 사건 명사가 아니다(결과 질문 대상 X)
_NP_EMOTION = {"서운", "답답", "속상", "섭섭", "힘들", "불편", "미안", "당황", "억울", "뿌듯", "행복", "피곤", "귀찮", "심란", "허탈", "민망"}
# 가벼운 목적어('신경을 쓰다', '생각을 하다') — 핵심 명사가 아니다
_NP_LIGHT = {"신경", "생각", "말", "얘기", "일", "것", "거", "마음", "노력"}
_NP_VERB_NOUN_RE = re.compile(r"^(.{2,6}?)(하자고|하자|하고|해서|했는데|했고|했어요|했죠|하는|하기|하려고|하셨|했|하면)$")
_NP_OBJ_RE = re.compile(r"^(.{2,8}?)(을|를)$")
_NP_SUBJ_RE = re.compile(r"^(.{2,8}?)(이|가|은|는)$")


def _np_tokens(text: str) -> list[str]:
    return [t for t in re.split(r"[\s,.!?…~\"'‘’“”()\[\]/·*-]+", text or "") if t]


def key_noun_phrase(user_text: str | None) -> str:
    """직전 사용자 발화의 핵심 명사구 하나(2~12자). '회식하자고' → '회식', '일관성이 가장 중요' → '일관성'.
    결과 질문·정의 다리에 넣는 용도 — 대명사만으로 가리키지 않게."""
    toks = _np_tokens(user_text)
    if not toks:
        return ""
    # 1) '… 가장 중요/핵심' 앞의 주어 명사 (정의 답변)
    for i, t in enumerate(toks):
        if t.startswith(("중요", "핵심")) and i > 0:
            j = i - 1
            if toks[j] == "가장" and j > 0:
                j -= 1
            m = _NP_SUBJ_RE.match(toks[j])
            if m and m.group(1) not in _NP_STOP:
                return m.group(1)
    # 2) 목적어(을/를) — 마지막 것, 앞 어절이 명사 수식이면 붙인다
    objs = []
    for i, t in enumerate(toks):
        m = _NP_OBJ_RE.match(t)
        if m and m.group(1) not in _NP_STOP and m.group(1) not in _NP_LIGHT:
            np_ = m.group(1)
            if i > 0 and len(toks[i - 1]) <= 4 and not re.search(r"(다|요|고|서|며|면|는|은|을|를|이|가|에|게|도|만|죠|니)$", toks[i - 1]) \
                    and toks[i - 1] not in _NP_STOP:
                np_ = f"{toks[i - 1]} {np_}"
            objs.append(np_)
    if objs:
        return objs[-1][:12]
    # 3) 명사+하다 동사('회식하자고')
    for t in toks:
        m = _NP_VERB_NOUN_RE.match(t)
        if m and m.group(1) not in _NP_STOP and m.group(1) not in _NP_EMOTION:
            return m.group(1)
    # 4) 주어·주제(이/가/은/는)
    for t in toks:
        m = _NP_SUBJ_RE.match(t)
        if m and m.group(1) not in _NP_STOP and not re.search(r"(하|되|있|없|같)$", m.group(1)):
            return m.group(1)
    return ""


def result_fallback_question(user_text: str | None, prev_user_text: str | None = None) -> str:
    """결과 질문 폴백 — 직전 발화의 명사구를 채운다(없으면 그 앞 발화 — 같은 사건의 서술). 대명사만으로 가리키지 않는다."""
    np_ = key_noun_phrase(user_text) or key_noun_phrase(prev_user_text)
    if np_:
        return f"'{np_}' 이후로는 어떻게 됐습니까?"
    return "방금 말씀하신 일 이후로는 어떻게 됐습니까?"


_DEMONSTRATIVE_RE = re.compile(r"(그것|그걸|그게|그거|그럴\s*(때|땐)|그런\s*(때|땐)|그러실\s*(때|땐)|그렇게\s*하(니|시니|셨을\s*(때|땐))|그때는|그땐|그\s*일)")


_GENERIC_Q = {"어떻게", "어떠셨", "어떠셨습니까", "어땠", "어땠어요", "어떠셨어요", "받아들였", "받아들였나요", "하셨", "하셨습니까",
              "느끼셨", "느끼셨습니까", "드셨", "되셨", "있으셨", "있으셨을까요", "계셨", "리더님", "리더님께서는", "리더님께서",
              "혹시", "그때", "그때는", "그것", "그걸", "그게", "그거", "그럴", "그런", "그렇게", "팀원", "팀원들", "생각", "마음",
              "어떤", "무엇", "무엇을", "보셨", "하시니", "하시나요", "되었", "됐", "됐습니까", "했", "했습니까"}


def has_bare_demonstrative(question: str, user_text: str | None) -> bool:
    """질문이 대명사로만 대상을 가리키는가 — 인용('…')도, 직전 사용자 발화의 내용 어절도, 문장 자체의 구체 어절(2개 이상)도 없이
    '그것/그럴 때'만 있다. ('크게 실패한 뒤 … 그때는'처럼 문장 안에 대상이 있으면 대명사 단독이 아니다.)"""
    if not _DEMONSTRATIVE_RE.search(question or ""):
        return False
    if re.search(r"['‘\"“][^'’\"”]{2,}['’\"”]", question):
        return False
    user_chunks = {c for c in _content_chunks(user_text or "") if len(c) >= 2}
    q_chunks = [c for c in _content_chunks(question) if len(c) >= 2]
    if user_chunks & set(q_chunks):
        return False
    own_specific = [c for c in q_chunks if c not in _GENERIC_Q and not _DEMONSTRATIVE_RE.fullmatch(c)]
    return len(own_specific) < 2


def bare_demonstrative_questions(text: str, user_text: str | None) -> list[str]:
    return [s for s in split_sentences(text or "") if is_question(s) and has_bare_demonstrative(s, user_text)]


def _josa(word: str, with_final: str, without_final: str) -> str:
    ch = (word or "")[-1:]
    if ch and "가" <= ch <= "힣" and (ord(ch) - 0xAC00) % 28:
        return with_final
    return without_final


# 정의 제시 → 첫 앵커 사이 기본 다리(페르소나별 3개). {kw} = 리더 정의의 핵심 단어.
ALIGN_BRIDGE_POOL = {
    "Daniel": ["'{kw}'{i_ga} 시험받았던 장면부터 여쭤보겠습니다.", "말씀하신 '{kw}'{eul_reul} 실제 장면에서 확인해 보고 싶습니다.",
               "'{kw}'{i_ga} 흔들릴 뻔했던 순간부터 들어보겠습니다."],
    "Ella": ["'{kw}'{i_ga} 시험받았던 장면부터 천천히 들어볼게요.", "말씀하신 '{kw}', 실제로 어떤 순간에 드러났는지 궁금해요.",
             "'{kw}'{eul_reul} 지켜내기 어려웠던 순간부터 여쭤볼게요."],
    "Jessica": ["'{kw}'{i_ga} 시험받은 장면부터 보겠습니다.", "'{kw}', 실제 장면으로 확인해 보죠.", "'{kw}'{i_ga} 흔들린 순간부터 짚어보겠습니다."],
    "Olivia": ["'{kw}'{eul_reul} 다른 각도에서 비춰볼 장면부터 여쭤볼게요.", "'{kw}'{i_ga} 시험받았던 순간을 함께 돌아보고 싶어요.",
               "말씀하신 '{kw}', 그게 드러난 한 장면부터 들어볼게요."],
    "Michael": ["'{kw}'{i_ga} 시험받았던 현장부터 바로 가 보겠습니다.", "'{kw}', 실제로 부딪혔던 장면부터 짚어보죠.",
                "'{kw}'{eul_reul} 지켜낸 순간부터 들어보겠습니다."],
    "Lucas": ["'{kw}'{i_ga} 시험받은 장면부터 보겠습니다.", "'{kw}', 실제 사례로 확인하겠습니다.", "'{kw}'{i_ga} 드러난 장면 하나부터요."],
}
_DEFAULT_BRIDGES = ["'{kw}'{i_ga} 시험받았던 장면부터 여쭤볼게요.", "말씀하신 '{kw}'{eul_reul} 실제 장면에서 확인해 보고 싶어요.",
                    "'{kw}'{i_ga} 흔들릴 뻔했던 순간부터 들어볼게요."]


_NO_KW_BRIDGES = ["이제 실제 장면에서부터 하나씩 여쭤볼게요.", "지금부터는 실제 있었던 장면으로 들어가 보겠습니다.",
                  "직접 겪으신 장면 하나에서 출발해 보겠습니다."]


def align_default_bridge(persona_name: str | None, definition_text: str | None, pos: int = 0) -> str:
    kw = key_noun_phrase(definition_text)
    if not kw:
        return _NO_KW_BRIDGES[pos % len(_NO_KW_BRIDGES)]
    key = (persona_name or "").split(" ")[0]
    pool = ALIGN_BRIDGE_POOL.get(key) or _DEFAULT_BRIDGES
    tpl = pool[pos % len(pool)]
    return tpl.format(kw=kw, i_ga=_josa(kw, "이", "가"), eul_reul=_josa(kw, "을", "를"))


def align_has_bridge(text: str) -> bool:
    """정의·목록 블록 뒤에 평서문 1문장 이상이 있는가(마지막 '· ' 목록 줄 이후)."""
    lines = (text or "").rstrip().split("\n")
    last_list = max((i for i, l in enumerate(lines) if l.strip().startswith("·")), default=None)
    tail = "\n".join(lines[last_list + 1:]) if last_list is not None else ""
    sents = [s for s in split_sentences(tail) if s.strip() and not s.strip().startswith("·")]
    return any(not is_question(s) for s in sents)


_FRAME_LEAD_RE = re.compile(r"^\s*(먼저 하나 여쭤볼게요\.|가볍게 시작해 볼게요\.|실제 있었던 일로 시작해 볼게요\.|바로 여쭤볼게요\.|"
                            r"이 영역은 이 질문부터요\.)\s*")


def strip_frame_lead(anchor: str) -> str:
    """앵커 프레임의 자체 리드('먼저 하나 여쭤볼게요.')를 뗀다 — 다리 문장과 이중 도입 방지."""
    return _FRAME_LEAD_RE.sub("", anchor or "", count=1)


def anchor_overlap(text: str, anchor_q: str) -> int:
    """출력 질문들과 이번 앵커 질문이 공유하는 내용 어절 수(2자 이상)."""
    qs = " ".join(x for x in split_sentences(text or "") if is_question(x))
    a = {c for c in _content_chunks(anchor_q or "") if len(c) >= 2}
    return len(a & set(_content_chunks(qs)))


ANCHOR_TRANSITIONS = ["다른 이야기를 하나 여쭤볼게요.", "이번엔 조금 다른 장면입니다."]


def followup_from_user(user_text: str | None) -> str:
    """대명사 단독 질문의 잔존 교체문(결과 강제 턴이 아닐 때) — 리더가 쓴 말을 받아 한 걸음 더 묻는다."""
    np_ = key_noun_phrase(user_text)
    if not np_:
        t = re.sub(r"\s+", " ", (user_text or "").strip())[:14].rstrip(" .,!?")
        np_ = t
    if not np_:
        return "방금 말씀하신 장면을 조금 더 구체적으로 들려주시겠어요?"
    return f"'{np_}'{_josa(np_, '이라고', '라고')} 하신 부분을 조금 더 구체적으로 들려주시겠어요?"


# 앵커 턴의 상투적 다리("그런 경험처럼,") — 주제가 이어지지 않는데 붙는 군말. 떼고 전환 문장으로.
_FILLER_BRIDGE_RE = re.compile(r"((그런|이런|그|이|방금 말씀하신|앞서 말씀하신)\s*(경험|말씀|이야기|사례)(처럼|과\s*같이|의\s*결에서|에\s*이어)|^(이처럼|그처럼))\s*,?\s*(혹시\s*)?")


def strip_filler_bridge(text: str) -> tuple[str, bool]:
    """앵커 질문 앞의 '그런 경험처럼,' 류 군말 다리를 떼고, 질문 앞에 전환 문장이 없으면 붙인다."""
    sents = split_sentences(text or "")
    out, hit = [], False
    for x in sents:
        if is_question(x) and _FILLER_BRIDGE_RE.search(x):
            y = _FILLER_BRIDGE_RE.sub("", x, count=1).strip()
            if y:
                out.append(y); hit = True
                continue
        out.append(x)
    if not hit:
        return text, False
    qi = next((i for i, x in enumerate(out) if is_question(x)), None)
    if qi is not None and not any(t in " ".join(out[:qi]) for t in ("다른 이야기", "다른 장면", "조금 다른")):
        out = out[:qi] + ["다른 이야기를 하나 여쭤볼게요."] + out[qi:]
        if qi >= 1:
            out = [out[0]] + out[qi:]   # 리드 1문장 + 전환 + 질문
    return " ".join(out).strip(), True


def ensure_align_list(text: str, sub_names: list[str]) -> tuple[str, bool]:
    """ALIGN 출력에 하위역량 목록('· ' 줄)이 없으면 첫 문단 뒤에 넣는다(목록은 competencies 값 그대로)."""
    if not sub_names or any(l.strip().startswith("·") for l in (text or "").split("\n")):
        return text, False
    block = "\n".join(f"· {n}" for n in sub_names)
    paras = (text or "").rstrip().split("\n\n")
    head = paras[:2] if len(paras) >= 2 else paras
    tail = paras[2:] if len(paras) >= 2 else []
    return "\n\n".join(head + [block] + tail).strip(), True


def drop_question_sentences(text: str) -> tuple[str, int]:
    """본문의 물음표 문장을 지운다 — 줄 단위로 처리해 목록·문단 줄바꿈을 보존. ALIGN 본문 — 질문은 뒤에 붙는 앵커 하나뿐."""
    n = 0
    lines = []
    for line in (text or "").split("\n"):
        sents = split_sentences(line)
        kept = [x for x in sents if not is_question(x)]
        n += len(sents) - len(kept)
        if sents and not kept:
            continue          # 질문뿐인 줄은 통째로 뺀다
        lines.append(" ".join(kept) if len(kept) != len(sents) else line)
    out = "\n".join(lines)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return out, n
