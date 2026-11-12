"""(2026-11-12 P11b-1) 어미 변환의 활용 규칙 — 불규칙 용언 표, 해요체↔합쇼체 변환, 결과 검사. 순수 함수, LLM 없음.

11/12 시뮬 p11a: '떠오르시나요?' → '떠오르시습니까?'(어미표의 '나요→습니까' 가 받침 없는 어간에도 붙었다), '교육팀을 이끄고 계시는군요'(ㄹ 탈락을
'고' 앞에까지 적용 — 이것은 변환이 아니라 LLM 출력이었다. 프롬프트 예시 '이끄시는군요'·'맡고 계시는군요' 두 개를 섞었다).
원칙: 표(이 파일)에 있는 꼴만 바꾼다. 표에 없거나 결과가 틀린 꼴(bad_form)이면 바꾸지 않고 원문을 둔다(safe).
  ㄹ 탈락   이끌다·만들다·알다·들다 — ㄴ·ㅂ·ㅅ·오 앞에서 ㄹ 이 빠진다(이끕니다·이끄시는·이끄나요). 그 밖(고·지·게·면·어)에서는 남는다(이끌고).
  르 불규칙  떠오르다·고르다 — 떠올라요·골라요 / 떠오릅니다·고릅니다
  ㅂ 불규칙  어렵다·쉽다·돕다 — 어려워요·도와요 / 어렵습니다·돕습니다
  ㅡ 탈락   쓰다·크다·바쁘다 — 써요·커요·바빠요 / 씁니다·큽니다·바쁩니다
  하다류     해요 / 합니다
"""
from __future__ import annotations

import re

_BASE = 0xAC00
JONG_L, JONG_B, JONG_N, JONG_SS = 8, 17, 4, 20


def is_hangul(ch: str) -> bool:
    return bool(ch) and "가" <= ch <= "힣"


def jamo(ch: str) -> tuple[int, int, int]:
    code = ord(ch) - _BASE
    return code // 588, (code // 28) % 21, code % 28


def compose(cho: int, jung: int, jong: int = 0) -> str:
    return chr(_BASE + cho * 588 + jung * 28 + jong)


def jong_of(ch: str) -> int:
    return jamo(ch)[2] if is_hangul(ch) else -1


def with_jong(ch: str, jong: int) -> str:
    cho, jung, _ = jamo(ch)
    return compose(cho, jung, jong)


# ── 표 ──────────────────────────────────────────────────────────────────────
# ㄹ 탈락 어간 — 긴 것은 어절 어디서나, 한 글자는 어절 첫머리에서만 본다(다른 낱말 속 글자와 구분이 안 된다).
L_STEMS_LONG: tuple[str, ...] = ("이끌", "만들", "힘들", "흔들", "떠들", "거들", "곁들", "받들")
L_STEMS_SHORT: tuple[str, ...] = ("알", "들", "늘", "줄", "열", "풀", "살", "팔", "놀", "울")
_L_LONG = "|".join(L_STEMS_LONG)
_L_LONG_DROPPED = "|".join(s[:-1] + with_jong(s[-1], 0) for s in L_STEMS_LONG)      # 이끄|만드|힘드…
# ㅂ 불규칙 — '워요' 앞 꼴(받침 뺀 어간): 어려워요 → 어렵습니다. '~스럽다'·'~롭다' 는 규칙으로 본다.
B_IRREGULAR_OPEN: tuple[str, ...] = ("어려", "쉬", "고마", "반가", "가까", "무거", "가벼", "즐거", "아쉬", "놀라", "두려", "부러", "아름다", "어두", "더", "추",
                                     "매", "미", "시끄러", "부끄러", "서러", "안타까", "새로", "까다로", "번거로", "외로", "괴로", "이로", "해로", "날카로", "흥미로")
_B_ADJ = ("어렵", "쉽", "고맙", "반갑", "가깝", "무겁", "가볍", "즐겁", "아쉽", "놀랍", "두렵", "부럽", "아름답", "어둡", "덥", "춥", "맵", "밉", "새롭",
          "까다롭", "번거롭", "외롭", "괴롭", "돕", "곱")
# 르 불규칙 — 'ㄹ라요/ㄹ러요' 의 앞 음절(받침 ㄹ) → 받침 뺀 음절 + '릅니다'
REU_IRREGULAR: dict[str, str] = {"올라요": "오릅니다", "골라요": "고릅니다", "몰라요": "모릅니다", "달라요": "다릅니다", "빨라요": "빠릅니다", "잘라요": "자릅니다",
                                 "불러요": "부릅니다", "눌러요": "누릅니다", "길러요": "기릅니다", "흘러요": "흐릅니다", "둘러요": "두릅니다", "물러요": "무릅니다"}
# ㅡ 탈락·그 밖의 줄어든 꼴 — 어절 끝이 이 꼴일 때만
CONTRACTED: dict[str, str] = {
    "써요": "씁니다", "커요": "큽니다", "꺼요": "끕니다", "떠요": "뜹니다", "바빠요": "바쁩니다", "아파요": "아픕니다", "나빠요": "나쁩니다", "고파요": "고픕니다",
    "기뻐요": "기쁩니다", "슬퍼요": "슬픕니다", "예뻐요": "예쁩니다", "모아요": "모읍니다", "따라요": "따릅니다", "치러요": "치릅니다", "들러요": "들릅니다",
    "나아요": "낫습니다", "도와요": "돕습니다", "고와요": "곱습니다", "놔요": "놓습니다", "어때요": "어떻습니다", "그래요": "그렇습니다", "이래요": "이렇습니다",
    "해요": "합니다", "돼요": "됩니다", "봐요": "봅니다", "내요": "냅니다",
    "줘요": "줍니다", "나눠요": "나눕니다", "바꿔요": "바꿉니다", "배워요": "배웁니다", "세워요": "세웁니다", "채워요": "채웁니다", "키워요": "키웁니다",
    "싸워요": "싸웁니다", "외워요": "외웁니다", "지워요": "지웁니다", "미뤄요": "미룹니다", "이뤄요": "이룹니다", "맞춰요": "맞춥니다", "갖춰요": "갖춥니다",
    "낮춰요": "낮춥니다", "늦춰요": "늦춥니다", "멈춰요": "멈춥니다", "둬요": "둡니다", "거둬요": "거둡니다",
    "만나요": "만납니다", "떠나요": "떠납니다", "끝나요": "끝납니다", "일어나요": "일어납니다", "나타나요": "나타납니다", "지나요": "지납니다",
    "드러나요": "드러납니다", "바라요": "바랍니다", "모자라요": "모자랍니다", "자라요": "자랍니다",
}
# '~는지' 가 아니라 '~은지' 를 쓰는 형용사 어간(받침 있음) · ㅎ 불규칙
ADJ_STEMS: tuple[str, ...] = ("좋", "같", "많", "싫", "작", "높", "낮", "깊", "넓", "좁", "짧", "괜찮", "옳", "젊", "굵", "얇")   # '적다'·'늦다' 는 동사와 꼴이 같아 뺀다
H_ADJ: dict[str, str] = {"어떻": "어떤", "그렇": "그런", "이렇": "이런", "저렇": "저런"}
VERB_STEMS: tuple[str, ...] = ("먹", "읽", "듣", "묻", "받", "믿", "찾", "잡", "앉", "남", "넘", "맡", "막", "닫", "얻", "웃", "돕", "놓", "넣", "낳", "쌓", "잇",
                               "짓", "벗", "씻", "깨닫", "붙", "맞", "갖", "겪", "닦", "묶", "섞", "참", "감", "숨", "심", "안", "신", "앓", "잃", "끓", "꿇")


# ── 결과 검사 ───────────────────────────────────────────────────────────────
_BAD_FIXED_RE = re.compile(
    rf"(?P<l_kept>(?:{_L_LONG})(?:나요|네요|는군요|는지|는|세요|십니|시는|시나|신가|신지|으세요|으시|으십|으셨|을까|을지|습니))"
    rf"|(?P<l_kept_s>(?<![가-힣])(?:{'|'.join(L_STEMS_SHORT)})(?:나요|네요|는군요|세요\b|십니|시나요|신가요|습니))"
    rf"|(?P<l_dropped>(?:{_L_LONG_DROPPED})(?:고|지|게|면|어|었|겠|자|기|던|도록|다가|려))"
    r"|(?P<reu>[가-힣]르(?:어요|었|아요|았))"
    rf"|(?P<b_irr>(?:{'|'.join(_B_ADJ)})(?:어요|아요|었|았|으세요|으시|으십|은지|은가|을까|으면|으니)|(?:{'|'.join(a for a in _B_ADJ if a != '돕')})는지)"
    r"|(?P<eu>(?:쓰|크|끄|뜨|바쁘|아프|나쁘|고프|기쁘|슬프|예쁘|모으|따르|치르|담그|잠그)(?:어요|아요|었|았)|(?:바뻐|아퍼|나뻐|고퍼)요)"
    r"|(?P<ha>하(?:아요|어요|았|었)|해습니|해십니)"
    rf"|(?P<neunji>(?:{'|'.join(ADJ_STEMS)}|어떻|그렇|이렇)는지)"
    r"|(?P<si_dup>시(?:습니|십니다|시는))")


def bad_form(text: str | None) -> str | None:
    """틀린 활용 꼴이 있으면 그 종류, 없으면 None. 변환 결과를 내보내기 전에 본다.
    'seup'(받침 없는 음절·ㄹ 받침 뒤의 '습니다/습니까'), 'eu_insert'(받침 없는 음절 뒤의 '을까요/으세요'), 그 밖은 표의 꼴."""
    t = text or ""
    m = _BAD_FIXED_RE.search(t)
    if m:
        return m.lastgroup
    for m in re.finditer(r"([가-힣])습니(?:다|까)", t):
        if jong_of(m.group(1)) in (0, JONG_L):
            return "seup"                          # 떠오르습니까 · 만들습니다 · 하습니다
    for m in re.finditer(r"([가-힣])(?:을까요|을지|으십니|으세요|으셨)", t):
        if jong_of(m.group(1)) == 0:
            return "eu_insert"                     # 하을까요 · 고르으세요
    return None


def safe(original: str, converted: str) -> str:
    """변환 결과가 틀린 꼴이면(원문에는 없던 틀린 꼴) 원문을 그대로 둔다."""
    if converted == original:
        return original
    bad = bad_form(converted)
    return original if (bad and bad_form(original) != bad) else converted


# ── LLM 출력의 ㄹ 탈락 오류 수선 ────────────────────────────────────────────
_L_DROPPED_FIX_RE = re.compile(rf"({_L_LONG_DROPPED})(?=(?:고|지|게|면|어|었|겠|자|기|던|도록|다가|려)(?:[\s,.?!]|[가-힣]))")
_L_KEPT_FIX_RE = re.compile(rf"({_L_LONG})(?=(?:나요|네요|는군요|세요|십니|시는|시나|신가|신지|셨))")


def repair_l_stem(text: str | None) -> tuple[str, int]:
    """'이끄고 계시는군요' → '이끌고 계시는군요', '만들시는' → '만드시는'. 긴 ㄹ 어간(이끌·만들·힘들·흔들·떠들…)만. (결과, 고친 수)"""
    t = text or ""
    n = 0

    def _add(m: re.Match) -> str:
        nonlocal n
        s = m.group(1)
        n += 1
        return s[:-1] + with_jong(s[-1], JONG_L)

    def _drop(m: re.Match) -> str:
        nonlocal n
        s = m.group(1)
        n += 1
        return s[:-1] + with_jong(s[-1], 0)
    t = _L_DROPPED_FIX_RE.sub(_add, t)
    t = _L_KEPT_FIX_RE.sub(_drop, t)
    return t, n


# ── 어간 + 어미 ─────────────────────────────────────────────────────────────
def attach_b(stem: str, tail: str = "니다") -> str | None:
    """어간 + 'ㅂ니다/ㅂ니까' — 받침 없는 어간·ㄹ 어간은 ㅂ 받침을 얹고(하 → 합니다, 만들 → 만듭니다), 그 밖은 '습' 을 붙인다(먹 → 먹습니다)."""
    stem = (stem or "").rstrip()
    if not stem or not is_hangul(stem[-1]):
        return None
    j = jong_of(stem[-1])
    if j in (0, JONG_L):
        return stem[:-1] + with_jong(stem[-1], JONG_B) + tail
    return stem + "습" + tail


def _ends_long_l(stem: str) -> bool:
    return stem.endswith(L_STEMS_LONG)


def _eojeol(body: str) -> str:
    return (body or "").split()[-1] if (body or "").split() else ""


def polite_question_to_formal(body: str) -> str | None:
    """해요체 질문 몸통(물음표 제외) → 합쇼체 질문 몸통. 표에 없는 꼴이면 None(호출자는 원문을 둔다)."""
    b = (body or "").rstrip()
    if len(b) < 3:
        return None
    for src, dst in (("아니에요", "아닙니까"), ("거예요", "것입니까"), ("건가요", "것입니까"), ("이에요", "입니까"), ("예요", "입니까"), ("인가요", "입니까"),
                     ("어떤가요", "어떻습니까"), ("그런가요", "그렇습니까"), ("어때요", "어떻습니까"), ("그래요", "그렇습니까"),
                     ("해요", "합니까"), ("돼요", "됩니까"), ("봐요", "봅니까"), ("줘요", "줍니까")):
        if b.endswith(src):
            return b[: -len(src)] + dst
    if b.endswith("나요"):
        stem = b[:-2]
        if not stem or not is_hangul(stem[-1]) or jong_of(stem[-1]) == JONG_L:
            return None                            # '만들나요' 는 원문이 이미 틀렸다 — 건드리지 않는다
        return attach_b(stem, "니까")              # 떠오르나요 → 떠오릅니까 · 아시나요 → 아십니까 · 먹나요 → 먹습니까
    if b.endswith("운가요") and len(b) >= 4 and jong_of(b[-4]) == 0:
        return b[:-4] + with_jong(b[-4], JONG_B) + "습니까"         # 어려운가요 → 어렵습니까
    if b.endswith("은가요") and len(b) >= 4 and jong_of(b[-4]) not in (0, -1):
        return b[:-3] + "습니까"                   # 좋은가요 → 좋습니까
    if b.endswith("는가요") and len(b) >= 4:
        return attach_b(b[:-3], "니까")            # 하는가요 → 합니까 · 먹는가요 → 먹습니까
    if b.endswith("가요") and len(b) >= 3 and jong_of(b[-3]) == JONG_N and b[-3] not in "던런떤언":
        return b[:-3] + with_jong(b[-3], JONG_B) + "니까"            # 큰가요 → 큽니까 · 바쁜가요 → 바쁩니까 · 힘든가요 → 힘듭니까
    if b.endswith(("어요", "아요")):
        stem = b[:-2]
        if not stem or not is_hangul(stem[-1]):
            return None
        j = jong_of(stem[-1])
        if j == JONG_L:
            if _ends_long_l(stem) or _eojeol(stem) == "알":
                return attach_b(stem, "니까")      # 만들어요 → 만듭니까 · 알아요 → 압니까
            return None                            # 들어요(듣다/들다)·걸어요(걷다/걸다) — 어느 쪽인지 모른다
        if j == 0:
            return None
        return stem + "습니까"                     # 먹어요 → 먹습니까 · 좋아요 → 좋습니까 · 했어요 → 했습니까
    if b.endswith("을까요") and len(b) >= 4 and jong_of(b[-4]) not in (0, JONG_L, -1):
        return b[:-3] + "습니까"                   # 좋을까요 → 좋습니까
    return None


def polite_statement_to_formal(body: str) -> str | None:
    """해요체 평서문 몸통(문장부호 제외)의 '~어요/~아요' 류 → 합쇼체. 표에 없는 꼴이면 None."""
    b = (body or "").rstrip()
    if len(b) < 2 or not b.endswith("요"):
        return None
    for src, dst in sorted({**REU_IRREGULAR, **CONTRACTED}.items(), key=lambda kv: -len(kv[0])):
        if b.endswith(src):
            return b[: -len(src)] + dst
    if b.endswith("워요") and len(b) >= 3:
        head = b[:-2]
        if head.endswith(B_IRREGULAR_OPEN) or head.endswith("스러"):
            return head[:-1] + with_jong(head[-1], JONG_B) + "습니다"      # 어려워요 → 어렵습니다
        return None
    if b.endswith("와요") and len(b) >= 3 and is_hangul(b[-3]):
        return b[:-2] + "옵니다"                   # 나와요 → 나옵니다(도와요·고와요 는 위 표)
    if b.endswith(("어요", "아요")):
        stem = b[:-2]
        if not stem or not is_hangul(stem[-1]):
            return None
        j = jong_of(stem[-1])
        if j == JONG_L:
            if _ends_long_l(stem) or _eojeol(stem) == "알":
                return attach_b(stem)              # 만들어요 → 만듭니다 · 알아요 → 압니다
            return None
        if j == 0:
            return None
        return stem + "습니다"                     # 먹어요 → 먹습니다 · 많아요 → 많습니다
    last = b[-2]
    if is_hangul(last) and jong_of(last) == 0 and jamo(last)[1] == 6 and not b.endswith(("이여요", "하여요")):
        cho, _, _ = jamo(last)
        if last in "펴켜":
            return b[:-2] + with_jong(last, JONG_B) + "니다"               # 펴요 → 폅니다
        return b[:-2] + compose(cho, 20, JONG_B) + "니다"                  # 느껴요 → 느낍니다 · 생겨요 → 생깁니다 · 보여요 → 보입니다
    return None


def formal_q_to_nunji(base: str) -> str | None:
    """'…습니까?' → '…는지'/'…은지' 몸통(Daniel 꼬리 변주용, '?' 제외한 '…는지' 까지). 동사·형용사를 표로 가려 붙인다. 모르는 어간이면 None."""
    if not base.endswith("습니까?"):
        return None
    stem = base[:-4]
    if not stem or not is_hangul(stem[-1]):
        return None
    for adj, det in H_ADJ.items():
        if stem.endswith(adj):
            return stem[: -len(adj)] + det + "지"                          # 어떻습니까 → 어떤지
    if jong_of(stem[-1]) == JONG_SS or stem.endswith(("있", "없", "않")):
        return stem + "는지"                                               # 했습니까 → 했는지 · 있습니까 → 있는지
    if stem.endswith(tuple(a for a in _B_ADJ if a not in ("돕", "곱"))):
        return stem[:-1] + with_jong(stem[-1], 0) + "운지"                 # 어렵습니까 → 어려운지
    if stem.endswith(ADJ_STEMS):
        return stem + "은지"                                               # 좋습니까 → 좋은지
    if stem.endswith(VERB_STEMS):
        return stem + "는지"                                               # 먹습니까 → 먹는지
    return None


def formal_question_to_polite(sentence: str) -> str | None:
    """'…ㅂ니까?' → '…나요?' — ㅂ 받침만 떼면 된다(ㄹ 탈락 어간은 '나' 앞에서도 ㄹ 이 빠진다: 이끕니까 → 이끄나요). '습/십/입니까' 는 호출자 표가 맡는다."""
    s = (sentence or "").rstrip()
    if not s.endswith("니까?") or len(s) < 4:
        return None
    for src, dst in (("아닙니까?", "아닌가요?"), ("겁니까?", "건가요?")):
        if s.endswith(src):
            return s[: -len(src)] + dst
    ch = s[-4]
    if not is_hangul(ch) or jong_of(ch) != JONG_B or ch in "습십입":
        return None
    return s[:-4] + with_jong(ch, 0) + "나요?"
