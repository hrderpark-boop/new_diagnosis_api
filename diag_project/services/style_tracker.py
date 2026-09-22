"""#6 문체 반복 추적 — 최근 코치 발화의 '시작 패턴'을 세어 LLM 제약을 만든다.

거의 모든 턴이 "네, ~하셨군요" + 요약으로 시작하면 열 번째쯤 기계로 들린다.
LLM 은 스스로 턴을 세지 못하므로 백엔드가 최근 3개 코치 발화를 보고
  · '네, ~하셨군요/말씀이시군요' 시작이 직전 턴에 있었으면 → 이번 턴 금지
  · 요약 되받기가 최근 2턴 안에 있었으면 → 이번 턴 금지(3턴에 1번 이하)
를 순수 함수로 계산한다.

2026-09-14 확장: '요약 되받기' 판정을 "네로 시작"이 아니라 **직전 사용자 발화의
명사구를 그대로 복창하는 문장**으로 넓혔다. Jessica 가 "네"를 빼고 "~하셨습니다"
평서문으로 같은 패턴을 유지해 제약을 우회했기 때문. 판정 = 표지어(_RECAP) OR
평서문 요약 종결(_PLAIN_RECAP_END) OR 사용자 어절 복창(echoes_user).
금지 턴의 대안은 페르소나별: Ella 는 감정 한 줄, Jessica 는 관찰·통찰 한 줄. 시스템 템플릿 턴(앵커·전환 템플릿)도 코치 발화로 세지만
그 문장들은 패턴에 걸리지 않게 작성돼 있어 영향이 없다.
"""
import re

# "네," / "넵," / "예," 로 시작하거나 첫 문장이 '~군요/~네요' 계열로 끝나는 시작.
_NE_OPENER = re.compile(r"^\s*(네|넵|예)\s*[,.!…]")
_GUNYO_END = re.compile(r"(군요|시네요|셨네요|이시네요)[.!?…]?\s*$")
# 요약 되받기: 첫 문장이 리더님 답변을 다시 정리하는 표지를 담는다.
_RECAP = re.compile(
    r"(하셨군요|말씀이시군요|이시군요|셨네요|하셨네요|말씀하신|말씀해 ?주신|"
    r"들려주신|들으니|정리하면|정리해 ?보면|요약하면|~?라는 말씀|"
    # 2026-09-16(Daniel 재주행): "~말씀, 잘 들었습니다/잘 알겠습니다" 형 요약 되받기
    r"잘 들었습니다|잘 알겠습니다|말씀, |다는 말씀|말씀에 (깊이 )?공감)"
)
# 평서문 요약: 첫 문장이 질문이 아닌 채 '~하셨습니다/~셨죠' 로 끝남(Jessica 우회형).
#   '~군요' 로 끝나는 상황 요약("팀원들의 불만이 있었던 상황이군요.")도 되받기. '~네요' 는 제외 —
#   해석·공감 한 줄("그 판단이 쉽지 않으셨겠네요.")의 종결이라 금지하면 대체 문장까지 막힌다.
_PLAIN_RECAP_END = re.compile(r"(셨습니다|셨죠|셨고요|이었습니다|였습니다|확인되었습니다|군요)[.!…]?\s*$")
# 사용자 어절에서 조사를 떼어 '내용 어절'만 남긴다(복창 판정용).
_JOSA_RE = re.compile(
    r"(에서는|으로는|에게는|한테는|까지는|부터는|이라도|라도|에서|으로|에게|한테|처럼|보다|"
    r"부터|까지|이나|든지|은|는|이|가|을|를|의|에|로|과|와|도|만|께|나|요)$"
)
# 동사 어미를 떼어 어간만 남긴다('올리라고'↔'올리도록', '분석하기'↔'분석하셨').
_VERB_END = re.compile(
    r"(하겠다고|하라고|하도록|하면서|했습니다|했어요|했었|하기|했죠|했고|하며|해서|하고|"
    r"라고|도록|면서|했|죠|한|할|함)$"
)
_STOP = {
    "그래서", "그런데", "그리고", "하지만", "그러니까", "그러면", "저는", "제가", "저희", "우리",
    "그냥", "정도", "같아요", "같은", "같은데", "때가", "있어요", "있었어요", "했어요", "했죠",
    "그때", "이런", "저런", "그런", "무슨", "어떤", "조금", "많이", "너무", "다시", "우선",
    "일단", "아니", "근데", "사실", "제일", "가장", "그거", "이거", "그게", "이게", "뭐랄까",
    "느낌", "생각", "부분", "경우", "때문", "정말", "진짜", "약간", "결국", "역시", "물론",
    "리더님", "팀원", "팀원들",
}


def _content_chunks(text: str) -> list[str]:
    """사용자 발화 → 조사 뗀 2자 이상 내용 어절 목록."""
    out = []
    for tok in re.split(r"[\s,.!?…~\"'‘’“”*()\[\]/·—-]+", text or ""):
        tok = tok.strip()
        if len(tok) < 2:
            continue
        base = _JOSA_RE.sub("", tok)
        base2 = _JOSA_RE.sub("", base)          # '일들이요' → '일들이' → '일들' (조사 두 겹, 2026-09-22)
        if len(base2) >= 2:
            base = base2
        stem = _VERB_END.sub("", base)
        if len(stem) >= 2:
            base = stem
        if len(base) >= 2 and base not in _STOP:
            out.append(base)
    return out


def echoes_user(coach_text: str, user_text: str | None) -> bool:
    """코치 첫 문장이 직전 사용자 발화의 명사구를 그대로 복창하는가.

    사용자 내용 어절이 코치 첫 문장에 2개 이상 그대로 들어 있거나, 5자 이상 어절이
    1개라도 그대로 들어 있으면 복창. (질문문이면 복창으로 보지 않는다 — 되묻기는 허용.)
    """
    fs = _first_sentence(coach_text)
    if not fs or not user_text or fs.rstrip().endswith("?"):
        return False
    hits = {c for c in set(_content_chunks(user_text)) if c in fs}
    # 2026-09-17: 어절 2개 이상만 복창. 한 어절 인용은 '연결 한 절'(다음 질문의 동기)로 허용한다.
    return len(hits) >= 2


def _first_sentence(text: str) -> str:
    t = (text or "").strip()
    if not t:
        return ""
    # 첫 문장 = 첫 종결부호(.!?)까지. 없으면 앞 60자.
    m = re.search(r"[.!?…]", t)
    return t[: m.end()] if m and m.end() <= 120 else t[:60]


def starts_with_ne_recap(text: str) -> bool:
    """'네, ~하셨군요' 류 시작인가."""
    fs = _first_sentence(text)
    if not fs:
        return False
    return bool(_NE_OPENER.match(fs)) or bool(_GUNYO_END.search(fs))


# 연결 한 절(2026-09-17 규칙): "방금 말씀하신 '인정'과도 이어지는데요, …?" — 표지어 '말씀하신' 이 들어가지만
#   되받기가 아니다(한 어절 인용을 다음 질문의 이유로 씀). 판정 전에 이 절을 걷어낸다(2026-09-18).
_BRIDGE_RE = re.compile(
    r"(방금|앞서|아까|조금 전)?\s*(말씀하신|말씀해 ?주신|언급하신)\s*['\"“‘][^'\"”’]{1,10}['\"”’]\s*"
    r"(과도|와도|과|와|을|를|에|도|이야기|말씀)?"
)


def _strip_bridge(sentence: str) -> str:
    return _BRIDGE_RE.sub("", sentence or "")


def is_recap_opening(text: str) -> bool:
    """첫 문장이 '요약 되받기'인가(리더님 답변을 다시 정리해 주는 문장).

    표지어('~하셨군요/말씀하신…') 또는 질문 아닌 평서문 요약 종결('~하셨습니다.').
    연결 한 절("방금 말씀하신 '○○'과도 …?")은 걷어내고 판정한다.
    """
    fs = _strip_bridge(_first_sentence(text))
    if not fs:
        return False
    if fs.rstrip().endswith("?"):
        return bool(_RECAP.search(fs))
    return bool(_RECAP.search(fs)) or bool(_PLAIN_RECAP_END.search(fs))


def is_recap_turn(coach_text: str, user_text: str | None = None) -> bool:
    """이 코치 턴이 '요약 되받기'였는가 — 표지어 OR 직전 사용자 발화 복창."""
    return is_recap_opening(coach_text) or echoes_user(coach_text, user_text)


def compute_style_constraints(
    recent_coach: list[str], recent_user: list[str] | None = None,
) -> dict:
    """최근 코치 발화(최신 순, 최대 3개)로 이번 턴 문체 제약을 계산한다.

    recent_user: 각 코치 발화 '직전'의 사용자 발화(같은 순서, 최신 순). 복창 판정용.
    반환:
      recent_openers   : 최근 발화 첫 문장(최신 순, 로그·프롬프트 표시용)
      ne_recap_prev    : 직전 발화가 '네, ~하셨군요' 시작이었는가
      recap_count_2    : 최근 2턴 중 요약 되받기(표지어·평서문 요약·복창) 수
      forbid_ne_opening: 이번 턴 '네, ~하셨군요' 시작 금지
      forbid_recap     : 이번 턴 요약 되받기 금지(3턴에 1번 이하)
    """
    recent = [r or "" for r in (recent_coach or [])][:3]
    users = [u or "" for u in (recent_user or [])][:3]
    openers = [_first_sentence(r) for r in recent]
    ne_prev = bool(recent) and starts_with_ne_recap(recent[0])
    recap_2 = sum(
        1 for i, r in enumerate(recent[:2])
        if is_recap_turn(r, users[i] if i < len(users) else "")
    )
    # (2026-09-22, 4번) 되받기 '3턴 1회' 제한과 '네' 시작 금지는 폐지 — 가드로 자르지 않고 Layer1 대화 규칙 2 한 줄이
    #   맡는다. 값은 관찰용(guard_log·리플레이 집계)으로만 남긴다.
    return {
        "recent_openers": openers,
        "ne_recap_prev": ne_prev,
        "recap_count_2": recap_2,
        "forbid_ne_opening": False,
        "forbid_recap": False,
    }


# 되받기 금지 턴의 '대체 문장' 규칙 — 6명 전부 앵무새 복창은 금지, 대신 붙이는 한 줄이 다르다.
#   (2026-09-15: Olivia·Daniel·Michael·Lucas 추가. Lucas 도 '요점 정리 한 줄' 없이 질문만 던지면 안 된다.)
# 2026-09-17: '인정·격려 한 줄' → '연결 한 절'. 직전 사용자 발화의 핵심 단어 하나를 집어 다음 질문의
#   동기로 쓴다(내용 되풀이 X). 복창 판정(어절 2개 이상)에 걸리지 않게 인용은 한 어절만.
_BRIDGE_RULE = ("**연결 한 절**로 받으세요 — 직전 발화의 핵심 단어 **하나**를 집어 다음 질문의 이유로 씁니다"
                "(예: \"방금 말씀하신 '인정'과도 이어지는데요, 목표를 정할 때는 …?\"). 내용을 되풀이하지 말고 "
                "인용은 한 어절만, 그 절은 질문 문장 안에 둡니다. ")
_PERSONA_REACTION = {
    "Ella": (_BRIDGE_RULE + "Ella 는 부드럽게('~와도 닿아 있는데요, ~은 어땠어요?'). "),
    "Jessica": (_BRIDGE_RULE + "Jessica 는 간결하게('그 \"기준\"과 연결해 여쭙니다. ~입니까?'). 평가 없이. "),
    "Olivia": (_BRIDGE_RULE + "Olivia 는 다른 각도로('그 \"불평\"을 뒤집어 보면 이런 질문이 생기는데요, ~?'). "),
    "Daniel": (_BRIDGE_RULE + "Daniel 은 격식체로('방금 말씀하신 \"인정\"과도 이어지는 부분입니다만, ~하셨습니까?'). "
               "능력 칭찬 없이 상황·사실만. "),
    "Michael": (_BRIDGE_RULE + "Michael 은 추진감 있게('그 \"밀어붙임\" 다음 장면이 궁금한데요, ~?'). 느낌표는 한 번. "),
    "Lucas": (_BRIDGE_RULE + "Lucas 는 요점 하나로('핵심은 \"연결\"이었으니, ~는요?'). 연결 절 없이 질문만 던지지 마세요. "),
}


# ── 느낌표 상한(2026-09-15): 페르소나별로 백엔드가 센다. Michael 만 1, 나머지 0. ──
#   Michael 시뮬레이션에서 안내 턴 5개·세션 합계 14개가 나와 프로필("한두 번")의 두 배를 넘었다.
#   안내·설명 턴(진행 안내, 정의 제시 등)은 Michael 도 0. 초과 시 재생성 1회 → 그래도 초과면
#   초과분을 마침표로 치환(enforce_exclamation_cap).
_EXCLAMATION_CAP = {"Michael": 1}
_EXPLAIN_INSTRUCTIONS = {
    "DIAGNOSIS_INTRO", "DIAGNOSIS_CONFIRM", "COMPETENCY_ALIGN", "META_QUESTION_FROM_USER",
    "CHAPTER_READY_TO_END", "CHAPTER_CONTINUE_CONFIRMED", "USER_REQUESTS_PAUSE",
}


def exclamation_cap(persona_name: str | None, instruction: str | None = None) -> int:
    """이번 응답의 느낌표 상한. Michael 1(안내·설명 턴 0), 나머지 0."""
    n = (persona_name or "").strip()
    cap = 0
    for key, c in _EXCLAMATION_CAP.items():
        if n.startswith(key):
            cap = c
    if instruction in _EXPLAIN_INSTRUCTIONS:
        return 0
    return cap


def count_exclamations(text: str | None) -> int:
    return (text or "").count("!")


def enforce_exclamation_cap(text: str, cap: int) -> tuple[str, int]:
    """상한을 넘는 느낌표를 마침표로 바꾼다. (치환 결과, 원래 개수) 반환.

    앞에서부터 cap 개는 남긴다. '!!' 연속은 하나로, '?!' 는 '?' 로, '.!' 는 '.' 로 정리한다.
    """
    if not text:
        return text, 0
    total = text.count("!")
    if total <= cap:
        return text, total
    out = []
    kept = 0
    for ch in text:
        if ch == "!":
            if kept < cap:
                kept += 1
                out.append(ch)
            else:
                out.append(".")
        else:
            out.append(ch)
    t = "".join(out)
    t = re.sub(r"\?\.", "?", t)          # '?!' → '?.' → '?'
    t = re.sub(r"!\.", "!", t)            # '!!' 의 두 번째 → '!.' → '!'
    t = re.sub(r"(?<!\.)\.\.(?!\.)", ".", t)  # '..' → '.' ('...' 말줄임은 유지)
    return t, total


def _persona_reaction_hint(persona_name: str | None) -> str:
    """금지 턴의 대안 — 페르소나별 '한 줄 반응' 결. 앵무새 복창은 모두 금지."""
    n = (persona_name or "").strip()
    for key, hint in _PERSONA_REACTION.items():
        if n.startswith(key):
            return hint
    if n:
        return "페르소나의 결로 해석·공감 한 줄을 붙이거나 바로 질문하세요. "
    return ""


def format_style_constraints(
    sc: dict | None, persona_name: str | None = None, instruction: str | None = None,
) -> str:
    """프롬프트 삽입용 텍스트. 제약이 없으면 빈 문자열(페르소나가 주어지면 느낌표 상한 줄은 항상)."""
    if not sc and not persona_name:
        return ""
    sc = sc or {}
    lines = []
    if persona_name:
        # 4-b(2026-09-16) 평가적 칭찬 금지 — BEI 원칙: 평가자가 원하는 신호를 주면 답을 포장한다.
        lines.append(
            "- **평가적 칭찬 금지(6명 공통)**: '훌륭한', '매우 인상 깊습니다', '깊은 통찰력', "
            "'참으로 의미 있는', '깊이 다가옵니다', '본질을 정확히 짚어주셨습니다', '탁월·뛰어난·대단한' 류 전부. "
            "인정은 사실 확인('그 결정을 내리셨군요', '쉽지 않은 자리였겠습니다')까지. "
            "시스템이 출력을 검사해 포함 문장을 지웁니다."
        )
        # (2026-09-22) 되받기: 자르지 않는다. 한 줄 지시 + 페르소나별 반응 힌트만.
        lines.append(
            "- 리더님 말을 한 문장으로 되풀이하지 마세요. 짧게 받고 바로 이어서 물으세요. "
            + _persona_reaction_hint(persona_name)
        )
        cap = exclamation_cap(persona_name, instruction)
        lines.append(
            f"- 느낌표(!) 상한: 이번 응답에 **최대 {cap}개**"
            + (" — 안내·설명 턴이라 0개" if cap == 0 and instruction in _EXPLAIN_INSTRUCTIONS
               and (persona_name or "").startswith("Michael") else "")
            + ". 시스템이 세어 초과분은 마침표로 바꿉니다. 에너지·강조는 느낌표가 아니라 단어로."
        )
    if not lines:
        return ""
    return "[🎛 이번 턴 문체 제약 — 시스템 계산, 반드시 준수]\n" + "\n".join(lines)
