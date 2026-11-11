"""(2026-10-23, 6번 P4) 코치 페르소나 구분 — 사전 질문(앵커·사다리·고정 문장·일반화 탐침)에 거는 결정론 어미 변환 계층.

LLM 이 아니라 규칙이다. 질문의 내용(묻는 대상·시점·행동)은 그대로 두고 어미·호칭·도입구만 바꾼다.
  Ella    부드러운 "~어요?"(기준형, 변환 없음)
  Jessica "~습니까?" 간결 — 완곡·군말 제거
  Olivia  변환 없음(대조 도입구는 실제 대조 질문에만 — LLM 질문 가드가 담당)
  Daniel  격식 "~시겠습니까?"
  Michael '직접' 행동 강조(2026-11-05 P4-2: "좋습니다," 도입은 평가 말투로 전면 금지 — michael_lead_guard 는 떼기만 한다)
  Lucas   최단문, 도입구·호칭 없음
또한 페르소나별 탐침 선호(레이어3 지시)를 둔다.
측정 원칙(묻는 순서·하위역량·예산)은 백엔드가 정하고 여기서는 건드리지 않는다.
"""
from __future__ import annotations

import re

from diag_project.services.intro_messages import persona_key

# (2026-11-11 P10-5) 되받기 마무리 어구 풀(PERSONA_TAILS — '흥미로운 지점이에요', '그 선택이 궤도를 바꿨군요' …)은 전수 삭제했다.
#   어느 답에나 붙는 받기 문구였다. 받기는 직전 답의 내용을 담는다 — 폴백은 receive_check.quote_receive(리더 절 인용).

# ── 탐침 선호(레이어3 지시 문장) ──────────────────────────────────────────────────
PROBE_PREFERENCE: dict[str, str] = {
    "Ella":    "되받기는 관찰 문장 2문장까지 허용(리더가 쓴 명사만). 탐침은 장면·행동을 차분히 따라간다.",
    "Jessica": "되받기는 1문장. 탐침은 숫자·기간·횟수·비율을 먼저 묻는다(언제·며칠·몇 명·몇 %). 완곡어('혹시', '조금')는 쓰지 않는다.",
    # (2026-11-11 P10-2) 대조(가정) 질문은 본 호출이 쓰지 않는다 — 사례 내용을 넣은 한 문장을 slot_render 가 따로 쓴다. 본 호출에 맡기면
    #   '반대로 했다면 어땠을까요?' 처럼 어느 사례에나 붙는 꼴이 나오고, 턴 형식 검사(가정형)와도 부딪혔다.
    "Olivia":  "되받기는 1~2문장. 탐침은 리더가 고른 쪽과 버린 쪽, 그 자리에 있던 다른 사람이 보인 반응을 차례로 따라간다. 가정 질문('~했다면')은 쓰지 않는다.",
    "Daniel":  "되받기는 관찰 문장 2문장까지 허용. 격식 어미('~하셨습니까', '~시겠습니까'). 탐침은 결정의 기준과 책임을 묻는다.",
    "Michael": "되받기는 1~2문장, 짧고 힘 있게. 탐침은 리더가 직접 한 행동을 먼저 묻는다('직접 뭘 하셨어요'). '좋습니다'·'좋은 선택' 같은 평가 리드는 쓰지 않는다 — 사실을 되짚는 문장으로 시작한다.",
    "Lucas":   "되받기는 1문장, 최단문. 도입구·'리더님' 호칭 없이 바로 묻는다. 숫자·기간·결과를 먼저 묻는다.",
}

# 대조 탐침 판정 — 도입구('거꾸로 보면요,')를 뗀 '질문 본문'에 반대 경우·안 했다면·다른 사람이라면이 있을 때만.
_CONTRAST_RE = re.compile(r"(반대로 (했|하셨|갔|가셨|움직)|입장에서는 어떤|거꾸로 (했|하셨|갔|가셨)|안 했다면|않았다면|않으셨다면|하지 않으셨다면|달리 했다면|"
                          r"다른 (사람|분|팀원)이(라면|었다면| 맡았다면)|만약[^?]{0,24}(않|안 )|그러지 않았다면|그대로 두셨다면)")



def is_contrast_question(text: str | None) -> bool:
    """Olivia 대조 탐침('반대로 했다면?') 판정 — 챕터당 1회 집계용. 도입구만으로는 대조가 아니다."""
    body = (text or "").strip()
    return bool(_CONTRAST_RE.search(body))


def preference_for(persona_name: str | None, *, contrast_used: bool = False) -> str:
    k = persona_key(persona_name)
    txt = PROBE_PREFERENCE.get(k, PROBE_PREFERENCE["Ella"])
    return txt   # (P10-2) contrast_used 는 호환용 인자 — 대조 질문은 slot_render 가 챕터당 1회 넣는다


def persona_guide_block(persona_name: str | None, *, contrast_used: bool = False) -> str:
    """레이어3 페르소나 블록 뒤에 붙는 탐침 선호 지시.
    (2026-11-11 P10-5) 마무리 어구를 목록에서 고르라는 지시와 어구 목록을 삭제 — 11/11 운영 세션의 고정 받기 문구는 이 지시가 낸 것이었다.
    (이 docstring 은 누설 사전 소스에 포함되므로 따옴표 인용을 넣지 않는다.)"""
    k = persona_key(persona_name)
    return (f"[🎭 탐침 선호 — {k}] {preference_for(k, contrast_used=contrast_used)}\n"
            "되받기는 리더가 방금 한 말의 내용(리더가 쓴 낱말)을 담아 쓴다. 내용 없이 어느 답에나 붙일 수 있는 한마디로 받지 않는다.\n\n")


# ── 어미 변환 ─────────────────────────────────────────────────────────────────
_OLIVIA_LEADS = ["거꾸로 보면요,", "다른 쪽에서 보면,", "조금 비켜서 보면,", "질문을 뒤집어 볼게요.", "한 발 물러서서요,"]

# (패턴, Jessica, Daniel) — 어미 치환표. 긴 패턴을 먼저 본다.
_ENDINGS: list[tuple[str, str, str]] = [
    (r"있으셨어요\?$",        "있으셨습니까?",          "있으셨는지 말씀해 주시겠습니까?"),
    (r"있었어요\?$",          "있었습니까?",            "있으셨는지 말씀해 주시겠습니까?"),
    (r"있으셨나요\?$",        "있으셨습니까?",          "있으셨는지 말씀해 주시겠습니까?"),
    (r"있었나요\?$",          "있었습니까?",            "있으셨는지 말씀해 주시겠습니까?"),
    (r"있을까요\?$",          "있습니까?",              "있으시겠습니까?"),
    (r"있으세요\?$",          "있습니까?",              "있으신지 말씀해 주시겠습니까?"),
    (r"주시겠어요\?$",        "주시겠습니까?",          "주시겠습니까?"),
    (r"주실 수 있을까요\?$",  "주시겠습니까?",          "주시겠습니까?"),
    (r"하셨어요\?$",          "하셨습니까?",            "하셨는지 말씀해 주시겠습니까?"),
    (r"하셨나요\?$",          "하셨습니까?",            "하셨는지 말씀해 주시겠습니까?"),
    (r"셨어요\?$",            "셨습니까?",              "셨는지 말씀해 주시겠습니까?"),
    (r"였어요\?$",            "였습니까?",              "였는지 말씀해 주시겠습니까?"),
    (r"였나요\?$",            "였습니까?",              "였는지 말씀해 주시겠습니까?"),
    (r"였을까요\?$",          "였습니까?",              "였을지 말씀해 주시겠습니까?"),
    (r"이었어요\?$",          "이었습니까?",            "이었는지 말씀해 주시겠습니까?"),
    (r"어땠어요\?$",          "어땠습니까?",            "어떠하셨는지 말씀해 주시겠습니까?"),
    (r"어땠나요\?$",          "어땠습니까?",            "어떠하셨는지 말씀해 주시겠습니까?"),
    (r"했어요\?$",            "했습니까?",              "했는지 말씀해 주시겠습니까?"),
    (r"됐어요\?$",            "됐습니까?",              "되었는지 말씀해 주시겠습니까?"),
    (r"에요\?$",              "입니까?",                "인지 말씀해 주시겠습니까?"),
    (r"예요\?$",              "입니까?",                "인지 말씀해 주시겠습니까?"),
    (r"어요\?$",              "습니까?",                "는지 말씀해 주시겠습니까?"),
    (r"나요\?$",              "습니까?",                "는지 말씀해 주시겠습니까?"),
    (r"있으신가요\?$",        "있으십니까?",            "있으십니까?"),
    (r"신가요\?$",            "십니까?",                "십니까?"),
    (r"있으실까요\?$",        "있으십니까?",            "있으십니까?"),
    (r"실까요\?$",            "십니까?",                "십니까?"),
    (r"었을까요\?$",          "었습니까?",              "었습니까?"),
    (r"을까요\?$",            "습니까?",                "습니까?"),
    (r"까요\?$",              "까요?",                  "을지 말씀해 주시겠습니까?"),
]
_LUCAS_CUTS = [(r"^(그때|그 당시|최근에|요즘|그중)\s+", ""), (r"\b리더님(은|이|께서|께서는)?\s*", ""), (r"\b직접\s+", ""),
               (r"\s*같이\s+", " "), (r",\s*최근에\s+", " 최근 "), (r"^(혹시|조금|한번|한 번)\s+", ""),
               # (2026-10-28 P0-3) 어미는 '~나요?' 로 통일 — '~죠?' 는 확인 질문으로 읽혀 린트 (c) 에 걸린다. 짧게 자르는 것이 Lucas 의 표식.
               (r"하신 적이 있었어요\?$", "하신 적 있나요?"), (r"적이 있었어요\?$", "적 있나요?"),
               (r"일이 있었어요\?$", "일 있었나요?"), (r"게 있었어요\?$", "게 있었나요?"), (r"있으셨어요\?$", "있었나요?"), (r"있었어요\?$", "있었나요?"),
               (r"무엇이었어요\?$", "뭐였나요?"), (r"무엇을\s+", "뭘 "), (r"어떻게 하셨어요\?$", "어떻게 하셨나요?"), (r"이었어요\?$", "이었나요?"),
               (r"였어요\?$", "였나요?"), (r"어땠어요\?$", "어땠나요?"), (r"됐어요\?$", "됐나요?"), (r"고치셨어요\?$", "고쳤나요?"),
               (r"있으세요\?$", "있나요?"), (r"있으실까요\?$", "있나요?"), (r"있으신가요\?$", "있었나요?"),
               # 사전 문장이 이미 '~나요?' 면 Ella 와 겹친다 → 존재 질문은 '있었나요?', '어떤'→'무슨', 행동 질문은 '대응'으로 좁힌다
               (r"있으셨나요\?$", "있었나요?"), (r"어떤 일이었나요\?$", "무슨 일이었나요?"), (r"어떤 상황이었나요\?$", "무슨 상황이었나요?"),
               (r"어떻게 하셨나요\?$", "어떻게 대응하셨나요?"),
               (r"이었을까요\?$", "이었나요?"), (r"었을까요\?$", "었나요?"), (r"을까요\?$", "나요?"), (r"어요\?$", "나요?")]


# (2026-10-28 P0-3) Olivia·Michael 어미표 — 사전 문장(Ella 기본형 '~어요?')에서 변환. 순서대로 첫 일치만 적용.
_OLIVIA_ENDINGS = [
    (r"있으셨어요\?$", "있으셨을까요?"), (r"있었어요\?$", "있었을까요?"), (r"있었나요\?$", "있었을까요?"),
    (r"있으셨나요\?$", "있으셨을까요?"), (r"있으세요\?$", "있을까요?"), (r"주시겠어요\?$", "주실 수 있을까요?"),
    (r"하셨어요\?$", "하셨을까요?"), (r"하셨나요\?$", "하셨을까요?"), (r"셨어요\?$", "셨을까요?"),
    (r"이었어요\?$", "이었을까요?"), (r"였어요\?$", "였을까요?"), (r"였나요\?$", "였을까요?"),
    (r"어땠어요\?$", "어땠을까요?"), (r"어땠나요\?$", "어땠을까요?"), (r"했어요\?$", "했을까요?"),
    (r"됐어요\?$", "됐을까요?"), (r"에요\?$", "일까요?"), (r"예요\?$", "일까요?"), (r"어요\?$", "을까요?"),
    (r"나요\?$", "을까요?"), (r"신가요\?$", "실까요?"), (r"습니까\?$", "을까요?"),
    # 사전 문장이 이미 '~을까요?' 면 '~나요?' 로(Ella 기본형과 같은 문장이 나가지 않게).
    #   (2026-11-11 P10-4) 종전 '~을지요?'('어떤 일이었을지요?')는 Olivia 의 해요체 결과 맞지 않아 폐기.
    (r"있으실까요\?$", "있으세요?"), (r"어떤 일이었을까요\?$", "어떤 일이었는지 들려주실래요?"), (r"었을까요\?$", "었나요?"), (r"을까요\?$", "나요?"),
]
# (2026-11-04 P3-4 2차) Michael 은 요청형 — 질문을 '들려주세요' 청유로 바꾼다. 사용자 결정: 구어체 '~어요?'는 Ella 와 겹쳐 폐기.
#   구조 규칙(_michael_request): 존재 질문 '…하신 적/일, 최근에 있으셨어요?' → '최근에 …하셨던 일, 하나만 들려주세요.'
#   '어떤 일이었어요?' → '어떤 일이었는지 들려주세요.' · '어떻게 하셨어요?' → '그때 어떻게 하셨는지 들려주세요.' · '어떻게 됐어요?' → '그 뒤 어떻게 됐는지도요.'
#   구조에 안 맞는 나머지는 아래 어미표로 '…는지 들려주세요.' 일반 변환. 물음표가 없어도 output_guard.is_question 이 간접 질문으로 인식한다.
_MICHAEL_ENDINGS = [
    (r"어땠(어요|나요|습니까|을까요)\?$", "어땠는지 들려주세요."),
    (r"(있으셨|있었|없었|없으셨)(어요|나요|습니까|을까요)\?$", "\\1는지 들려주세요."),
    (r"(있으세요|있으신가요|있으실까요|있을까요|있나요|있어요|있습니까)\?$", "있었는지 들려주세요."),
    (r"(셨|했|됐|였)(어요|나요|습니까|을까요)\?$", "\\1는지 들려주세요."),
    (r"(입니까|예요|에요|인가요|일까요)\?$", "인지 들려주세요."),
    (r"(세요|십니까|신가요|실까요)\?$", "신지 들려주세요."),
]
_MQ_TIME = r"(?:최근에|근래에|요즘|올해 들어|지난 몇 달 사이에|최근|작년에|이번 달에)"
_MQ_EXIST = r"(?:있으셨어요|있으세요|있으셨나요|있으신가요|있으실까요|있었어요|있었나요|있었을까요|있으셨습니까|있었습니까|있습니까|있으셨을까요)"
_MQ_HEAD = r"(?P<head>일|적|경험|결정|행동|순간|장면|시도|게|것)"
_MQ_EXIST_RE = re.compile(r"^(?P<pre>.*?)(?P<verb>\S*?)(?P<nm>셨던|신|싶은|던)\s+" + _MQ_HEAD + r"(?:이|을|,)?\s*(?P<time>" + _MQ_TIME + r")?\s*" + _MQ_EXIST + r"\?$")
_MQ_WHAT_RE = re.compile(r"어떤 (?P<n>일|상황|장면)이었(?:을까요|나요|어요|습니까)\?$")
_MQ_HOW_RE = re.compile(r"어떻게 (?P<v>\S*셨)(?:어요|나요|습니까|을까요)\?$")
_MQ_RESULT_RE = re.compile(r"어떻게 됐(?:어요|나요|습니까|을까요)\?$")


# (2026-11-04 P3 3차) 앵커 꼬리 3종 순환 — Michael: '하나만 들려주세요.' / '떠오르는 게 있으세요?' / '기억나는 일 있으면 얘기해 주세요.'
#   '…는지 들려주세요.' 꼴은 '…는지 떠오르는 대로 말씀해 주세요.' / '…는지 기억나는 대로 얘기해 주세요.' 로.
_MQ_EXIST_TAILS = ("하나만 들려주세요.", "떠오르는 게 있으세요?", "기억나는 일 있으면 얘기해 주세요.")
_MQ_NUNJI_TAILS = ("들려주세요.", "떠오르는 대로 말씀해 주세요.", "기억나는 대로 얘기해 주세요.")


def _michael_request(body: str, variant: int = 0) -> str:
    """Michael 요청형 변환. 구조 규칙 → 어미표 → 변환 불가면 원문. variant 로 꼬리 3종 순환."""
    b = body.strip()
    v = int(variant or 0) % 3
    m = _MQ_RESULT_RE.search(b)
    if m:
        out = b[:m.start()] + "어떻게 됐는지도요."
        out = re.sub(r"^그 뒤에는\s+", "그 뒤 ", out)
        return out if not out.startswith("어떻게") else "그 뒤 " + out
    m = _MQ_WHAT_RE.search(b)
    if m:
        return b[:m.start()] + f"어떤 {m.group('n')}이었는지 {_MQ_NUNJI_TAILS[v]}"
    m = _MQ_HOW_RE.search(b)
    if m:
        out = b[:m.start()] + f"어떻게 {m.group('v')}는지 {_MQ_NUNJI_TAILS[v]}"
        return "그때 " + out if out.startswith("어떻게") and "때" not in b else out
    m = _MQ_EXIST_RE.match(b)
    if m:
        pre, verb, nm, head, time = m.group("pre"), m.group("verb"), m.group("nm"), m.group("head"), m.group("time")
        nm2 = "셨던" if nm == "신" else nm
        head2 = {"적": "일", "게": "것"}.get(head, head)
        if v == 2 and head in ("일", "적") and nm in ("신", "셨던"):
            nm2, head2 = nm, "적"          # '…맞추신 적, 기억나는 일 있으면 얘기해 주세요.' ('일 … 일' 중복 회피)
        if nm in ("싶은", "던") and not verb:
            core = f"{pre}{nm2} {head2}"
        else:
            core = f"{pre}{verb}{nm2} {head2}"
        core = re.sub(r"\s{2,}", " ", core).strip()
        lead = f"{time} " if time and not re.match(r"^" + _MQ_TIME, core) else ""
        return f"{lead}{core}, {_MQ_EXIST_TAILS[v]}"
    for pat, rep in _MICHAEL_ENDINGS:
        if re.search(pat, b):
            out = re.sub(pat, rep, b)
            return out[:-len("들려주세요.")] + _MQ_NUNJI_TAILS[v] if v and out.endswith("들려주세요.") else out
    return body


# (2026-11-04 P3 3차) Ella·Jessica·Olivia·Lucas 의 존재 질문 앵커 꼬리 3종(variant 0 은 기본 어미 그대로).
_EXIST_TAIL_RE = re.compile(r"^(?P<core>.*?(?:일|적|경험|결정|행동|순간|게|것))(?:이|을|,)?\s*(?P<time>최근에|근래에|요즘|올해 들어|지난 몇 달 사이에|최근)?\s*(?P<ex>있[가-힣]*\?)$")
_EXIST_TAILS = {
    "Ella": ("떠오르는 게 있어요?", "기억나는 게 있으면 들려주세요."),
    "Jessica": ("떠오르는 것이 있습니까?", "기억나는 일이 있으면 말씀해 주십시오."),
    "Olivia": ("떠오르는 게 있을까요?", "기억나는 게 있다면 들려주실래요?"),
    "Lucas": ("떠오르는 게 있나요?", "기억나는 일 있으면요?"),
}


def _vary_exist_tail(text: str, key: str, variant: int) -> str:
    v = int(variant or 0) % 3
    if v == 0 or key not in _EXIST_TAILS:
        return text
    m = _EXIST_TAIL_RE.match((text or "").strip())
    if not m:
        return text
    core, time = m.group("core"), m.group("time")
    return f"{core}, {time + ' ' if time else ''}{_EXIST_TAILS[key][v - 1]}"


def _apply_endings(text: str, col: int) -> str:
    for pat, jes, dan in _ENDINGS:
        if re.search(pat, text):
            return re.sub(pat, jes if col == 1 else dan, text)
    return text


DANIEL_VARIANTS = 3


def _daniel(t: str, variant: int) -> str:
    """Daniel 격식 꼬리 3개 변주(2턴 연속 같은 꼬리 금지는 호출자가 variant 를 돌려서 보장)."""
    base = _apply_endings(t, 1)                     # "~습니까?" 형으로 먼저
    v = variant % DANIEL_VARIANTS
    if v == 0:
        out = re.sub(r"입니까\?$", "인지 말씀해 주시겠습니까?", base)
        out = re.sub(r"십니까\?$", "신지 말씀해 주시겠습니까?", out) if out == base else out   # (2026-10-28) '있으십니까?' 도 변주
        out = re.sub(r"습니까\?$", "는지 말씀해 주시겠습니까?", out) if out == base else out
        return out if out != base else base
    if v == 1:
        out = re.sub(r"입니까\?$", "인지요?", base)
        out = re.sub(r"십니까\?$", "신지요?", out) if out == base else out
        out = re.sub(r"습니까\?$", "는지요?", out) if out == base else out
        return out
    return base if "리더님" in base else re.sub(r"^", "리더님께서는 ", base, count=1)


def voice_question(persona_name: str | None, text: str, *, variant: int = 0) -> str:
    """사전 질문 한 문장을 페르소나 어미로. 내용 불변, 물음표 1개 유지. 모르는 페르소나·빈 문장은 그대로.
    variant: Daniel 꼬리 변주 인덱스(호출자가 턴마다 돌린다)."""
    t = (text or "").strip()
    if not t or t.count("?") != 1 or not t.endswith("?"):
        return text
    k = persona_key(persona_name)
    if k == "Ella":
        return _vary_exist_tail(t, k, variant)
    if k == "Olivia":
        # (2026-10-28 P0-3) Olivia 는 '~었을까요?/~을까요?' 의 열린 어미 — Ella(기본 사전 문장)와 같은 문장이 나가지 않게.
        t = re.sub(r"^(혹시|한번|한 번)\s+", "", t)
        for pat, rep in _OLIVIA_ENDINGS:
            if re.search(pat, t):
                return _vary_exist_tail(re.sub(pat, rep, t), k, variant)
        return _vary_exist_tail(t, k, variant)
    if k == "Jessica":
        t = re.sub(r"^(혹시|조금|한번|한 번)\s+", "", t)
        t = t.replace("뭘 ", "무엇을 ").replace("걸 ", "것을 ")
        return _vary_exist_tail(_apply_endings(t, 1), k, variant)
    if k == "Daniel":
        t = t.replace("뭘 ", "무엇을 ").replace("걸 ", "것을 ")
        return _daniel(t, variant)
    if k == "Michael":
        # (2026-11-04 P3-4 2차) Michael 은 요청형 '…하셨던 일, 하나만 들려주세요.' + '직접'. ('~던가요' 회상형·'~어요?' 구어체 모두 폐지.)
        body = re.sub(r"^(좋습니다[,!.]?\s*)", "", t)
        # (2026-10-29 P1-2) 어절 첫머리의 '하신 적'에만 — '전하신 적·조정하신 적·배려하신 적'이 '전직접 하신 적'으로 깨지던 것(p11 Michael 앵커 4종)
        body = re.sub(r"(?<![가-힣])하신 적", "직접 하신 적", body, count=1) if "직접" not in body else body
        return _michael_request(body, variant)
    if k == "Lucas":
        s = t
        for pat, rep in _LUCAS_CUTS:
            s = re.sub(pat, rep, s)
        s = re.sub(r"\s{2,}", " ", s).strip()
        return _vary_exist_tail(s, k, variant) if s.count("?") == 1 else t
    return t


_GOOD_RE = re.compile(r"좋습니다[!,.]?\s*")
_CHEER_RE = re.compile(r"응원합니다")
# (2026-11-02 p2f) 챕터 누적 상한 — p2c Michael 83턴 중 39턴이 '좋습니다'로 시작(2턴에 1회 규칙만으로는 빈도를 못 줄였다).
MICHAEL_GOOD_LEAD_CAP = 3


def michael_lead_guard(text: str, allow: bool, *, add: bool = True) -> tuple[str, bool]:
    """Michael '좋습니다' 도입: 턴당 최대 1회, 허용 턴이면 정확히 1회(없고 add=True 면 붙인다), 비허용 턴이면 전부 뗀다. (텍스트, 사용 여부)
    add=False(라포·인사 등 챕터 밖 턴)에서는 붙이지 않고 중복만 정리한다. 응원 문장이 있는 턴에는 붙이지 않고 전부 뗀다."""
    t = (text or "").strip()
    if not t:
        return text, False
    if _CHEER_RE.search(t):   # (2026-11-02 p2f) '그 선택, 응원합니다. 좋습니다, 다음에…' 금지
        return _GOOD_RE.sub("", t).strip(), False
    n = len(_GOOD_RE.findall(t))
    if not allow:
        return _GOOD_RE.sub("", t).strip(), False
    if n == 0:
        return (f"좋습니다, {t}", True) if add else (t, False)
    first = _GOOD_RE.search(t)
    rest = _GOOD_RE.sub("", t[first.end():])
    return (t[:first.start()] + "좋습니다, " + rest).strip(), True


def restore_slot_sentence(reply: str, persona: str | None, slot_text: str | None) -> tuple[str, bool]:
    """(2026-11-02 p2c) 페르소나 슬롯 고정 문장 복원. 반환 (본문, 복원 여부).

    8-n·8-o·8-p 가 본문을 바꾸면 슬롯 문장이 빠진다(p2c 24세션: Michael 16/25·Jessica 5/25·Daniel 4/25).
    Olivia 는 최종 본문에 대조 질문이 남아 있으면 그대로, Daniel 은 관찰 1문장을 되받기 뒤에, Michael 응원 턴은 되받기 뒤에 응원 문장
    (되받기가 없으면 넣지 않음), 그 밖(실행 의지 질문 턴 포함)은 첫 되받기 1문장 + 슬롯 질문. (이 docstring 은 누설 사전 소스에 포함되므로 코치 발화 어휘를 넣지 않는다.)"""
    from diag_project.services.output_guard import split_sentences, is_question as is_question_sentence
    if not reply or not slot_text or not persona:
        return reply, False
    _n = lambda t: re.sub(r"\s+", "", t)
    # 비교 단위는 슬롯 문장의 첫 문장 — Daniel 관찰은 2문장('… 되지요. 저도 그랬습니다.')이라 리드 1문장 상한이 뒷문장을 자른다(p2c 25턴 중 14).
    _key = (split_sentences(slot_text) or [slot_text])[0]
    if persona == "Michael":
        # (2026-11-04 P3-2 → 2026-11-11 P10-2) 응원 턴(슬롯 종류 "Michael"): [되받기] + 응원 문장(사례 내용을 넣어 쓴 것) + 질문.
        #   되받기가 없으면 응원만 넣지 않는다. 실행 의지 질문 턴은 슬롯 종류가 "Michael_q" 라 아래 일반 경로(되받기 1문장 + 질문).
        _ld = slot_text
        if _n(_ld) in _n(reply):
            return reply, False
        sents = [x for x in split_sentences(reply) if x.strip()]
        stmts = [x for x in sents if not is_question_sentence(x)]
        if not stmts:
            return reply, False
        i = sents.index(stmts[0])
        return " ".join(sents[: i + 1] + [_ld] + sents[i + 1:]).strip(), True
    if _n(_key) in _n(reply):
        return reply, False
    if persona == "Olivia" and _CONTRAST_RE.search(reply):
        return reply, False
    sents = split_sentences(reply)
    lead = [x for x in sents if not is_question_sentence(x)][:1]
    if persona == "Daniel":
        # (P3-2) 관찰은 되받기 뒤에: 되받기가 있으면 [되받기] + 관찰 + 나머지, 없으면 관찰 + 본문
        if lead:
            i = sents.index(lead[0])
            return " ".join(sents[: i + 1] + [slot_text] + sents[i + 1:]).strip(), True
        return f"{slot_text} {reply}".strip(), True
    return " ".join(lead + [slot_text]).strip(), True
