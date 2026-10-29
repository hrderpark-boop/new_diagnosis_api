"""사용자 입력 이상 판정 (2026-10-28 P0-4·P0-7) — 순수 함수. LLM 호출 없음.

턴 핸들러(diagnoses._submit_message_phase3a)가 decider 뒤·LLM 호출 전에 이 판정으로
'시스템 고정 응답' 턴을 만든다. 원장(asked)·사건은 전진하지 않고, 직전 질문을 다시 낸다.

판정 종류(우선순위 순):
  repeat_prev   직전 사용자 메시지와 같은 입력(공백 제거 90% 이상)        → "앞서 말씀하신 내용과 같네요. [직전 질문]"
  repeat_any    세션 안 더 앞의 답변·사건과 같은 입력(사건 중복, P0-7)     → "앞서 들려주신 이야기와 같은 사례로 보여요. …"
  returned_q    코치 자신의 직전 질문을 그대로 붙여넣음                    → "질문이 그대로 돌아왔네요. 편하게 답해 주시면 됩니다. [앵커]"
  pause_phrase  일시정지 버튼 문구가 일반 턴에 들어옴                      → "네, 이어가겠습니다. [직전 질문]"
  confirm_reask 안내(DIAGNOSIS_INTRO) 뒤 '네' 외 비실질 입력(sp·오타)       → 안내 확인 재요청(정의 질문으로 넘어가지 않음)
  def_reask     정의 질문 답이 10자 미만·물음표만                          → 정의 질문 1회 재요청
  ack_reask     질문 뒤 비실질 입력(네/넵/네?/??/sp)                        → "그럼 여쭤볼게요. [앵커]"
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

from diag_project.services.output_guard import is_question, split_sentences

_HANGUL_RE = re.compile(r"[가-힣]")
_ACK_RE = re.compile(
    r"^((네|넵|넹|예|응|음|어|그래요?|좋아요|좋습니다|알겠(어요|습니다)|괜찮아요|오케이|ok|okay|yes|y)[\s.,!?~^]*)+$",
    re.IGNORECASE)
_PAUSE_CONTINUE_RE = re.compile(r"괜찮아요[,.]?\s*계속\s*진행할게요|계속\s*진행할게요\.?$|계속\s*진행하기$")
_CONSENT_OPENER_RE = re.compile(r"^(네|예|넵|넹|응|좋아요|좋습니다|좋아|알겠|그래요|괜찮아요|오케이|ok|okay|yes|시작)", re.IGNORECASE)
_QMARK_ONLY_RE = re.compile(r"^[\s?？.!…~]+$")

REPEAT_RATIO = 0.90          # 공백 제거 후 유사도(difflib) 기준
REPEAT_MIN_CHARS = 10        # 이보다 짧은 입력은 반복으로 보지 않는다('네' 두 번은 ack 로 처리)
DEFINITION_MIN_CHARS = 10    # 정의 답 최소 길이(공백 제외)
EVENT_DUP_RATIO = 0.60       # 사건 텍스트 자카드(어절) 중복 기준


def _norm(s: str | None) -> str:
    return re.sub(r"\s+", "", (s or "")).strip()


def similarity(a: str | None, b: str | None) -> float:
    """공백 제거 후 문자열 유사도(0~1)."""
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return 0.0
    return difflib.SequenceMatcher(None, na, nb).ratio()


_PUNCT_RE = re.compile(r"[.,!?…~'\"()\[\]:;]")


def jaccard_words(a: str | None, b: str | None) -> float:
    sa = set(_PUNCT_RE.sub("", a or "").split())
    sb = set(_PUNCT_RE.sub("", b or "").split())
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def last_question_of(coach_text: str | None) -> str:
    """코치 발화의 마지막 질문(없으면 빈 문자열). 목록 줄은 제외한다.
    (2026-10-29) "…있으셨습니까? 있었다면 언제쯤이었는지부터 알려주시면 됩니다." 처럼 마지막 문장이 조건절로 시작하면
    바로 앞 질문과 한 쌍이므로 둘을 함께 돌려준다(재생 s281 Jessica: '있었다면 …' 만 되묻는 사고)."""
    from diag_project.services.output_guard import starts_without_main_clause
    for line in reversed((coach_text or "").split("\n")):
        if line.strip().startswith("·"):
            continue
        sents = split_sentences(line)
        for i in range(len(sents) - 1, -1, -1):
            if is_question(sents[i]):
                q = sents[i].strip()
                if i > 0 and starts_without_main_clause(q) and is_question(sents[i - 1]):
                    return f"{sents[i - 1].strip()} {q}"
                return q
    return ""


def is_ack_only(text: str | None) -> bool:
    """'네/넵/네?/??/sp' 처럼 답이 아닌 입력. 한글이 없거나(라틴 오타·기호), 동의 추임새만, 또는 3자 이하."""
    t = (text or "").strip()
    if not t:
        return True
    if _ACK_RE.match(t):
        return True
    if not _HANGUL_RE.search(t):
        return len(_norm(t)) <= 6          # 'sp', '??', 'ok?' 류. 긴 영문 답은 제외
    return len(_norm(t)) <= 3


def is_consent(text: str | None) -> bool:
    t = (text or "").strip()
    return bool(t) and bool(_CONSENT_OPENER_RE.match(t))


def is_pause_continue_phrase(text: str | None) -> bool:
    return bool(_PAUSE_CONTINUE_RE.search((text or "").strip()))


def definition_too_short(text: str | None) -> bool:
    t = (text or "").strip()
    if not t or _QMARK_ONLY_RE.match(t):
        return True
    if not _HANGUL_RE.search(t):
        return True
    return len(_norm(t)) < DEFINITION_MIN_CHARS


def repeats_previous(cur: str | None, prev: str | None) -> bool:
    """직전 사용자 메시지와 같은 입력(공백 제거 90% 이상, 10자 이상)."""
    if len(_norm(cur)) < REPEAT_MIN_CHARS:
        return False
    return similarity(cur, prev) >= REPEAT_RATIO


def repeats_any(cur: str | None, earlier: list[str]) -> str | None:
    """세션의 더 앞 답변 중 같은 것이 있으면 그 답변을 돌려준다(없으면 None). 직전 1건은 호출자가 따로 본다."""
    if len(_norm(cur)) < REPEAT_MIN_CHARS * 2:
        return None
    for e in earlier:
        if len(_norm(e)) >= REPEAT_MIN_CHARS * 2 and similarity(cur, e) >= REPEAT_RATIO:
            return e
    return None


def duplicates_event(cur: str | None, event_texts: list[str]) -> str | None:
    """새 사건 서술이 기존 사건(상황+행동 텍스트)과 어절 자카드 0.6 이상이면 그 사건 텍스트."""
    if len(_norm(cur)) < 30:
        return None
    for e in event_texts:
        if e and jaccard_words(cur, e) >= EVENT_DUP_RATIO:
            return e
    return None


def returned_question(cur: str | None, prev_coach_text: str | None) -> bool:
    """사용자 입력이 직전 코치 질문 문장(들) 중 하나와 같다."""
    nc = _norm(cur)
    if len(nc) < 8:
        return False
    for s in split_sentences(prev_coach_text or ""):
        if is_question(s) and similarity(cur, s) >= REPEAT_RATIO:
            return True
    # 코치 발화 전체를 붙여넣은 경우
    return similarity(cur, prev_coach_text) >= REPEAT_RATIO if len(nc) >= 20 else False


@dataclass
class Anomaly:
    kind: str               # repeat_prev | repeat_any | returned_q | pause_phrase | confirm_reask | def_reask | ack_reask
    question: str = ""      # 다시 낼 질문(있으면)
    detail: str = ""        # 로그용


def detect(
    *,
    user_text: str | None,
    prev_user_text: str | None,
    earlier_user_texts: list[str],
    prev_coach_text: str | None,
    prev_instruction: str | None,
    event_texts: list[str],
    pause_pending: bool,
    awaiting_choice: bool,
    definition_reasked: bool,
) -> Anomaly | None:
    """이번 턴이 '시스템 고정 응답' 턴인지 판정. None 이면 정상 흐름.

    prev_instruction: 직전 코치 메시지의 instruction_used.
    pause_pending: 일시정지 제안이 걸려 있어 '계속 진행할게요' 가 정상 입력인 턴.
    awaiting_choice: 챕터 전환 팝업·종료 안내 등 '네' 가 정상 입력인 턴(이 턴은 ack 재질문을 하지 않는다).
    """
    t = (user_text or "").strip()
    q = last_question_of(prev_coach_text)
    prev_instr = prev_instruction or ""

    # 1) 일시정지 문구가 일반 턴에 들어옴 → 직전 질문 재발화
    if is_pause_continue_phrase(t) and not pause_pending and q:
        return Anomaly("pause_phrase", q, "일시정지 문구(계속 진행)가 일반 턴에 입력")

    # 2) 직전 사용자 메시지와 동일
    if repeats_previous(t, prev_user_text) and q:
        return Anomaly("repeat_prev", q, "직전 사용자 메시지와 90% 이상 동일")

    # 3) 코치 질문 되돌아옴
    if returned_question(t, prev_coach_text) and q:
        return Anomaly("returned_q", q, "직전 코치 질문을 그대로 붙여넣음")

    # 4) 안내 뒤 비실질 입력(sp·오타) — 동의도 질문도 아니면 안내 확인 재요청
    if prev_instr == "DIAGNOSIS_INTRO" and not is_consent(t) and is_ack_only(t) and not _ACK_RE.match(t):
        return Anomaly("confirm_reask", "", "안내 뒤 '네' 외 비실질 입력")

    # 5) 정의 답이 너무 짧음 — 1회만 재요청
    if prev_instr == "COMPETENCY_ASK" and definition_too_short(t) and not definition_reasked:
        return Anomaly("def_reask", q, "정의 답 10자 미만·물음표만")

    # 6) 질문 뒤 비실질 입력(네/넵/네?/??/sp) → 앵커 재발화. 동의가 정상인 턴은 제외
    if q and is_ack_only(t) and not awaiting_choice and not pause_pending \
            and prev_instr not in ("DIAGNOSIS_INTRO", "DIAGNOSIS_CONFIRM", "COMPETENCY_ASK",
                                   "CHAPTER_READY_TO_END", "AWAIT_NEXT_CHAPTER_CHOICE", "RAPPORT_BUILDING",
                                   "USER_REQUESTS_PAUSE", "SUGGEST_PAUSE", "CHAPTER_ONE_MORE_ASK", "NAME_RECONFIRM"):
        return Anomaly("ack_reask", q, "질문 뒤 비실질 입력")

    # 7) 세션 안 더 앞 답변과 동일(같은 답 두 번 복사) / 기존 사건과 중복
    if q and prev_instr not in ("COMPETENCY_ASK", "DIAGNOSIS_INTRO", "DIAGNOSIS_CONFIRM", "RAPPORT_BUILDING"):
        dup = repeats_any(t, earlier_user_texts)
        if dup is not None:
            return Anomaly("repeat_any", q, "세션 앞 답변과 90% 이상 동일")
        dup_e = duplicates_event(t, event_texts)
        if dup_e is not None:
            return Anomaly("repeat_any", q, "기존 사건과 어절 자카드 0.6 이상")
    return None
