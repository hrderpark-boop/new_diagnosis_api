"""ALIGN(정의 잇기) 턴 결정론 조립 (2026-10-28 P0-1).

구조는 백엔드가 고정하고 LLM 은 '공감 되받기 2~3문장'만 쓴다. 챕터 크기와 무관하게 같은 렌더러.

  [LLM 공감 되받기 2~3문장]
  [고정 정의 1문장]
  [목록 — 하위역량 전부, '· ' 줄]
  [고정 안내] 이 N가지를 하나씩 여쭤볼 텐데, 항목마다 실제 있었던 일 하나씩 떠올려 주시면 됩니다.
  [고정 다리] 먼저 ~쪽부터요.
  [앵커 1개]

LLM 출력에서 질문 문장·목록 줄·다른 챕터 가이드 문구·리더에게 선택을 넘기는 문장은 전부 제거한다.
고정 문장은 전부 페르소나 어미(intro_messages.PERSONA_LINES)로 나간다.
"""
from __future__ import annotations

import re

from diag_project.data.competencies import COMPETENCY_FRAMEWORK
from diag_project.services.intro_messages import align_topic_bridge, persona_line
from diag_project.services.korean import with_josa
from diag_project.services.output_guard import is_question, split_sentences

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


def guide_sentence(n: int, persona_name: str | None) -> str:
    return persona_line(persona_name, "align_guide", n=_KO_NUM.get(n, str(n)))


def render_align(
    *,
    llm_text: str,
    chapter: str,
    sub_names: list[str],
    persona_name: str | None,
    bridge_sub_key: str | None,
    bridge_sub_name: str | None,
    anchor: str,
    user_text: str | None = None,
) -> str:
    """ALIGN 최종 출력. anchor 는 이미 페르소나 어미가 적용된 앵커 질문 한 문장. user_text 는 리더의 이번 답(복사 문장 제거용)."""
    recv = receive_sentences(llm_text, chapter=chapter, sub_names=sub_names, user_text=user_text)
    if not recv:
        recv = [persona_line(persona_name, "align_receive_fallback")]
    parts = [
        " ".join(recv),
        definition_sentence(chapter, persona_name) + "\n" + "\n".join(f"· {n}" for n in sub_names),
        guide_sentence(len(sub_names), persona_name) + " " + align_topic_bridge(bridge_sub_key, bridge_sub_name, persona_name),
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
    if text.count("?") != 1:
        reasons.append(f"물음표 {text.count('?')}개")
    last = split_sentences(lines[-1] if lines else "")
    last_s = last[-1] if last else ""
    if not is_question(last_s):
        reasons.append("끝이 질문이 아님")
    if re.search(r"(않죠|않지요|다르지 않|맞죠|맞지요|그렇죠)\s*\?$", last_s):
        reasons.append("확인 질문으로 끝남")
    return (not reasons), reasons
