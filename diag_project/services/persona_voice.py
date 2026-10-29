"""(2026-10-23, 6번 P4) 코치 페르소나 구분 — 사전 질문(앵커·사다리·고정 문장·일반화 탐침)에 거는 결정론 어미 변환 계층.

LLM 이 아니라 규칙이다. 질문의 내용(묻는 대상·시점·행동)은 그대로 두고 어미·호칭·도입구만 바꾼다.
  Ella    부드러운 "~어요?"(기준형, 변환 없음)
  Jessica "~습니까?" 간결 — 완곡·군말 제거
  Olivia  변환 없음(대조 도입구는 실제 대조 질문에만 — LLM 질문 가드가 담당)
  Daniel  격식 "~시겠습니까?"
  Michael '직접' 행동 강조("좋습니다," 도입은 턴 가드 michael_lead_guard 가 2턴에 1회 이하로 관리)
  Lucas   최단문, 도입구·호칭 없음
또한 페르소나별 탐침 선호(레이어3 지시)와 되받기 마무리 어구 풀 5개(서로 안 겹침)를 둔다.
측정 원칙(묻는 순서·하위역량·예산)은 백엔드가 정하고 여기서는 건드리지 않는다.
"""
from __future__ import annotations

import re

from diag_project.services.intro_messages import persona_key

# ── 되받기 마무리 어구 풀(5개씩, 서로 안 겹침, 금지 어구 아님) ──────────────────────
PERSONA_TAILS: dict[str, list[str]] = {
    "Ella":    ["그러셨군요.", "그렇게 이어졌군요.", "그 대목이 눈에 들어와요.", "그 선택이 보여요.", "그 흐름이 잡혀요."],
    "Jessica": ["확인했습니다.", "정리됩니다.", "기록해 두겠습니다.", "그 부분은 분명합니다.", "핵심이 보입니다."],
    "Olivia":  ["흥미로운 지점이에요.", "다른 면이 보여요.", "거기서 갈래가 났군요.", "뜻밖의 대목이에요.", "그 선택이 궤도를 바꿨군요."],
    "Daniel":  ["그러셨습니까.", "무게가 있는 결정이었겠습니다.", "경험이 묻어나는 대목입니다.", "그렇게 풀어가셨군요.", "그 판단이 중심을 잡았겠습니다."],
    "Michael": ["좋습니다.", "그게 움직임이네요.", "바로 그 행동이에요.", "힘이 실린 결정이네요.", "속도가 붙었군요."],
    "Lucas":   ["알겠습니다.", "그렇군요.", "됐습니다.", "그 지점이군요.", "넘어가죠."],
}

# ── 탐침 선호(레이어3 지시 문장) ──────────────────────────────────────────────────
PROBE_PREFERENCE: dict[str, str] = {
    "Ella":    "되받기는 관찰 문장 2문장까지 허용(리더가 쓴 명사만). 탐침은 장면·행동을 차분히 따라간다.",
    "Jessica": "되받기는 1문장. 탐침은 숫자·기간·횟수·비율을 먼저 묻는다(언제·며칠·몇 명·몇 %). 완곡어('혹시', '조금')는 쓰지 않는다.",
    "Olivia":  "되받기는 1~2문장. 챕터에 한 번은 대조 탐침('반대로 했다면 어땠을까요?', '안 했다면 무엇이 달라졌을까요?')을 쓴다 — 이미 썼으면 쓰지 않는다. 대조 질문일 때만 '거꾸로 보면요,' 같은 도입구를 쓰고, 다른 질문 앞에는 붙이지 않는다.",
    "Daniel":  "되받기는 관찰 문장 2문장까지 허용. 격식 어미('~하셨습니까', '~시겠습니까'). 탐침은 결정의 기준과 책임을 묻는다.",
    "Michael": "되받기는 1~2문장, 짧고 힘 있게. 탐침은 리더가 직접 한 행동을 먼저 묻는다('직접 뭘 하셨어요'). 질문 앞에 '좋습니다,'.",
    "Lucas":   "되받기는 1문장, 최단문. 도입구·'리더님' 호칭 없이 바로 묻는다. 숫자·기간·결과를 먼저 묻는다.",
}

# 대조 탐침 판정 — 도입구('거꾸로 보면요,')를 뗀 '질문 본문'에 반대 경우·안 했다면·다른 사람이라면이 있을 때만.
_CONTRAST_RE = re.compile(r"(반대로 (했|하셨|갔|가셨|움직)|거꾸로 (했|하셨|갔|가셨)|안 했다면|않았다면|않으셨다면|하지 않으셨다면|달리 했다면|"
                          r"다른 (사람|분|팀원)이(라면|었다면| 맡았다면)|만약[^?]{0,24}(않|안 )|그러지 않았다면|그대로 두셨다면)")
CONTRAST_LEADS = ["거꾸로 보면요,", "거꾸로 보면,", "다른 쪽에서 보면,", "조금 비켜서 보면,", "질문을 뒤집어 볼게요.", "한 발 물러서서요,", "반대로 보면,", "반대로 보면요,"]
_LEAD_RE = re.compile(r"^(?:" + "|".join(re.escape(l) for l in CONTRAST_LEADS) + r")\s*")


def strip_contrast_lead(text: str | None) -> tuple[str, int]:
    """질문이 실제 대조가 아니면 문장 앞의 대조 도입구를 뗀다(문장 단위). (뗀 수)"""
    from diag_project.services.output_guard import split_sentences
    out, n = [], 0
    for sent in split_sentences(text or ""):
        sent = sent.strip()
        if not sent:
            continue
        stripped = _LEAD_RE.sub("", sent)
        if stripped != sent and not _CONTRAST_RE.search(stripped):
            n += 1
            sent = stripped
        out.append(sent)
    return " ".join(out), n


def is_contrast_question(text: str | None) -> bool:
    """Olivia 대조 탐침('반대로 했다면?') 판정 — 챕터당 1회 집계용. 도입구만으로는 대조가 아니다."""
    body = _LEAD_RE.sub("", (text or "").strip())
    return bool(_CONTRAST_RE.search(body))


def tails_for(persona_name: str | None) -> list[str]:
    return list(PERSONA_TAILS.get(persona_key(persona_name), PERSONA_TAILS["Ella"]))


def preference_for(persona_name: str | None, *, contrast_used: bool = False) -> str:
    k = persona_key(persona_name)
    txt = PROBE_PREFERENCE.get(k, PROBE_PREFERENCE["Ella"])
    if k == "Olivia" and contrast_used:
        txt = txt.replace("챕터에 한 번은 대조 탐침('반대로 했다면 어땠을까요?', '안 했다면 무엇이 달라졌을까요?')을 쓴다 — 이미 썼으면 쓰지 않는다.",
                          "대조 탐침은 이 챕터에서 이미 썼으니 다시 쓰지 않는다.")
    return txt


def persona_guide_block(persona_name: str | None, *, contrast_used: bool = False) -> str:
    """레이어3 페르소나 블록 뒤에 붙는 선호·마무리 어구 지시."""
    k = persona_key(persona_name)
    tails = " / ".join(t.rstrip(".") for t in tails_for(k))
    return (f"[🎭 탐침 선호 — {k}] {preference_for(k, contrast_used=contrast_used)}\n"
            f"되받기 마무리 어구는 이 중에서 고르되 연속 턴에 같은 것을 쓰지 않는다: {tails}.\n\n")


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
    # 사전 문장이 이미 '~을까요?' 면 '~을지요?' 로(Ella 기본형과 같은 문장이 나가지 않게)
    (r"있으실까요\?$", "있으실지요?"), (r"었을까요\?$", "었을지요?"), (r"을까요\?$", "을지요?"),
]
_MICHAEL_ENDINGS = [
    # (2026-10-28 P0-3) Michael 은 '~던가요?' 회상형 — Lucas('~나요?')·Ella('~어요?')와 같은 문장이 나가지 않게
    (r"있으셨어요\?$", "있으셨던가요?"), (r"있었어요\?$", "있었던가요?"), (r"있으세요\?$", "있으신가요?"),
    (r"주시겠어요\?$", "주시겠나요?"), (r"하셨어요\?$", "하셨던가요?"), (r"셨어요\?$", "셨던가요?"),
    (r"이었어요\?$", "이었던가요?"), (r"였어요\?$", "였던가요?"), (r"어땠어요\?$", "어땠던가요?"), (r"했어요\?$", "했던가요?"),
    (r"됐어요\?$", "됐던가요?"), (r"에요\?$", "인가요?"), (r"예요\?$", "인가요?"), (r"어요\?$", "던가요?"),
    (r"습니까\?$", "던가요?"), (r"있으셨나요\?$", "있으셨던가요?"), (r"셨나요\?$", "셨던가요?"),
    (r"있으실까요\?$", "있으실 것 같나요?"), (r"있으신가요\?$", "있으셨던가요?"), (r"신가요\?$", "셨던가요?"),
    (r"었을까요\?$", "었던가요?"), (r"을까요\?$", "을 것 같나요?"), (r"나요\?$", "던가요?"),
]


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
        return t
    if k == "Olivia":
        # (2026-10-28 P0-3) Olivia 는 '~었을까요?/~을까요?' 의 열린 어미 — Ella(기본 사전 문장)와 같은 문장이 나가지 않게.
        t = re.sub(r"^(혹시|한번|한 번)\s+", "", t)
        for pat, rep in _OLIVIA_ENDINGS:
            if re.search(pat, t):
                return re.sub(pat, rep, t)
        return t
    if k == "Jessica":
        t = re.sub(r"^(혹시|조금|한번|한 번)\s+", "", t)
        t = t.replace("뭘 ", "무엇을 ").replace("걸 ", "것을 ")
        return _apply_endings(t, 1)
    if k == "Daniel":
        t = t.replace("뭘 ", "무엇을 ").replace("걸 ", "것을 ")
        return _daniel(t, variant)
    if k == "Michael":
        # (2026-10-28 P0-3) Michael 은 '~었나요?/~나요?' 의 밝고 빠른 어미 + '직접'. 어미 변환이 없으면 Ella 와 같은 문장이 나갔다.
        body = re.sub(r"^(좋습니다[,!.]?\s*)", "", t)
        # (2026-10-29 P1-2) 어절 첫머리의 '하신 적'에만 — '전하신 적·조정하신 적·배려하신 적'이 '전직접 하신 적'으로 깨지던 것(p11 Michael 앵커 4종)
        body = re.sub(r"(?<![가-힣])하신 적", "직접 하신 적", body, count=1) if "직접" not in body else body
        for pat, rep in _MICHAEL_ENDINGS:
            if re.search(pat, body):
                return re.sub(pat, rep, body)
        return body
    if k == "Lucas":
        s = t
        for pat, rep in _LUCAS_CUTS:
            s = re.sub(pat, rep, s)
        s = re.sub(r"\s{2,}", " ", s).strip()
        return s if s.count("?") == 1 else t
    return t


_GOOD_RE = re.compile(r"좋습니다[!,.]?\s*")


def michael_lead_guard(text: str, allow: bool, *, add: bool = True) -> tuple[str, bool]:
    """Michael '좋습니다' 도입: 턴당 최대 1회, 허용 턴이면 정확히 1회(없고 add=True 면 붙인다), 비허용 턴이면 전부 뗀다. (텍스트, 사용 여부)
    add=False(라포·인사 등 챕터 밖 턴)에서는 붙이지 않고 중복만 정리한다."""
    t = (text or "").strip()
    if not t:
        return text, False
    n = len(_GOOD_RE.findall(t))
    if not allow:
        return _GOOD_RE.sub("", t).strip(), False
    if n == 0:
        return (f"좋습니다, {t}", True) if add else (t, False)
    first = _GOOD_RE.search(t)
    rest = _GOOD_RE.sub("", t[first.end():])
    return (t[:first.start()] + "좋습니다, " + rest).strip(), True
