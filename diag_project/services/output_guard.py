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


def template_anchor(question: str, lead: str = "이 경험은 여기서 정리하겠습니다. 이제 다른 관점으로 여쭤볼게요.") -> str:
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
        base = re.sub(r"\s{2,}", " ", base).strip(" ,")
        return base, removed
    return " ".join(kept), removed


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
    t = re.sub(r"\s{2,}", " ", t).strip()
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
