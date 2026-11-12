"""(2026-11-10 P9-6) 페르소나 말투(어미 결) 검사·교정 — LLM 이 쓰는 여는 문장·범위 문장에도 페르소나 어미를 건다.

11/10 운영 Jessica 세션: 사전 앵커는 persona_voice 가 '~습니까?' 로 바꾸지만, LLM 이 쓴 여는 문장('…살펴보려고 해요')·범위 문장
('…함께 짚어볼 거예요')은 해요체로 나가 말투가 섞였다. 여기서는 규칙으로만 본다(LLM 없음).
  합쇼체(formal)    Jessica · Daniel — 문장 끝은 '~습니다/~습니까' 만. '~요'(해요체) 금지. Daniel 의 '~는지요?' 변주는 허용.
  혼용(mixed)       Lucas — 말투 프로필이 '~요/~죠' 단문이고 고정 문장은 합쇼체('알겠습니다')라 설계상 섞인다. 검사하지 않는다.
  해요체(polite)    Ella · Olivia · Michael — 질문이 '~습니까?' 로 끝나면 섞임.
교정은 보수적인 어미표로만 하고, 표에 없는 어미는 건드리지 않는다(위반으로 남겨 호출자가 폴백).

(2026-11-10 P9 승인 조건 1) 어미 강제는 **질문 문장과 고정 문장**에만 건다. 받는 문장(되받기)은 Jessica·Daniel 도 '~군요/~네요/~셨군요'를 쓴다 —
금지는 해요체 질문('~어요?')뿐. scope="questions" 는 질문 문장(+ fixed 로 넘긴 고정 문장)만 보고, scope="all" 은 시스템이 자리를 정한 문장
(여는 문장·범위 문장·첫 인사·안내 본문)에 쓴다.

(2026-11-11 P10-4) scope="strict" — 여는 문장·범위 문장·다리처럼 **코치가 자리를 정해 쓰는 문장**은 코치 어미를 강제한다. 받는 문장만 자유.
  해요체 코치(Ella·Olivia·Michael): 평서문이 '~습니다/~ㅂ니다/~십시오'로 끝나도 섞임(11/11 운영 Olivia: 여는 문장 '…다릅니다', '…이야기입니다').
  합쇼체 코치(Jessica·Daniel): '~군요/~네요' 면제 없이 '~습니다/~습니까'만.
  "all" 은 종전대로 — 공용 안내 본문(합쇼체·해요체가 섞인 템플릿)을 해요체 코치에게서 건드리지 않기 위해 strict 를 따로 둔다.
"""
from __future__ import annotations

import re

from diag_project.services.intro_messages import persona_key
from diag_project.services.output_guard import split_sentences

REGISTER: dict[str, str] = {"Ella": "polite", "Olivia": "polite", "Michael": "polite",
                            "Jessica": "formal", "Daniel": "formal", "Lucas": "mixed"}

_TAIL = r"(?P<p>[.?!…~\"'”’]*)$"
_POLITE_END_RE = re.compile(r"(요|죠)" + _TAIL)
# (2026-11-12 P11d-4) '…에 관한 건데요,' — 앞이 띄어쓰기라도 잡는다(합쇼체 코치의 여는 문장에 남았다)
_POLITE_MID_RE = re.compile(r"(?:[가-힣](?:는데요|인데요|거든요|고요|구요|지만요|서요|니까요|군요|네요|어요|아요|신가요|셨나요)|건데요)\s*[,，—]")
_DANIEL_OK_RE = re.compile(r"(는지요|은지요|인지요|신지요|을지요|지요|군요)" + _TAIL)   # 고정 문장 '~셨군요.'
_LUCAS_OK_RE = re.compile(r"(나요|은요|는요|건요|면요|만요|군요)" + _TAIL)
_RECV_OK_RE = re.compile(r"(군요|네요)" + _TAIL)
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
    (r"들을게요", "듣겠습니다"), (r"물을게요", "묻겠습니다"), (r"걸을게요", "걷겠습니다"), (r"도울게요", "돕겠습니다"),   # (P11b-1) ㄷ·ㅂ 불규칙
    (r"둘게요", "두겠습니다"), (r"을게요", "겠습니다"),
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
    (r"건데요[,，]\s*", "것입니다. "),      # (2026-11-12 P11d-4) '…에 관한 건데요, 최근에 …?' → '…에 관한 것입니다. 최근에 …?'(합쇼체 코치의 여는 문장)
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


def _norm(s: str) -> str:
    return re.sub(r"[\s.,!?~'\"“”‘’…·—-]+", "", s or "")


def register_violations(persona_name: str | None, text: str | None, *, scope: str = "all", fixed: list[str] | None = None) -> list[str]:
    """페르소나 말투와 다른 어미로 끝난 문장 목록(섞임). scope="questions" 면 질문 문장과 fixed(고정 문장)만 본다 — 받는 문장은 보지 않는다."""
    from diag_project.services.output_guard import is_question
    reg = register_of(persona_name)
    k = persona_key(persona_name)
    out: list[str] = []
    if reg == "mixed":
        return out
    fixed_n = {_norm(f) for f in (fixed or []) if f}
    strict = scope == "strict"
    for s in split_sentences(text or ""):
        s = s.strip()
        if not s:
            continue
        if scope == "questions" and not (is_question(s) or _norm(s) in fixed_n):
            continue
        core = s.rstrip(".?!…~\"'”’ ")
        if (_PLAIN_END_RE.search(s) and not s.rstrip().endswith("?")) or _HEARSAY_END_RE.search(s):
            out.append(s)
            continue
        if reg in ("formal", "terse"):
            bad = bool(_POLITE_END_RE.search(s)) or bool(_POLITE_MID_RE.search(s))
            if bad and k == "Daniel" and _DANIEL_OK_RE.search(s) and not _POLITE_MID_RE.search(s):
                bad = False
            # (승인 조건 1) '~군요/~네요'로 끝나는 평서문(받는 문장)은 합쇼체 코치에게도 허용 — 문장 가운데의 '~군요,' 연결도 그대로 둔다
            #   (P10-4) strict(여는 문장·범위 문장·다리)에서는 면제하지 않는다
            if bad and not strict and _RECV_OK_RE.search(s) and not s.rstrip().endswith("?"):
                bad = False
            if bad and reg == "terse" and _LUCAS_OK_RE.search(s) and not _POLITE_MID_RE.search(s):
                bad = False
            if bad:
                out.append(s)
        else:
            if _FORMAL_Q_RE.search(core + ("?" if s.rstrip().endswith("?") else "")) and s.rstrip().endswith("?"):
                out.append(s)
            elif s.rstrip().endswith("니까?") and len(core) >= 3 and "가" <= core[-3] <= "힣" and (ord(core[-3]) - 0xAC00) % 28 == 17:
                out.append(s)                                          # (P11b-1) '합니까?'·'이끕니까?' — 종전 식의 'ㅂ니까' 는 낱자라 걸리지 않았다
            elif strict and is_formal_statement(s):
                out.append(s)
    return out


def is_formal_statement(sentence: str | None) -> bool:
    """평서문이 합쇼체('~습니다/~ㅂ니다/~십시오')로 끝나는가 — '니다' 앞 글자에 ㅂ 받침이 있거나 '습니다', 또는 '~시오'."""
    body = (sentence or "").strip().rstrip(".?!…~\"'”’ ")
    if (sentence or "").rstrip().endswith("?"):
        return False
    if body.endswith(("십시오", "시오")):
        return True
    if not body.endswith("니다") or len(body) < 3:
        return False
    ch = body[-3]
    return "가" <= ch <= "힣" and (ord(ch) - 0xAC00) % 28 == 17


def register_hint(persona_name: str | None) -> str:
    """LLM 집중 호출(여는 문장·슬롯·받기)에 넘기는 말투 지시 한 줄."""
    reg = register_of(persona_name)
    if reg == "formal":
        return "합쇼체 — 문장은 '~습니다', 질문은 '~습니까?'로 끝낸다. '~요'로 끝내지 않는다."
    if reg == "mixed":
        return "짧은 단문 존댓말 — 군말·호칭 없이."
    return "해요체 — 문장은 '~요', 질문은 '~요?'로 끝낸다. '~습니다/~습니까'로 끝내지 않는다."


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
        # (2026-11-12 P11 시뮬 p11a) '떠오르시나요?' → '떠오르시습니까?' 로 깨졌다 — '~시나요/~신가요' 는 '~십니까' 로
        for pat, rep in ((r"계세요$", "계십니까"), (r"어떨까요$", "어떻습니까"), (r"주시겠어요$", "주시겠습니까"), (r"으세요$", "으십니까"), (r"세요$", "십니까"),
                         (r"시나요$", "십니까"), (r"신가요$", "십니까"), (r"시는가요$", "십니까")):
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
    # (2026-11-12 P11b-1) '~어요/~아요' 류 — 불규칙 용언 표로(만들어요 → 만듭니다 · 떠올라요 → 떠오릅니다 · 어려워요 → 어렵습니다 · 써요 → 씁니다). 표에 없으면 그대로
    from diag_project.services.conjugation import L_STEMS_LONG as _LSL, polite_statement_to_formal as _pstf
    new = _pstf(body)
    if new:
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
        # (P11b-1) ㄹ 어간은 받침이 어간의 것이다 — '만들게요' → '만들겠습니다'('만드겠습니다' 아님). 어느 쪽인지 모르는 한 글자 어간('살게요')은 그대로 둔다
        _stem_g = body[:-2]
        _eoj_g = _stem_g.split()[-1] if _stem_g.split() else ""
        if _stem_g.endswith(_LSL) or _eoj_g in ("열", "풀", "팔", "놀", "울", "돌", "밀", "알"):
            return _stem_g + "겠습니다" + (punct or ".")
        if _eoj_g in ("살", "끌", "들", "걸", "늘", "달", "길", "벌"):
            return t
        c = ord(body[-3]) - 0xAC00
        return body[:-3] + chr(0xAC00 + c - 8) + "겠습니다" + (punct or ".")
    if body.endswith("세요"):
        return body[:-2] + "십니다" + (punct or ".")
    return t


# (2026-11-11 P10-4) 합쇼체 평서문 → 해요체. 아는 꼴(표) → 불규칙 예외 → 규칙(모음 어간 ㅂ니다·받침 어간 습니다) 순서. 모르는 꼴은 그대로 둔다(호출자 폴백).
_TO_POLITE_STMT: list[tuple[str, str]] = [
    (r"려고 합니다", "려고 해요"), (r"려 합니다", "려고 해요"),
    (r"보겠습니다", "볼게요"), (r"하겠습니다", "할게요"), (r"드리겠습니다", "드릴게요"), (r"가겠습니다", "갈게요"), (r"듣겠습니다", "들을게요"),
    (r"여쭙겠습니다", "여쭤볼게요"), (r"묻겠습니다", "물어볼게요"), (r"두겠습니다", "둘게요"),
    (r"것입니다", "거예요"), (r"겁니다", "거예요"), (r"아닙니다", "아니에요"),
    (r"싶습니다", "싶어요"), (r"있습니다", "있어요"), (r"없습니다", "없어요"), (r"같습니다", "같아요"),
    (r"(았|었|였|했|셨|겠)습니다", r"\1어요"),
    (r"다릅니다", "달라요"), (r"합니다", "해요"), (r"됩니다", "돼요"), (r"드립니다", "드려요"), (r"십니다", "세요"),
    (r"주십시오", "주세요"), (r"하십시오", "하세요"), (r"십시오", "세요"),
]
_POLITE_IRREGULAR: dict[str, str] = {
    "만듭니다": "만들어요", "압니다": "알아요", "엽니다": "열어요", "늡니다": "늘어요", "듭니다": "들어요", "이끕니다": "이끌어요", "끕니다": "끌어요",
    "풉니다": "풀어요", "따릅니다": "따라요", "듣습니다": "들어요", "묻습니다": "물어요", "걷습니다": "걸어요", "깨닫습니다": "깨달아요",
    "그렇습니다": "그래요", "이렇습니다": "이래요", "어떻습니다": "어때요", "낫습니다": "나아요", "짓습니다": "지어요", "잇습니다": "이어요",
    "돕습니다": "도와요", "곱습니다": "고와요", "마십니다": "마셔요", "치릅니다": "치러요", "들릅니다": "들러요", "다다릅니다": "다다라요",
    "이릅니다": "이릅니다", "푸릅니다": "푸릅니다",      # 어느 활용인지 모르는 꼴 — 바꾸지 않는다
    # '~이다' 로 끝나는 동사(명사+입니다 와 꼴이 같다) — 보이다·줄이다·높이다 …
    "보입니다": "보여요", "줄입니다": "줄여요", "높입니다": "높여요", "붙입니다": "붙여요", "움직입니다": "움직여요", "기울입니다": "기울여요",
    "들입니다": "들여요", "쓰입니다": "쓰여요", "놓입니다": "놓여요", "섞입니다": "섞여요", "쌓입니다": "쌓여요", "모입니다": "모여요",
}
_REGULAR_B_STEMS = set("잡입좁뽑씹접집업")


def _jamo(ch: str) -> tuple[int, int, int]:
    code = ord(ch) - 0xAC00
    return code // 588, (code // 28) % 21, code % 28


def _compose(cho: int, jung: int, jong: int = 0) -> str:
    return chr(0xAC00 + cho * 588 + jung * 28 + jong)


def _polite_stmt(body: str) -> str | None:
    """합쇼체 평서문 몸통(문장부호 제외) → 해요체. 못 바꾸면 None."""
    # (P11b-1) 불규칙 표를 먼저 본다 — '마십니다' 가 '십니다 → 세요' 줄에 걸려 '마세요' 가 되던 것
    for k_, v_ in sorted(_POLITE_IRREGULAR.items(), key=lambda kv: -len(kv[0])):
        if body.endswith(k_):
            return body[: -len(k_)] + v_
    for pat, rep in _TO_POLITE_STMT:
        new = re.sub(pat + "$", rep, body)
        if new != body:
            return new
    if body.endswith("입니다") and len(body) >= 4 and "가" <= body[-4] <= "힣":
        return body[:-3] + ("이에요" if _has_batchim(body[-4]) else "예요")
    if body.endswith("습니다") and len(body) >= 4 and "가" <= body[-4] <= "힣":
        stem = body[:-3]
        cho, jung, jong = _jamo(stem[-1])
        if jong == 17 and stem[-1] not in _REGULAR_B_STEMS:           # ㅂ 불규칙: 어렵습니다 → 어려워요
            return stem[:-1] + _compose(cho, jung) + "워요"
        return stem + ("아요" if jung in (0, 2, 8) else "어요")          # 좋습니다 → 좋아요, 먹습니다 → 먹어요
    if body.endswith("니다") and len(body) >= 3 and "가" <= body[-3] <= "힣":
        cho, jung, jong = _jamo(body[-3])
        if jong != 17:
            return None
        head = body[:-3]
        if jung == 18 and cho == 5 and head and "가" <= head[-1] <= "힣" and _jamo(head[-1])[2] == 0:   # 르 불규칙: 고릅니다 → 골라요
            pc, pj, _ = _jamo(head[-1])
            return head[:-1] + _compose(pc, pj, 8) + ("라요" if pj in (0, 8) else "러요")
        if jung in (0, 1, 4, 5, 6):                                    # 가/내/서/세/펴 + 요
            return head + _compose(cho, jung) + "요"
        if jung == 18:
            # (P11b-1) ㅡ 탈락 — 앞 음절의 모음을 따른다: 바쁩니다 → 바빠요, 아픕니다 → 아파요, 기쁩니다 → 기뻐요, 씁니다 → 써요
            _pj = _jamo(head[-1])[1] if (head and "가" <= head[-1] <= "힣") else -1
            return head + _compose(cho, 0 if _pj in (0, 8) else 4) + "요"
        nxt = {8: 9, 13: 14, 20: 6}.get(jung)                          # ㅗ→ㅘ, ㅜ→ㅝ, ㅣ→ㅕ
        if nxt is not None:
            return head + _compose(cho, nxt) + "요"
        if jung == 16:                                                 # 쉬 + 어요
            return head + _compose(cho, jung) + "어요"
    return None


def _politen_sentence(s: str) -> str:
    t = s.strip()
    if not t.endswith("?"):
        m = re.search(_TAIL, t)
        punct = m.group("p") if m else ""
        body = t[: len(t) - len(punct)] if punct else t
        new = _polite_stmt(body) if is_formal_statement(t) else None
        return (new + (punct or ".")) if new else s
    for pat, rep in _TO_POLITE_Q:
        new = re.sub(pat, rep, t)
        if new != t:
            return new
    from diag_project.services.conjugation import formal_question_to_polite as _fqtp
    return _fqtp(t) or s                                               # (P11b-1) '합니까?' → '하나요?', '이끕니까?' → '이끄나요?' 


def apply_register(persona_name: str | None, text: str | None, *, scope: str = "all", fixed: list[str] | None = None) -> tuple[str, int, list[str]]:
    """말투가 섞인 문장을 어미표로 교정한다. (결과, 고친 문장 수, 그래도 남은 위반 문장). scope·fixed 는 register_violations 와 같다."""
    src = text or ""
    bad = register_violations(persona_name, src, scope=scope, fixed=fixed)
    if not bad:
        return src, 0, []
    reg = register_of(persona_name)
    out, n = src, 0
    for s in bad:
        _plain = (_PLAIN_END_RE.search(s) and not s.rstrip().endswith("?")) or _HEARSAY_END_RE.search(s)
        new = _formalize_sentence(s) if (reg in ("formal", "terse") or _plain) else _politen_sentence(s)
        from diag_project.services.conjugation import safe as _safe_conj
        new = _safe_conj(s, new)                                       # (P11b-1) 변환 결과가 틀린 활용 꼴이면 원문 유지
        if new != s:
            out = out.replace(s, new, 1)
            n += 1
    return out, n, register_violations(persona_name, out, scope=scope, fixed=fixed)
