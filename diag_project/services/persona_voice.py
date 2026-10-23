"""(2026-10-23, 6번 P4) 코치 페르소나 구분 — 사전 질문(앵커·사다리·고정 문장·일반화 탐침)에 거는 결정론 어미 변환 계층.

LLM 이 아니라 규칙이다. 질문의 내용(묻는 대상·시점·행동)은 그대로 두고 어미·호칭·도입구만 바꾼다.
  Ella    부드러운 "~어요?"(기준형, 변환 없음)
  Jessica "~습니까?" 간결 — 완곡·군말 제거
  Olivia  질문 앞에 '다른 각도' 한 줄
  Daniel  격식 "~시겠습니까?"
  Michael "좋습니다," 도입 + 행동 강조
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
    "Olivia":  "되받기는 1~2문장. 챕터에 한 번은 대조 탐침('반대로 했다면 어땠을까요?', '안 했다면 무엇이 달라졌을까요?')을 쓴다 — 이미 썼으면 쓰지 않는다. 질문 앞에 다른 각도 한 줄.",
    "Daniel":  "되받기는 관찰 문장 2문장까지 허용. 격식 어미('~하셨습니까', '~시겠습니까'). 탐침은 결정의 기준과 책임을 묻는다.",
    "Michael": "되받기는 1~2문장, 짧고 힘 있게. 탐침은 리더가 직접 한 행동을 먼저 묻는다('직접 뭘 하셨어요'). 질문 앞에 '좋습니다,'.",
    "Lucas":   "되받기는 1문장, 최단문. 도입구·'리더님' 호칭 없이 바로 묻는다. 숫자·기간·결과를 먼저 묻는다.",
}

_CONTRAST_RE = re.compile(r"(반대로|거꾸로|안 했다면|않았다면|하지 않으셨다면|달리 했다면|만약[^?]{0,20}(않|안)|그러지 않았다면)")


def is_contrast_question(text: str | None) -> bool:
    """Olivia 대조 탐침('반대로 했다면?') 판정 — 챕터당 1회 집계용."""
    return bool(_CONTRAST_RE.search(text or ""))


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
    (r"까요\?$",              "까요?",                  "을지 말씀해 주시겠습니까?"),
]
_LUCAS_CUTS = [(r"^(그때|그 당시|최근에|요즘|그중)\s+", ""), (r"\b리더님(은|이|께서|께서는)?\s*", ""), (r"\b직접\s+", ""),
               (r"\s*같이\s+", " "), (r",\s*최근에\s+", " 최근 "), (r"하신 적이 있었어요\?$", "하신 적 있나요?"), (r"적이 있었어요\?$", "적 있나요?"),
               (r"일이 있었어요\?$", "일 있었나요?"), (r"게 있었어요\?$", "게 있었나요?"), (r"있으셨어요\?$", "있었나요?"), (r"있었어요\?$", "있었나요?"),
               (r"무엇이었어요\?$", "뭐였나요?"), (r"무엇을\s+", "뭘 "), (r"어떻게 하셨어요\?$", "어떻게 하셨죠?"), (r"이었어요\?$", "이었나요?"),
               (r"였어요\?$", "였나요?"), (r"어땠어요\?$", "어땠나요?"), (r"됐어요\?$", "됐나요?"), (r"고치셨어요\?$", "고쳤나요?")]


def _apply_endings(text: str, col: int) -> str:
    for pat, jes, dan in _ENDINGS:
        if re.search(pat, text):
            return re.sub(pat, jes if col == 1 else dan, text)
    return text


def voice_question(persona_name: str | None, text: str) -> str:
    """사전 질문 한 문장을 페르소나 어미로. 내용 불변, 물음표 1개 유지. 모르는 페르소나·빈 문장은 그대로."""
    t = (text or "").strip()
    if not t or t.count("?") != 1 or not t.endswith("?"):
        return text
    k = persona_key(persona_name)
    if k == "Ella":
        return t
    if k == "Jessica":
        t = re.sub(r"^(혹시|조금|한번|한 번)\s+", "", t)
        t = t.replace("뭘 ", "무엇을 ").replace("걸 ", "것을 ")
        return _apply_endings(t, 1)
    if k == "Daniel":
        t = t.replace("뭘 ", "무엇을 ").replace("걸 ", "것을 ")
        return _apply_endings(t, 2)
    if k == "Olivia":
        lead = _OLIVIA_LEADS[sum(map(ord, t)) % len(_OLIVIA_LEADS)]
        return f"{lead} {t[0].lower() + t[1:] if t[0].isascii() else t}"
    if k == "Michael":
        body = re.sub(r"^(좋습니다,\s*)", "", t)
        body = re.sub(r"하신 적", "직접 하신 적", body, count=1) if "직접" not in body else body
        return f"좋습니다, {body}"
    if k == "Lucas":
        s = t
        for pat, rep in _LUCAS_CUTS:
            s = re.sub(pat, rep, s)
        s = re.sub(r"\s{2,}", " ", s).strip()
        return s if s.count("?") == 1 else t
    return t
