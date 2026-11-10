"""ALIGN(정의 잇기) 턴 결정론 조립 (2026-10-28 P0-1).

구조는 백엔드가 고정하고 LLM 은 '공감 되받기 2~3문장'만 쓴다. 챕터 크기와 무관하게 같은 렌더러.

  [LLM 공감 되받기 2~3문장]
  [고정 정의 1문장]
  [목록 — 하위역량 전부, '· ' 줄]
  [고정 안내] 이 N가지가 실제로 어떻게 나타나는지, 있었던 일 몇 가지를 깊게 들어보겠습니다. (2026-11-04 BEI 결정 6)
  [고정 다리] 먼저 하나를 깊게 들어볼게요.
  [사례 1 여는 앵커 1개]

LLM 출력에서 질문 문장·목록 줄·다른 챕터 가이드 문구·리더에게 선택을 넘기는 문장은 전부 제거한다.
고정 문장은 전부 페르소나 어미(intro_messages.PERSONA_LINES)로 나간다.
"""
from __future__ import annotations

import re

from diag_project.data.competencies import COMPETENCY_FRAMEWORK
from diag_project.services.intro_messages import align_guide_line, align_open_line, persona_line
from diag_project.services.korean import with_josa
from diag_project.services.output_guard import is_question, key_noun_phrase, split_sentences, count_questions
from diag_project.services.receive_check import quote_phrase

RECEIVE_MAX_SENTENCES = 3
_LIST_LINE_RE = re.compile(r"^\s*([·•\-*]|\d+[.)])\s*")
_CHOICE_RE = re.compile(r"(어느 쪽|어떤 쪽|쪽부터 (함께 )?(들여다|볼|보|시작)|골라|선택해|원하시는 (쪽|것|순서)|편하신 (쪽|순서)|자주 쓰시는 쪽)")
_KO_NUM = {1: "한", 2: "두", 3: "세", 4: "네", 5: "다섯", 6: "여섯", 7: "일곱", 8: "여덟", 9: "아홉", 10: "열"}


def _other_chapter_markers(chapter: str) -> list[str]:
    """다른 챕터의 이름·정의 핵심 어절 — ALIGN 되받기에 섞이면 가이드 유입으로 보고 그 문장을 버린다."""
    marks: list[str] = []
    for k, v in COMPETENCY_FRAMEWORK.items():
        if k == chapter:
            continue
        name = v.get("name") or ""
        if name:
            marks.append(name)                       # 다른 챕터 이름 자체('조직관리')
        for ind in (v.get("indicators") or {}).values():
            n = (ind.get("name") or "").split("(")[0].strip()
            if len(n) >= 3:
                marks.append(n)
    return marks


_ASK_RE = re.compile(r"(여쭙|여쭤|여쭐|묻겠|물어볼|물어보|질문(을|이|드|하)|들려주|말씀해\s*주|궁금)")


def _echoes_user(s: str, user_text: str | None) -> bool:
    """리더 답변을 그대로(또는 거의 그대로) 옮긴 문장 — 되받기가 아니라 복사."""
    if not user_text or len(s.replace(" ", "")) < 12:
        return False
    ns, nu = re.sub(r"\s+", "", s), re.sub(r"\s+", "", user_text)
    if ns in nu:
        return True
    import difflib
    return difflib.SequenceMatcher(None, ns, nu).ratio() >= 0.8


def receive_sentences(llm_text: str, *, chapter: str, sub_names: list[str], user_text: str | None = None) -> list[str]:
    """LLM 출력에서 되받기 평서문 최대 3개. 질문·간접 질문·목록 줄·하위역량 나열·다른 챕터 문구·선택 넘기기·리더 답변 복사는 버린다."""
    others = _other_chapter_markers(chapter)
    out: list[str] = []
    text = re.sub(r"([.!?…])(?=[가-힣A-Za-z(])", r"\1 ", llm_text or "")   # 마침표 뒤 공백 누락 보정(문장 수 세기)
    for line in text.split("\n"):
        if not line.strip() or _LIST_LINE_RE.match(line) or line.strip().startswith("```"):
            continue
        for s in split_sentences(line):
            s = s.strip()
            if not s or is_question(s) or _ASK_RE.search(s):
                continue
            if _echoes_user(s, user_text):
                continue
            if sum(1 for n in sub_names if n and n in s) >= 2:      # 하위역량을 문장에 나열 → 목록이 대신한다
                continue
            if any(m in s for m in others):
                continue
            if _CHOICE_RE.search(s):
                continue
            if re.search(r"(가지를|가지로|가지 영역|가지 항목)", s) and re.search(r"(살펴|들여다|여쭤|볼게요|보겠습니다)", s):
                continue                                              # 안내문은 시스템이 붙인다
            out.append(s)
            if len(out) >= RECEIVE_MAX_SENTENCES:
                return out
    return out


def definition_sentence(chapter: str, persona_name: str | None) -> str:
    fw = COMPETENCY_FRAMEWORK.get(chapter, {})
    name = fw.get("name") or "이 역량"
    desc = (fw.get("description") or "").strip().rstrip(".")
    return persona_line(persona_name, "align_definition", cn_eul=with_josa(name, "을/를"), defn=desc)


def guide_sentence(n: int, persona_name: str | None, variant: int = 0) -> str:
    """(2026-11-05 P4-1) 안내 문장 3종 순환 — variant 는 챕터 순서 인덱스(세션 5챕터에서 같은 문장 ≤2회)."""
    return align_guide_line(_KO_NUM.get(n, str(n)), persona_name, variant)


def leader_definition_body(chapter: str, user_text: str | None) -> str:
    """리더 정의 답에서 역량 이름('자기관리는 …')을 뺀 본문 — 인용 후보에서 역량 이름을 제외한다(2026-11-05)."""
    name = (COMPETENCY_FRAMEWORK.get(chapter or "", {}) or {}).get("name") or ""
    t = user_text or ""
    if name:
        t = re.sub(rf"{re.escape(name)}(이란|란|이라는|라는|은|는|이|가|을|를|도)?\s*", " ", t)
    return re.sub(r"\s+", " ", t).strip()


_DEF_TAIL_RES = (
    r"\s*(이)?라고\s*(생각(합니다|해요|하고\s*있(습니다|어요)|했습니다|해)|봅니다|봐요|보고\s*있(습니다|어요)|믿(습니다|어요)|여깁니다|여겨요|할\s*수\s*있(습니다|어요))[.!…~]*$",
    r"\s*(인\s*(것|거)|것|거)?\s*같(아요|습니다|네요)[.!…~]*$",
    r"\s*(이)?(라고요|입니다|이에요|예요|이죠|이지요|죠|이요|요)[.!…~]*$",
    r"[.!…~]+$",
)
DEF_QUOTE_MIN_EOJEOL = 4
DEF_QUOTE_MAX_CHARS = 70


def definition_quote(chapter: str, user_text: str | None) -> str:
    """(2026-11-10 P9 승인 조건 4) ALIGN 받기 폴백에 인용할 리더 정의의 구절 — 정의 첫 문장에서 역량 이름과 '…라고 생각합니다' 꼬리를 떼고 남은 것.
    4어절 이상이면 그 구절(길면 쉼표·연결어미에서 끊어 70자 안), 그보다 짧아도 정의 한 줄을 그대로 받는다. 정의가 없으면 빈 문자열."""
    from diag_project.services.output_guard import split_sentences
    body = leader_definition_body(chapter, user_text)
    first = next((x.strip() for x in split_sentences(body) if x.strip()), "")
    t = first
    for _ in range(2):
        for pat in _DEF_TAIL_RES:
            t = re.sub(pat, "", t).strip()
    t = t.strip(" ,'\"“”‘’")
    from diag_project.prompts.phase3a.layer3_state import is_consent_only
    if not t or is_consent_only(first) or len(re.sub(r"\s+", "", t)) < 4:
        return ""                                  # '네'·'좋아요' 같은 동의만 온 답은 정의가 아니다 — 되받기 생략
    if len(t) > DEF_QUOTE_MAX_CHARS:
        cut = [m.end() for m in re.finditer(r"(,\s|고\s|며\s|서\s)", t) if DEF_QUOTE_MAX_CHARS // 2 <= m.end() <= len(t)]
        tail = t[cut[0]:].strip() if cut else t[-DEF_QUOTE_MAX_CHARS:].split(" ", 1)[-1]
        if len(tail.split()) >= DEF_QUOTE_MIN_EOJEOL:
            t = tail
    return t


def _rago(phrase: str) -> str:
    ch = (phrase or "")[-1:]
    return "이라고" if ch and "가" <= ch <= "힣" and (ord(ch) - 0xAC00) % 28 else "라고"


def render_align(
    *,
    llm_text: str,
    chapter: str,
    sub_names: list[str],
    persona_name: str | None,
    anchor: str,
    user_text: str | None = None,
    variant: int = 0,
) -> str:
    """ALIGN 최종 출력. anchor 는 사례 1 여는 문장(P4-4: 왜 묻는지 1문장 + 있었는지 질문, 또는 사전 앵커 한 문장). user_text 는 리더의 이번 답(복사 문장 제거용).
    variant 는 챕터 순서 인덱스 — 안내·다리 고정 문장 3종 순환(P4-1)."""
    recv = receive_sentences(llm_text, chapter=chapter, sub_names=sub_names, user_text=user_text)
    if not recv:
        # (2026-11-05 P3-1) 일반 폴백('네, 잘 들었어요') 금지. (2026-11-10 P9 승인 조건 4) 낱말 하나(''상태'를 중심에')가 아니라 리더 정의의 구절을
        #   그대로 받아 '…라고 보시는군요.' — 구절이 없으면(정의가 비었으면) 되받기 생략.
        phrase = definition_quote(chapter, user_text)
        recv = [persona_line(persona_name, "align_receive_quote", quote_rago=f"'{phrase}'{_rago(phrase)}")] if phrase else []
    parts = [
        " ".join(recv),
        definition_sentence(chapter, persona_name) + "\n" + "\n".join(f"· {n}" for n in sub_names),
        guide_sentence(len(sub_names), persona_name, variant) + " " + align_open_line(persona_name, variant),
        (anchor or "").strip(),
    ]
    return "\n\n".join(p for p in parts if p.strip())


def align_shape_ok(text: str, sub_names: list[str]) -> tuple[bool, list[str]]:
    """린트와 같은 기준의 자가 점검: 목록 전부·끝이 질문 1개·확인 질문 아님. (통과 여부, 사유)"""
    reasons: list[str] = []
    lines = [l.strip() for l in (text or "").split("\n")]
    listed = {l[1:].strip() for l in lines if l.startswith("·")}
    missing = [n for n in sub_names if n not in listed]
    if missing:
        reasons.append(f"목록 누락: {missing}")
    # (2026-11-04 P3-4 2차) Michael 요청형 앵커('…하나만 들려주세요.')는 물음표가 없다 — 질문 문장 수(is_question)로 센다.
    _nq = count_questions(text)
    if _nq != 1:
        reasons.append(f"질문 문장 {_nq}개")
    last = split_sentences(lines[-1] if lines else "")
    last_s = last[-1] if last else ""
    # (P4-4) 여는 문장은 질문 뒤에 짧은 덧붙임 1문장('작은 일이어도요.')이 올 수 있다 — 마지막 줄의 질문이 끝이거나 끝에서 두 번째(덧붙임 ≤ 25자)면 통과
    if not is_question(last_s) and not (len(last) >= 2 and is_question(last[-2]) and len(last_s) <= 25):
        reasons.append("끝이 질문이 아님")
    if re.search(r"(않죠|않지요|다르지 않|맞죠|맞지요|그렇죠)\s*\?$", last_s):
        reasons.append("확인 질문으로 끝남")
    return (not reasons), reasons
