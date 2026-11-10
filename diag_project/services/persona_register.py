"""(2026-11-10 P9-6) 페르소나 말투(어미 결) 검사·교정 — LLM 이 쓰는 여는 문장·범위 문장에도 페르소나 어미를 건다.

11/10 운영 Jessica 세션: 사전 앵커는 persona_voice 가 '~습니까?' 로 바꾸지만, LLM 이 쓴 여는 문장('…살펴보려고 해요')·범위 문장
('…함께 짚어볼 거예요')은 해요체로 나가 말투가 섞였다. 여기서는 규칙으로만 본다(LLM 없음).
  합쇼체(formal)    Jessica · Daniel — 문장 끝은 '~습니다/~습니까' 만. '~요'(해요체) 금지. Daniel 의 '~는지요?' 변주는 허용.
  혼용(mixed)       Lucas — 말투 프로필이 '~요/~죠' 단문이고 고정 문장은 합쇼체('알겠습니다')라 설계상 섞인다. 검사하지 않는다.
  해요체(polite)    Ella · Olivia · Michael — 질문이 '~습니까?' 로 끝나면 섞임.
교정은 보수적인 어미표로만 하고, 표에 없는 어미는 건드리지 않는다(위반으로 남겨 호출자가 폴백).
"""
from __future__ import annotations

import re

from diag_project.services.intro_messages import persona_key
from diag_project.services.output_guard import split_sentences

REGISTER: dict[str, str] = {"Ella": "polite", "Olivia": "polite", "Michael": "polite",
                            "Jessica": "formal", "Daniel": "formal", "Lucas": "mixed"}

_TAIL = r"(?P<p>[.?!…~\"'”’]*)$"
_POLITE_END_RE = re.compile(r"(요|죠)" + _TAIL)
_POLITE_MID_RE = re.compile(r"[가-힣](는데요|인데요|거든요|고요|구요|지만요|서요|니까요|군요|네요|어요|아요|신가요|셨나요)\s*[,，—]")
_DANIEL_OK_RE = re.compile(r"(는지요|은지요|인지요|신지요|을지요|지요|군요)" + _TAIL)   # 고정 문장 '~셨군요.'
_LUCAS_OK_RE = re.compile(r"(나요|은요|는요|건요|면요|만요|군요)" + _TAIL)
_FORMAL_Q_RE = re.compile(r"(습니까|십니까|입니까|ㅂ니까|읍니까)\?*$")
# (p9b) 해라체 평서('…꽤 다르다.')·전언 꼴('…다르더랍니다.')은 어느 페르소나에게도 섞임 — 여는 문장 틀을 평서체로 주자 LLM 이 그대로 냈다
_PLAIN_END_RE = re.compile(r"(?<!니)다[.!…]*$")
_HEARSAY_END_RE = re.compile(r"더랍니다[.!…]*$")

# 해요체 → 합쇼체. (패턴, 치환) — 문장 끝(문장부호 앞)에만 건다. 긴 패턴 먼저.
_TO_FORMAL_STMT: list[tuple[str, str]] = [
    (r"볼 거예요", "보겠습니다"), (r"할 거예요", "하겠습니다"), (r"갈 거예요", "가겠습니다"), (r"드릴 거예요", "드리겠습니다"),
    (r"거예요", "것입니다"), (r"거에요", "것입니다"),
    (r"려고 해요", "려고 합니다"), (r"려 해요", "려고 합니다"), (r"려고요", "려고 합니다"), (r"려고 하는데요", "려고 합니다"),
    (r"볼게요", "보겠습니다"), (r"할게요", "하겠습니다"), (r"드릴게요", "드리겠습니다"), (r"갈게요", "가겠습니다"),
    (r"들을게요", "듣겠습니다"), (r"둘게요", "두겠습니다"), (r"을게요", "겠습니다"),
    (r"달라요", "다릅니다"), (r"싶어요", "싶습니다"), (r"있어요", "있습니다"), (r"없어요", "없습니다"), (r"같아요", "같습니다"),
    (r"이에요", "입니다"), (r"예요", "입니다"), (r"돼요", "됩니다"), (r"해요", "합니다"), (r"봐요", "봅니다"),
    (r"(았|었|였|했|셨|겠)어요", r"\1습니다"), (r"(았|었|였|했|셨|겠)네요", r"\1습니다"), (r"(았|었|였|했|셨|겠)군요", r"\1습니다"),
    (r"(았|었|였|했|셨)죠", r"\1습니다"),
    (r"시네요", "십니다"), (r"시군요", "십니다"), (r"하네요", "합니다"), (r"하군요", "합니다"),
    (r"이네요", "입니다"), (r"이군요", "입니다"), (r"인데요", "입니다"), (r"이죠", "입니다"),
    (r"주세요", "주십시오"), (r"하세요", "하십시오"), (r"보세요", "보십시오"),
    (r"일 텐데요", "일 것입니다"), (r"을 텐데요", "을 것입니다"), (r"텐데요", "것입니다"), (r"가 봐요", "가 보겠습니다"),
]
_TO_FORMAL_MID: list[tuple[str, str]] = [
    (r"하는데요([,，])", r"합니다만\1"), (r"인데요([,，])", r"입니다만\1"), (r"(았|었|였|했|셨)는데요([,，])", r"\1습니다만\2"),
    (r"는데요([,，])", r"습니다만\1"),
    (r"(았|었|였|했|셨)군요([,，])", r"\1고\2"), (r"시는군요([,，])", r"시고\1"), (r"(았|었|였|했|셨)고요([,，])", r"\1고\2"),
    (r"있어요(\s*—)", r"있습니다\1"),
    (r"신가요([,，])", r"신지\1"), (r"(았|었|였|했|셨)나요([,，])", r"\1는지\2"),
]
_TO_POLITE_Q: list[tuple[str, str]] = [
    (r"(셨|었|았|였|했)습니까\?$", r"\1어요?"), (r"있습니까\?$", "있어요?"), (r"없습니까\?$", "없어요?"),
    (r"입니까\?$", "인가요?"), (r"십니까\?$", "세요?"), (r"습니까\?$", "나요?"),
]


def register_of(persona_name: str | None) -> str:
    return REGISTER.get(persona_key(persona_name), "polite")


def register_violations(persona_name: str | None, text: str | None) -> list[str]:
    """페르소나 말투와 다른 어미로 끝난 문장 목록(섞임). 고정 문장·인용은 호출자가 걸러서 넘긴다."""
    reg = register_of(persona_name)
    k = persona_key(persona_name)
    out: list[str] = []
    if reg == "mixed":
        return out
    for s in split_sentences(text or ""):
        s = s.strip()
        if not s:
            continue
        core = s.rstrip(".?!…~\"'”’ ")
        if (_PLAIN_END_RE.search(s) and not s.rstrip().endswith("?")) or _HEARSAY_END_RE.search(s):
            out.append(s)
            continue
        if reg in ("formal", "terse"):
            bad = bool(_POLITE_END_RE.search(s)) or bool(_POLITE_MID_RE.search(s))
            if bad and k == "Daniel" and _DANIEL_OK_RE.search(s) and not _POLITE_MID_RE.search(s):
                bad = False
            if bad and reg == "terse" and _LUCAS_OK_RE.search(s) and not _POLITE_MID_RE.search(s):
                bad = False
            if bad:
                out.append(s)
        else:
            if _FORMAL_Q_RE.search(core + ("?" if s.rstrip().endswith("?") else "")) and s.rstrip().endswith("?"):
                out.append(s)
    return out


def _has_batchim(ch: str) -> bool:
    return bool(ch) and "가" <= ch <= "힣" and (ord(ch) - 0xAC00) % 28 != 0


def _formal_stem(stem: str, tail: str = "니다") -> str | None:
    """어간 + 합쇼체 어미 — 받침 없으면 ㅂ 받침을 얹고('읽히' → '읽힙니다'), 있으면 '습니다'('같' → '같습니다'). ㄹ 받침은 떼고 ㅂ('만들' → '만듭니다')."""
    stem = stem.rstrip()
    if not stem or not ("가" <= stem[-1] <= "힣"):
        return None
    code = ord(stem[-1]) - 0xAC00
    jong = code % 28
    if jong == 0 or jong == 8:                    # 받침 없음 또는 ㄹ
        return stem[:-1] + chr(0xAC00 + code - jong + 17) + tail      # 17 = ㅂ
    return stem + ("습" + tail)


_GENERIC_TAILS = ("시는군요", "는군요", "네요", "군요", "고요", "구요", "지요", "죠")


def _formalize_sentence(s: str) -> str:
    from diag_project.services.persona_voice import _apply_endings
    t = s
    for pat, rep in _TO_FORMAL_MID:
        t = re.sub(pat, rep, t)
    m = re.search(_TAIL, t)
    punct = m.group("p") if m else ""
    body = t[: len(t) - len(punct)] if punct else t
    if punct.startswith("?") or t.rstrip().endswith("?"):
        for pat, rep in ((r"해\s*볼까요$", "하겠습니다"), (r"볼까요$", "보겠습니다")):      # 청유 '~볼까요?' 는 평서 '~겠습니다.' 로
            new = re.sub(pat, rep, body)
            if new != body:
                return new + "."
        for pat, rep in ((r"계세요$", "계십니까"), (r"어떨까요$", "어떻습니까"), (r"주시겠어요$", "주시겠습니까"), (r"으세요$", "으십니까"), (r"세요$", "십니까")):
            new = re.sub(pat, rep, body)
            if new != body:
                return new + "?"
        q = _apply_endings(body + "?", 1)                      # 질문은 persona_voice 의 Jessica 어미표('~습니까?')
        return q if q != body + "?" else t
    if body.endswith("더랍니다"):                              # '다르더랍니다' → '다릅니다'
        new = _formal_stem(body[:-4])
        if new:
            return new + (punct or ".")
    if body.endswith("다") and not body.endswith("니다"):      # 해라체 평서 — 아는 꼴만 고친다(명사+다 '문제다'는 어간과 구분이 안 돼 건드리지 않는다)
        for pat, rep in ((r"다르다$", "다릅니다"), (r"이다$", "입니다"), (r"한다$", "합니다"), (r"된다$", "됩니다"), (r"있다$", "있습니다"),
                         (r"없다$", "없습니다"), (r"같다$", "같습니다"), (r"(았|었|였|했|셨|겠)다$", r"\1습니다"), (r"는다$", "습니다")):
            new = re.sub(pat, rep, body)
            if new != body:
                return new + (punct or ".")
        return t
    for pat, rep in _TO_FORMAL_STMT:
        new = re.sub(pat + "$", rep, body)
        if new != body:
            return new + (punct or ".")
    # 일반 규칙: 어간 + '네요/군요/는군요/고요/죠' → 어간 + ㅂ니다/습니다
    for tail in _GENERIC_TAILS:
        if body.endswith(tail) and len(body) > len(tail):
            stem = body[: -len(tail)] + ("시" if tail == "시는군요" else "")
            new = _formal_stem(stem)
            if new:
                return new + (punct or ".")
    # '~ㄹ게요' → '~겠습니다', '~세요.'(평서) → '~십니다'
    if body.endswith("게요") and len(body) >= 3 and (ord(body[-3]) - 0xAC00) % 28 == 8:
        c = ord(body[-3]) - 0xAC00
        return body[:-3] + chr(0xAC00 + c - 8) + "겠습니다" + (punct or ".")
    if body.endswith("세요"):
        return body[:-2] + "십니다" + (punct or ".")
    return t


def _politen_sentence(s: str) -> str:
    t = s.strip()
    if not t.endswith("?"):
        return s
    for pat, rep in _TO_POLITE_Q:
        new = re.sub(pat, rep, t)
        if new != t:
            return new
    return s


def apply_register(persona_name: str | None, text: str | None) -> tuple[str, int, list[str]]:
    """말투가 섞인 문장을 어미표로 교정한다. (결과, 고친 문장 수, 그래도 남은 위반 문장)."""
    src = text or ""
    bad = register_violations(persona_name, src)
    if not bad:
        return src, 0, []
    reg = register_of(persona_name)
    out, n = src, 0
    for s in bad:
        _plain = (_PLAIN_END_RE.search(s) and not s.rstrip().endswith("?")) or _HEARSAY_END_RE.search(s)
        new = _formalize_sentence(s) if (reg in ("formal", "terse") or _plain) else _politen_sentence(s)
        if new != s:
            out = out.replace(s, new, 1)
            n += 1
    return out, n, register_violations(persona_name, out)
