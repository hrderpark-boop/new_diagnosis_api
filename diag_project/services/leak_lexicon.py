"""내부 어휘 누설 사전 (2026-10-28 P0-2) — 프롬프트 템플릿에서 자동 추출. 수동 목록 없음.

출력 가드(routes/diagnoses 8-i)와 재생 린트(tools/transcript_lint.py)가 **같은 사전**을 쓴다.
누설 = 코치 출력에 프롬프트 템플릿(layer1~3·instruction 이름·페르소나 가이드·로그 포맷)의 내부 어휘가 나오는 것
(되받기·다리·탐침·턴·사건·STAR·태그·지시·가이드·반례·오버라이드·instruction·probe …) + 상태 보고문("충분히 들었습니다" 류).

추출 방식(요약)
  - 소스: prompts/phase3a/layer1_system.py · layer2_chapters.py · layer3_state.py, services/instruction_decider.py(instruction 이름 상수),
    services/persona_voice.py. 보조 소스: routes/diagnoses.py 의 로그 포맷 문자열(코치가 절대 말하지 않는 문자열).
  - 문자열 리터럴(ast)만 읽는다. 한글 어절은 조사를 떼어 명사 후보로, 영문은 3자 이상 식별어·대문자 스네이크.
  - 제외: 코치가 말하도록 설계된 어휘(competencies 의 역량·하위역량 이름·정의·앵커·주제구, intro_messages·time_greeting 의 고정 문장,
    템플릿 안의 따옴표 예문)와 기능어·서술어 어미 종결 어절.
  - 탐지 시 리더가 그 시점까지 쓴 어절을 되받은 것은 누설이 아니다(설계된 되받기).
"""
from __future__ import annotations

import ast
import re
from collections import Counter, defaultdict
from functools import lru_cache
from pathlib import Path

from diag_project.data.coaches_persona import COACHES_PERSONA
from diag_project.data.competencies import (
    COMPETENCY_FRAMEWORK,
    SUBCOMPETENCY_ANCHOR_QUESTIONS,
    SUBCOMPETENCY_TOPIC_PHRASE,
)
from diag_project.services.output_guard import find_state_leak, is_question, split_sentences

ROOT = Path(__file__).resolve().parents[2]

LEAK_SOURCES = [
    ROOT / "diag_project/prompts/phase3a/layer1_system.py",
    ROOT / "diag_project/prompts/phase3a/layer2_chapters.py",
    ROOT / "diag_project/prompts/phase3a/layer3_state.py",
    ROOT / "diag_project/services/instruction_decider.py",
    ROOT / "diag_project/services/persona_voice.py",
]
# 보조 소스: 로그 포맷 문자열만 읽는다(코치 발화가 아님이 구조적으로 보장되는 문자열).
LOG_SOURCES = [ROOT / "diag_project/routes/diagnoses.py"]
COACH_SPEECH_SOURCES = [
    ROOT / "diag_project/services/intro_messages.py",
    ROOT / "diag_project/services/time_greeting.py",
    ROOT / "diag_project/data/ladder_questions.py",   # 사다리 질문도 코치 발화('반복 작업을 자동으로' 가 누설로 잡혔다)
]

MIN_COUNT = 3           # 주 소스 합산 최소 빈도
MIN_FILES = 2           # 또는 출현 파일 수
MIN_COUNT_1CHAR = 5     # 1자 어절 최소 빈도(+단독 출현 2회)

_TOKEN_SPLIT_RE = re.compile(r"[\s\.,!?…:;()\[\]{}'\"“”‘’·/—–\-→⇒*#_=%<>|~`+\\^$@&※①②③④⑤⑥⑦⑧⑨⑩❌✅⭐★☆→]+")
_HANGUL_RE = re.compile(r"^[가-힣]+$")
_ENGLISH_RE = re.compile(r"^[A-Za-z][A-Za-z_]{2,}$")
_UPPER_SNAKE_RE = re.compile(r"^[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+$")
_PLACEHOLDER_RE = re.compile(r"\{[^{}]*\}")
_LOG_FORMAT_RE = re.compile(r"%[sdrf]")

# 조사 — 긴 것부터. 3자 이상 어절에서만 1자 조사를 뗀다(회의→회 같은 훼손 방지).
_JOSA_LONG = ("에서는", "으로는", "에게는", "까지는", "부터는", "이라는", "이라고", "에서도", "으로도", "이란",
              "에서", "으로", "에게", "께서", "까지", "부터", "처럼", "보다", "이나", "라는", "라고", "마다", "조차", "마저", "밖에")
_JOSA_SHORT = ("은", "는", "이", "가", "을", "를", "의", "에", "와", "과", "도", "만", "로", "들")
_ALL_JOSA = tuple(sorted(set(_JOSA_LONG) | set(_JOSA_SHORT), key=len, reverse=True))

# 폐쇄류 기능어(대명사·지시어·부사·수사·호칭·감탄사). 누설 어휘가 아니라 '거르는' 목록이다.
_FUNCTION_WORDS = {
    "그", "이", "저", "것", "수", "때", "더", "안", "못", "또", "잘", "꼭", "좀", "다", "왜", "뭐", "네", "예", "아니", "응",
    "거", "게", "건", "걸", "곳", "데", "등", "및", "즉", "약", "한", "두", "세", "네", "몇", "번", "개", "명", "분", "쪽", "뒤", "앞",
    "위", "아래", "안", "밖", "전", "후", "중", "내", "외", "식", "별", "당", "씩", "간", "말", "일", "점",
    "그것", "그게", "그걸", "그런", "그럼", "그때", "그리고", "그래서", "그런데", "그러나", "하지만", "또한", "또는", "혹은", "즉",
    "이것", "이게", "이런", "이번", "이제", "이미", "아직", "다시", "먼저", "바로", "거의", "매우", "아주", "너무", "정말", "진짜",
    "항상", "늘", "가장", "제일", "특히", "주로", "대개", "보통", "흔히", "자주", "가끔", "함께", "같이", "서로", "모두", "전부",
    "여기", "거기", "저기", "지금", "오늘", "어제", "내일", "요즘", "최근", "당시", "처음", "마지막", "하나", "둘", "셋", "모든",
    "어떤", "어느", "무슨", "누구", "언제", "어디", "어떻게", "얼마나", "무엇", "누가",
    "리더", "리더님", "코치", "님", "저희", "우리", "제가", "저는", "당신", "자신", "본인", "사람", "사람들",
    "있다", "없다", "하다", "되다", "이다", "아니다", "있는", "없는", "하는", "되는", "않는", "않고", "않는다", "않다",
    "경우", "정도", "이상", "이하", "이내", "이후", "이전", "사이", "동안", "통해", "위해", "대해", "대한", "따라", "관련",
    "하나만", "하나씩", "한번", "한 번", "두 번", "여러", "각", "매", "총", "약간", "조금", "많이", "크게", "작게", "짧게", "길게",
}
# 서술어·부사 어미로 끝나는 어절은 명사 후보에서 제외.
_PREDICATE_TAIL_RE = re.compile(r"(다|요|죠|까|니|며|든|야|해|돼|봐|줘|게|히|시오|세요|는데|지만|면서|려고|도록|니까|라서|어서|아서|"
                                r"는지|은지|ㄴ지|다면|라면|으면|하면|었|았|셨|겠)$")
_ENGLISH_STOP = {"the", "and", "for", "not", "with", "this", "that", "from", "are", "was", "were", "you", "your", "but",
                 "all", "any", "can", "has", "have", "into", "its", "may", "one", "two", "use", "when", "who", "why",
                 "none", "true", "false", "str", "int", "dict", "list", "bool", "self", "return", "def", "import"}

# ── 상태 보고문(백엔드 상태를 리더에게 말하는 문장) 패턴 ───────────────────────
STATE_STEMS = ("요약", "마무리", "충족", "모였", "모인", "모이", "충분히", "들었", "정리하겠")
_STATE_REPORT_RE = re.compile(
    r"(충분히\s*(들었|들은|여쭤|여쭸|모였|모인|확보)"
    r"|(사례|사건|이야기|경험|장면)(를|가|는|도|은|이|들|들을|들이|들은)?\s*(\S+\s+){0,2}?(들려주셨|모였|모인|모이|충분|확보|수집)"
    r"|여기서\s*마무리|여기까지\s*(하|마무리|듣)|(이|해당|현재)\s*영역(은|는|도)?\s*(\S+\s+){0,2}?(마무리|정리|끝|충분)"
    r"|마무리(하겠|할게요|하겠습니다|짓겠|하고\s*넘어|하죠|합시다)"
    r"|(들은|들려주신|말씀하신|이야기를|사례를|내용을)\s*(\S+\s+){0,2}?정리(하겠|해\s*보겠|해\s*드리겠|하고\s*넘어)"
    r"|조건(이|은|도|을)\s*(\S+\s+)?충족|충족(되|됐|했|됩|이\s*되)"
    r"|요약(하자면|하면|하겠|해\s*보면|해보면|해\s*드리|드리)"
    r"|(지금까지|여기까지|이쯤에서|이\s*영역|사례|사건)(\S*)\s*(\S+\s+){0,2}?정리(하겠|할게|해\s*보겠|하면|하자면|하고)"
    r"|정리하겠습니다"
    # (2026-10-29 s30 Daniel 전환 턴) 코치 자기 지칭·질문 예고 — "Daniel 코치로서 자기관리 영역의 첫 질문을 드리겠습니다."
    r"|코치로서|(첫|다음|마지막)\s*질문(을|부터)?\s*(드리|하|여쭙)겠)"
)

# ── 잘림·반복·탐침·어미 패턴 ───────────────────────────────────────────────────

def _raw_tokens(text: str) -> list[str]:
    text = _PLACEHOLDER_RE.sub(" ", text or "")
    return [t for t in _TOKEN_SPLIT_RE.split(text) if t]


def strip_josa(token: str) -> str:
    """어절 끝의 조사를 뗀다. 긴 조사는 2자 이상 어간이 남을 때, 1자 조사는 3자 이상 어절에서만."""
    for j in _JOSA_LONG:
        if token.endswith(j) and len(token) - len(j) >= 2:
            return token[: -len(j)]
    if len(token) >= 3:
        for j in _JOSA_SHORT:
            if token.endswith(j):
                return token[:-1]
    return token


def korean_candidates(token: str) -> list[str]:
    """한 어절에서 명사 후보(원형·조사 제거형)를 낸다. 2자 어절은 1자 어간도 후보로 낸다(턴은→턴)."""
    if not _HANGUL_RE.match(token):
        return []
    out = [token]
    stripped = strip_josa(token)
    if stripped != token:
        out.append(stripped)
    elif len(token) == 2 and token[1] in "".join(_JOSA_SHORT):
        out.append(token[0])
    return out


_TWO_CHAR_PREDICATE_TAILS = "는은던을를지고어아"   # 묻는·쓴·쓰지·말고 — 2자 어절이 이 글자로 끝나면 거의 서술어 어간
_DERIVED_SUFFIX_RE = re.compile(r"(적|적으로|적인|적이)$")


def _is_function_word(w: str) -> bool:
    if w in _FUNCTION_WORDS or w in _ALL_JOSA or w in ("류", "등", "및", "외"):
        return True
    if len(w) >= 2 and _PREDICATE_TAIL_RE.search(w):
        return True
    if len(w) == 2 and w[-1] in _TWO_CHAR_PREDICATE_TAILS:
        return True
    if len(w) >= 3 and _DERIVED_SUFFIX_RE.search(w):
        return True
    return False


# ══════════════════════════════════════════════════════════════════════════════
# 2. 소스 파일에서 문자열 추출
# ══════════════════════════════════════════════════════════════════════════════
def string_literals(path: Path, *, include_docstrings: bool = True) -> list[str]:
    """파일의 문자열 리터럴(f-string 조각 포함). include_docstrings=False 면 단독 문자열식(docstring)을 뺀다."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return []
    skip: set[int] = set()
    if not include_docstrings:
        for node in ast.walk(tree):
            if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                skip.add(id(node.value))
    out: list[str] = []
    in_fstring: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.JoinedStr):
            parts = []
            for v in node.values:
                if isinstance(v, ast.Constant) and isinstance(v.value, str):
                    parts.append(v.value)
                    in_fstring.add(id(v))
                else:
                    parts.append(" ")
            out.append("".join(parts))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in skip and id(node) not in in_fstring:
            out.append(node.value)
    return out


# 템플릿 안의 따옴표 예문('언제였을까요?', '그렇게 생각하시는 이유도 간단히 부탁드려요.') — 코치가 그대로 말하도록 적힌 문장.
#   종결 어미·문장부호로 끝나는 따옴표 구간만 예문으로 보고 코치 발화 어휘에 넣는다(내부 용어 인용 '사건 2' 는 해당 없음).
_QUOTED_SPAN_RE = re.compile(r"['‘“\"]([^'‘’“”\"\n]{6,200}?)['’”\"]")
_UTTERANCE_END_RE = re.compile(r"([요다죠까네]|니다|세요|습니까|[?!.…])\s*(\[[A-Z_]+\])?\s*$")


def quoted_utterances(texts: list[str]) -> list[str]:
    out = []
    for text in texts:
        for m in _QUOTED_SPAN_RE.finditer(text or ""):
            span = m.group(1).strip()
            if _UTTERANCE_END_RE.search(span) and re.search(r"[가-힣]", span):
                out.append(span)
    return out


def strip_quoted_utterances(text: str) -> str:
    return _QUOTED_SPAN_RE.sub(lambda m: " " if _UTTERANCE_END_RE.search(m.group(1).strip()) else m.group(0), text or "")


_NOUN_EVIDENCE_JOSA = ("은", "는", "이", "가", "을", "를", "의", "에", "에서", "도", "만", "으로", "로", "와", "과", "마다", "부터", "까지", "들")
_VERB_EVIDENCE_TAILS = ("다", "서", "고", "요", "습니다", "면", "지", "던", "는데", "라", "죠", "어요", "아요", "니다", "는다", "ㄴ다", "며", "니", "겠")


_VERB_TAIL_FIRST = set("다서고요면지던라죠며니겠어아")


def _evidence(w: str, raw: Counter) -> tuple[int, int]:
    """(명사 증거, 서술어 증거) — 템플릿 어절 중 w+조사 / w+복합어(지시문·지시사항) 꼴과 w+어미 꼴의 수."""
    noun = verb = 0
    for t, n in raw.items():
        if t == w or not t.startswith(w):
            continue
        rest = t[len(w):]
        if rest in _NOUN_EVIDENCE_JOSA:
            noun += n
        elif rest in _VERB_EVIDENCE_TAILS or _PREDICATE_TAIL_RE.search(rest) or rest[0] in _VERB_TAIL_FIRST:
            verb += n
        elif 1 <= len(rest) <= 3 and _HANGUL_RE.match(rest) and not _is_function_word(rest):
            noun += n
    return noun, verb


def _tokens_with_counts(texts: list[str]) -> tuple[Counter, Counter, Counter]:
    """(한글 후보 빈도, 한글 원형 단독 출현 빈도, 영문 토큰 빈도)."""
    kor, kor_bare, eng = Counter(), Counter(), Counter()
    for text in texts:
        for tok in _raw_tokens(text):
            if _HANGUL_RE.match(tok):
                cands = korean_candidates(tok)
                for c in cands:
                    kor[c] += 1
                kor_bare[tok] += 1
            elif _ENGLISH_RE.match(tok):
                eng[tok] += 1
    return kor, kor_bare, eng


def coach_speech_tokens(extra_texts: list[str] | None = None) -> set[str]:
    """코치가 실제로 말하도록 설계된 어휘(제외 집합). extra_texts: 템플릿 안 따옴표 예문."""
    texts: list[str] = list(extra_texts or [])
    for ch, fw in COMPETENCY_FRAMEWORK.items():
        texts.append(fw.get("name", ""))
        texts.append(fw.get("description", ""))
        for ind in fw.get("indicators", {}).values():
            texts.append(ind.get("name", ""))
    for qs in SUBCOMPETENCY_ANCHOR_QUESTIONS.values():
        texts.extend(qs)
    texts.extend(SUBCOMPETENCY_TOPIC_PHRASE.values())
    try:
        from diag_project.data import competencies as _c
        for qs in getattr(_c, "SUBCOMPETENCY_MUST_ASK", {}).values():
            texts.extend(qs)
    except Exception:  # pragma: no cover
        pass
    for p in COACH_SPEECH_SOURCES:
        texts.extend(string_literals(p, include_docstrings=False))
    # 페르소나 되받기 어구·대조 도입구·다리 문장(백엔드가 코치 발화로 붙이는 고정 문장)
    try:
        from diag_project.services import persona_voice as _pv
        for pool in getattr(_pv, "PERSONA_TAILS", {}).values():
            texts.extend(pool)
        texts.extend(getattr(_pv, "CONTRAST_LEADS", []))
        texts.extend(getattr(_pv, "_OLIVIA_LEADS", []))
    except Exception:  # pragma: no cover
        pass
    try:
        from diag_project.services import output_guard as _og
        for name in ("RESULT_FALLBACKS", "ANCHOR_TRANSITIONS", "_DEFAULT_BRIDGES", "_NO_KW_BRIDGES"):
            texts.extend(getattr(_og, name, []))
        texts.append(getattr(_og, "RESULT_QUANTIFY_QUESTION", ""))
        for pool in getattr(_og, "ALIGN_BRIDGE_POOL", {}).values():
            texts.extend(pool)
    except Exception:  # pragma: no cover
        pass
    for v in COACHES_PERSONA.values():
        texts.append(v.get("opening_new", ""))
        texts.append(v.get("opening_returning", ""))
    kor, kor_bare, eng = _tokens_with_counts(texts)
    return set(kor) | set(kor_bare) | {e.lower() for e in eng}


class _CoachVocab:
    """코치 발화 어휘 대조기 — 후보가 코치 어절과 같거나, 코치 어절이 '후보+조사/서술 어미' 꼴이거나,
    후보가 '코치 어절+조사' 꼴이면 코치 어휘로 본다."""

    def __init__(self, tokens: set[str]):
        self.tokens = tokens
        self.by_first: dict[str, list[str]] = defaultdict(list)
        for t in tokens:
            if t:
                self.by_first[t[0]].append(t)

    def __contains__(self, w: str) -> bool:
        if w in self.tokens:
            return True
        if not w or not _HANGUL_RE.match(w):
            return False
        for j in _ALL_JOSA:
            if w.endswith(j) and len(w) > len(j) and w[: -len(j)] in self.tokens:
                return True
        return any(t != w and _match_korean_word(t, w) for t in self.by_first.get(w[0], ()))


def build_lexicon() -> dict:
    """누설 사전. 반환: {"korean": {어절: 빈도}, "english": {식별어: 빈도}, "sources": {어절: [파일,...]}, "excluded_coach": n, ...}"""
    kor_total, kor_bare_total, eng_total = Counter(), Counter(), Counter()
    files_of: dict[str, set[str]] = defaultdict(set)
    upper_snake: Counter = Counter()
    quoted: list[str] = []
    for p in LEAK_SOURCES:
        raw_texts = string_literals(p, include_docstrings=True)
        quoted.extend(quoted_utterances(raw_texts))
        texts = [strip_quoted_utterances(t) for t in raw_texts]
        kor, kor_bare, eng = _tokens_with_counts(texts)
        kor_total.update(kor)
        kor_bare_total.update(kor_bare)
        eng_total.update(eng)
        for w in list(kor) + list(eng):
            files_of[w].add(p.name)
        for text in texts:
            for tok in _raw_tokens(text):
                if _UPPER_SNAKE_RE.match(tok):
                    upper_snake[tok] += 1
                    files_of[tok].add(p.name)
    # 보조 소스: 로그 포맷 문자열 — 빈도 1도 채택
    log_kor, log_eng = Counter(), Counter()
    for p in LOG_SOURCES:
        texts = [s for s in string_literals(p, include_docstrings=False) if _LOG_FORMAT_RE.search(s)]
        kor, kor_bare, eng = _tokens_with_counts(texts)
        log_kor.update(kor)
        log_eng.update(eng)
        for w in list(kor) + list(eng):
            files_of[w].add(p.name + "(log)")

    coach = _CoachVocab(coach_speech_tokens(quoted))
    korean: dict[str, int] = {}
    excluded_coach = 0
    for w, n in kor_total.items():
        if not (1 <= len(w) <= 6):
            continue
        if _is_function_word(w):
            continue
        if w in coach:
            excluded_coach += 1
            continue
        noun_ev, verb_ev = _evidence(w, kor_bare_total)
        if len(w) == 1:
            if n < MIN_COUNT_1CHAR or kor_bare_total.get(w, 0) < 1 or noun_ev < 3:
                continue
        elif n < MIN_COUNT and len(files_of[w]) < MIN_FILES:
            continue
        if len(w) <= 2 and verb_ev > noun_ev:
            continue
        if len(w) == 2 and noun_ev == 0 and n < 10:
            continue
        korean[w] = n
    for w, n in log_kor.items():
        if w in korean or not (2 <= len(w) <= 6) or _is_function_word(w) or w in coach:
            continue
        korean[w] = n
    # 조사 붙은 변형(턴은)이 어간(턴)과 함께 들어오면 변형은 뺀다.
    for w in list(korean):
        for j in _ALL_JOSA:
            stem = w[: -len(j)]
            if w.endswith(j) and stem and (stem in korean or _is_function_word(stem) or stem in coach):
                del korean[w]
                break

    english: dict[str, int] = {}
    for w, n in eng_total.items():
        lw = w.lower()
        if lw in _ENGLISH_STOP or lw in coach:
            continue
        if n >= 3 or _UPPER_SNAKE_RE.match(w):
            english[lw] = english.get(lw, 0) + n
    for w, n in upper_snake.items():
        english[w.lower()] = max(english.get(w.lower(), 0), n)
    for w, n in log_eng.items():
        lw = w.lower()
        if lw in english or lw in _ENGLISH_STOP or lw in coach:
            continue
        english[lw] = n
    return {
        "korean": dict(sorted(korean.items(), key=lambda x: (-x[1], x[0]))),
        "english": dict(sorted(english.items(), key=lambda x: (-x[1], x[0]))),
        "sources": {w: sorted(files_of.get(w) or files_of.get(w.lower()) or []) for w in list(korean) + list(english)},
        "excluded_coach": excluded_coach,
        "state_stems": [s for s in STATE_STEMS if any(t.startswith(s) for t in kor_total)],
    }


def lexicon_size(lex: dict) -> int:
    return len(lex["korean"]) + len(lex["english"])


# ══════════════════════════════════════════════════════════════════════════════
# 3. 누설 탐지
# ══════════════════════════════════════════════════════════════════════════════
_REMAINDER_RE = re.compile(
    r"^(?:은|는|이|가|을|를|의|에|에서|에게|께|께서|도|만|로|으로|와|과|나|이나|까지|부터|처럼|보다|마다|당|씩|별|들|들이|들을|들은|들의)?"
    r"(?:이|)(?:었|였|이었|이에|예|입니|)(?:습니다|니다|어요|요|고|는데|죠|네요|군요|지만|니|니까|라서|라고|라는|란|다|면|며)?$")
_ONE_CHAR_REMAINDER = {"", "은", "는", "이", "가", "을", "를", "의", "에", "에는", "에서", "에서는", "에도", "도", "만", "마다", "당", "부터", "까지",
                       "들", "들이", "들을", "들은", "로", "으로", "별", "씩", "이다", "입니다", "이에요", "이죠", "이고",
                       # (2026-10-29) 서술격 조사 활용형 — "다음 주제로 넘어가는 턴이라" 가 '턴' 으로 안 잡혔다
                       "이라", "이라고", "이라서", "이며", "이니", "이면", "인데", "이었", "이었다", "이었어요", "이라면", "입니까", "인가요", "이네요"}


def _match_korean_word(token: str, word: str) -> bool:
    if not token.startswith(word):
        return False
    rest = token[len(word):]
    if len(word) == 1:
        return rest in _ONE_CHAR_REMAINDER
    return len(rest) <= 6 and bool(_REMAINDER_RE.match(rest))


def find_lexicon_leaks(text: str, lex: dict, user_tokens: set[str] | None = None) -> list[str]:
    """코치 발화에서 사전 어휘를 어절 단위로 찾는다(원형 + 조사/서술 어미 허용).
    user_tokens: 리더가 그 시점까지 쓴 어절 — 리더가 먼저 쓴 말을 되받은 것은 누설이 아니다(설계된 되받기)."""
    hits: list[str] = []
    kor_words = lex["korean"]
    eng_words = lex["english"]
    user_tokens = user_tokens or set()
    for tok in _raw_tokens(text):
        if _HANGUL_RE.match(tok):
            for w in kor_words:
                if _match_korean_word(tok, w):
                    if not any(_match_korean_word(u, w) for u in user_tokens):
                        hits.append(w)
                    break
        elif re.match(r"^[A-Za-z][A-Za-z_]*$", tok):
            if tok.lower() in eng_words and tok.lower() not in user_tokens:
                hits.append(tok)
    # 중복 제거(순서 유지)
    seen, out = set(), []
    for h in hits:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out


def find_state_report(text: str) -> list[str]:
    hits = list(find_state_leak(text))
    for m in _STATE_REPORT_RE.finditer(text or ""):
        s = re.sub(r"\s+", " ", m.group(0)).strip()
        if s and s not in hits:
            hits.append(s)
    return hits


# ══════════════════════════════════════════════════════════════════════════════
# 앱(출력 가드)용 편의 함수
# ══════════════════════════════════════════════════════════════════════════════
@lru_cache(maxsize=1)
def cached_lexicon() -> dict:
    """프로세스당 1회 계산. 템플릿 파일이 바뀌면 재기동 시 반영된다."""
    return build_lexicon()


# 리더 발화 코퍼스(tests/fixtures 의 실제 리더 입력) — 리더가 일상적으로 쓰는 어절('지시'·'태도'·'현재'·'사건' …)은
#   템플릿에도 나오지만 코치가 써도 누설이 아니다. 가드(문장 삭제)는 이 어절을 제외한 '엄격 사전'만 쓴다. 린트는 전체 사전으로 센다.
_FIXTURE_DIR = ROOT / "tests" / "fixtures"
EVERYDAY_MIN_COUNT = 3
# (2026-10-29) 운영 세션 리더 입력(tests/fixtures/sessions_1028/*_users.json)에 '한 번이라도' 나온 어절은 엄격 사전에서 뺀다 —
#   템플릿 빈도가 높아도 리더가 쓰는 말이면 누설 근거가 못 된다(전환·응답·요약·종료·안내·없음·최대·인사 류).
_LEADER_DIR = _FIXTURE_DIR / "sessions_1028"
LEADER_MIN_COUNT = 1
# 가드(문장 삭제)는 템플릿에 10회 이상 나오는 어절만 쓴다 — 5회 안팎의 어절('말하지'·'선언'·'인정'·'관찰')은 예시 문장 조각이거나
#   일반 명사라 삭제가 오히려 대화를 깬다(10/28 재생 2라운드). 린트는 전체 사전으로 세어 보고한다.
GUARD_MIN_COUNT = 10


def _fixture_texts() -> list[str]:
    import json
    out: list[str] = []

    def walk(x):
        if isinstance(x, str):
            out.append(x)
        elif isinstance(x, list):
            for i in x:
                walk(i)
        elif isinstance(x, dict):
            for v in x.values():
                walk(v)
    for f in sorted(_FIXTURE_DIR.glob("*.json")) if _FIXTURE_DIR.exists() else []:
        try:
            walk(json.loads(f.read_text(encoding="utf-8")))
        except Exception:   # noqa: BLE001
            continue
    return out


@lru_cache(maxsize=1)
def guard_lexicon() -> dict:
    """가드용 엄격 사전 = 전체 사전 − 리더 발화 코퍼스에 EVERYDAY_MIN_COUNT 회 이상 나온 어절(일상어). 영문은 그대로."""
    lex = cached_lexicon()
    counts: Counter = Counter()
    for t in _fixture_texts():
        for tok in _raw_tokens(t):
            if not _HANGUL_RE.match(tok):
                continue
            for w in lex["korean"]:
                if _match_korean_word(tok, w):
                    counts[w] += 1
                    break
    everyday = {w for w, n in counts.items() if n >= EVERYDAY_MIN_COUNT}
    leader_counts: Counter = Counter()
    for t in _leader_texts():
        for tok in _raw_tokens(t):
            if not _HANGUL_RE.match(tok):
                continue
            for w in lex["korean"]:
                if _match_korean_word(tok, w):
                    leader_counts[w] += 1
                    break
    leader_words = {w for w, n in leader_counts.items() if n >= LEADER_MIN_COUNT}
    excluded = everyday | leader_words
    return {"korean": {w: c for w, c in lex["korean"].items() if w not in excluded and c >= GUARD_MIN_COUNT},
            "english": dict(lex["english"]), "everyday_excluded": sorted(excluded),
            "leader_excluded": sorted(w for w in leader_words if lex["korean"].get(w, 0) >= GUARD_MIN_COUNT)}


def _leader_texts() -> list[str]:
    """운영 세션 5건의 리더 입력(json 리스트)."""
    import json
    out: list[str] = []
    if not _LEADER_DIR.exists():
        return out
    for f in sorted(_LEADER_DIR.glob("*_users.json")):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:   # noqa: BLE001
            continue
        out.extend(x for x in data if isinstance(x, str))
    return out


def user_token_set(user_texts: list[str]) -> set[str]:
    toks: set[str] = set()
    for t in user_texts or []:
        toks.update(x.lower() for x in _raw_tokens(t or ""))
    return toks


def find_leaks(text: str, user_texts: list[str] | None = None, *, strict: bool = True) -> list[str]:
    """코치 출력의 내부 어휘 + 상태 보고문(중복 제거). 리더가 쓴 어절 되받기는 제외.
    strict=True(가드 기본): 일상어를 뺀 엄격 사전. False: 린트와 같은 전체 사전."""
    lex = guard_lexicon() if strict else cached_lexicon()
    out = find_lexicon_leaks(text or "", lex, user_token_set(user_texts or []))
    for s in find_state_report(text or ""):
        if s not in out:
            out.append(s)
    return out


def strip_leak_sentences(text: str, words: list[str]) -> tuple[str, int]:
    """누설 평서문을 지운다. 질문 문장은 그대로 둔다(질문 보존). 목록 줄은 통째로 판단. (결과, 지운 문장 수)"""
    if not words:
        return text, 0
    n = 0
    out_lines: list[str] = []
    for line in (text or "").split("\n"):
        if not line.strip():
            out_lines.append(line)
            continue
        kept: list[str] = []
        for s in split_sentences(line):
            hit = [w for w in words if (w in s) or any(_match_korean_word(tok, w) for tok in _raw_tokens(s) if _HANGUL_RE.match(tok))]
            if not hit:
                kept.append(s)
                continue
            if is_question(s):
                kept.append(s)      # 질문은 보존(어절만 떼면 '내리기 , 실제로' 처럼 문법이 깨진다 — 관찰만)
            else:
                n += 1
        if kept or not split_sentences(line):
            out_lines.append(" ".join(kept) if kept else line)
    out = "\n".join(out_lines)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    return (out if out else text), n
