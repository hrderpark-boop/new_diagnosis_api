"""#6 문체 반복 추적 — 최근 코치 발화의 '시작 패턴'을 세어 LLM 제약을 만든다.

거의 모든 턴이 "네, ~하셨군요" + 요약으로 시작하면 열 번째쯤 기계로 들린다.
LLM 은 스스로 턴을 세지 못하므로 백엔드가 최근 3개 코치 발화를 보고
  · '네, ~하셨군요/말씀이시군요' 시작이 직전 턴에 있었으면 → 이번 턴 금지
  · 요약 되받기가 최근 2턴 안에 있었으면 → 이번 턴 금지(3턴에 1번 이하)
를 순수 함수로 계산한다. 시스템 템플릿 턴(앵커·전환 템플릿)도 코치 발화로 세지만
그 문장들은 패턴에 걸리지 않게 작성돼 있어 영향이 없다.
"""
import re

# "네," / "넵," / "예," 로 시작하거나 첫 문장이 '~군요/~네요' 계열로 끝나는 시작.
_NE_OPENER = re.compile(r"^\s*(네|넵|예)\s*[,.!…]")
_GUNYO_END = re.compile(r"(군요|시네요|셨네요|이시네요)[.!?…]?\s*$")
# 요약 되받기: 첫 문장이 리더님 답변을 다시 정리하는 표지를 담는다.
_RECAP = re.compile(
    r"(하셨군요|말씀이시군요|이시군요|셨네요|하셨네요|말씀하신|말씀해 ?주신|"
    r"들려주신|들으니|정리하면|정리해 ?보면|요약하면|~?라는 말씀)"
)


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


def is_recap_opening(text: str) -> bool:
    """첫 문장이 '요약 되받기'인가(리더님 답변을 다시 정리해 주는 문장)."""
    fs = _first_sentence(text)
    return bool(fs) and bool(_RECAP.search(fs))


def compute_style_constraints(recent_coach: list[str]) -> dict:
    """최근 코치 발화(최신 순, 최대 3개)로 이번 턴 문체 제약을 계산한다.

    반환:
      recent_openers   : 최근 발화 첫 문장(최신 순, 로그·프롬프트 표시용)
      ne_recap_prev    : 직전 발화가 '네, ~하셨군요' 시작이었는가
      recap_count_2    : 최근 2턴 중 요약 되받기 수
      forbid_ne_opening: 이번 턴 '네, ~하셨군요' 시작 금지
      forbid_recap     : 이번 턴 요약 되받기 금지(3턴에 1번 이하)
    """
    recent = [r or "" for r in (recent_coach or [])][:3]
    openers = [_first_sentence(r) for r in recent]
    ne_prev = bool(recent) and starts_with_ne_recap(recent[0])
    recap_2 = sum(1 for r in recent[:2] if is_recap_opening(r))
    return {
        "recent_openers": openers,
        "ne_recap_prev": ne_prev,
        "recap_count_2": recap_2,
        "forbid_ne_opening": ne_prev,
        "forbid_recap": recap_2 >= 1,
    }


def format_style_constraints(sc: dict | None) -> str:
    """프롬프트 삽입용 텍스트. 제약이 없으면 빈 문자열."""
    if not sc:
        return ""
    lines = []
    if sc.get("forbid_ne_opening"):
        lines.append(
            "- 직전 턴이 '네, ~하셨군요/~말씀이시군요'로 시작했습니다. **이번 턴은 "
            "그 시작 금지** — 호응어 없이 바로 질문으로 들어가거나 다른 짧은 반응 "
            "한 마디('그랬군요.', '아, 그 장면요.')로 시작하세요."
        )
    if sc.get("forbid_recap"):
        lines.append(
            "- 최근 2턴 안에 리더님 답변을 요약해 되받은 문장이 있었습니다. **이번 "
            "턴은 요약 되받기 금지** — 답변을 다시 정리하지 말고 바로 다음 질문(또는 "
            "짧은 반응 + 질문)으로."
        )
    if not lines:
        return ""
    return "[🎛 이번 턴 문체 제약 — 시스템 계산, 반드시 준수]\n" + "\n".join(lines)
