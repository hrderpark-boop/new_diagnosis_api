"""Instruction Decider (Phase 3-A 두뇌)

매 턴마다 LLM 에게 줄 명시적 지시 (instruction) 를 결정한다.
15가지 instruction 중 하나를 선택해 LLM 의 다음 행동을 결정.

설계 출처: docs/phase3a/01_design.md (Section 7.4-7.5)
"""

import re
from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from diag_project.models.event import Event
from diag_project.models.diagnosis_session import ChatMessage, MessageRole
from diag_project.services.avoidance_detector import (
    check_avoidance,
    is_unproductive_response,
    detect_deflection,
    detect_rush,
    detect_session_abort_signal,
    detect_pause_request,
    detect_meta_question,
    detect_prompt_injection,
    detect_closing_intent,
    is_invalid_input,
)


# 이름으로 오추출되기 쉬운 부사·감탄사·일반명사·인사·역할어 블랙리스트.
#  자기소개 어미에 우연히 걸려도(예: "영광입니다"→"영광", "과정입니다"→"과정",
#  "아니라고요"→"아니") 이름이 아니므로 폐기한다.
_NAME_BLACKLIST = {
    "아니", "아니요", "아니오", "과정", "영광", "글쎄", "글쎄요", "환영",
    "안녕", "반갑", "감사", "고맙", "리더", "코치", "진단", "생각", "질문",
    "답변", "여기", "저기", "그냥", "당연", "물론", "사실", "정말", "진짜",
    "그거", "이거", "저거", "우리", "저희", "당신", "본인", "자신", "무슨",
    "네네", "예예", "그래", "맞아", "맞습", "몰라", "모름",
    # P1-2: 이름으로 오추출되던 부사·감탄사 추가 ("조금이라도"→"조금" 등)
    "조금", "지금", "아무", "혹시", "다시", "잠깐", "잠시", "약간", "부디",
    "제발", "정도", "이제", "이번", "오늘", "요즘", "한번", "일단",
    # 직책·역할어(직책 앞의 이름만 뽑고, 직책 자체는 이름이 아님)
    "팀장", "과장", "부장", "차장", "대리", "사원", "주임", "이사", "부장님",
    "본부장", "실장", "센터장", "파트장", "상무", "전무", "대표", "선생",
}


def _is_blacklisted_name(cand: str | None) -> bool:
    """추출 후보가 이름이 아닌 일반어(블랙리스트)인지 판정."""
    if not cand:
        return True
    c = cand.strip()
    if not c:
        return True
    return any(bad in c for bad in _NAME_BLACKLIST)


def _extract_user_name(text: str) -> str | None:
    """첫 user 메시지에서 이름 추출. 명확한 자기소개가 없으면 None.

    🚨 억지 추출 절대 금지: 사용자가 이름을 명확히 밝히지 않고 비아냥·거부·
    반말·불만으로 응답하면, 문장 속 무의미한 명사(예: '환영은', '이딴')를
    이름으로 뽑지 않는다. '명확한 자기소개 어미' 패턴이 있을 때만 신뢰하고,
    없으면 None 을 반환한다(→ 코치는 기본 호칭 '리더님'으로 부른다).

    예시:
    - "안녕하세요 박기진입니다"        → "박기진"
    - "박기진이라고 합니다"            → "박기진"
    - "환영은 무슨. 이딴 진단인지..."  → None (비아냥 — 억지 추출 안 함)
    - "안녕하세요"                     → None (이름 없음)
    - ""                              → None
    """
    from diag_project.services.avoidance_detector import detect_deflection

    if not text or not text.strip():
        return None

    # 비아냥·남탓·도발·거부 신호가 있으면 이름 추출 자체를 포기한다.
    # (이런 문장에서 우연히 어미 패턴이 매칭돼도 이름일 가능성이 낮다)
    if detect_deflection(text):
        return None

    # 🚫 이름으로 절대 추출하면 안 되는 부사·감탄사·일반명사·인사·역할어는
    #   자기소개 어미("영광입니다", "과정입니다", "아니라고요")에 우연히
    #   걸려도 폐기한다(_is_blacklisted_name).
    def _clean(cand: str | None) -> str | None:
        if not cand:
            return None
        cand = cand.strip()
        return None if _is_blacklisted_name(cand) else cand

    # (1) 맥락 키워드(직책) 기반: '홍길동 팀장', '박영희 과장이라고 합니다' 등
    #     → 직책 앞의 2~4자 한글을 이름으로 신뢰.
    role_match = re.search(
        r'([가-힣]{2,4})\s*'
        r'(?:팀장|과장|부장|차장|대리|사원|주임|이사|본부장|실장|센터장|'
        r'파트장|상무|전무|대표|리더)',
        text,
    )
    if role_match and (nm := _clean(role_match.group(1))):
        return nm

    # (2) 명확한 '자기소개 어미' 패턴만 신뢰한다. (fallback 명사 추출은 폐기 —
    #     그게 '환영은' 같은 무의미 명사를 이름으로 뽑던 근본 원인이었다.)
    #  - 이름 그룹은 lazy 매칭: 탐욕적이면 '김민준이라고'가 '김민준이'로 잘림.
    #  - 어미 대안은 긴 것 우선 (이라고 합니다 > 이라고 > 라고 …).
    #  - (2026-11-04) 이름과 어미 사이 공백 1개 허용('박기진 입니다' — 운영 11/4 입력이 재생 Jessica 에서 이름 재확인으로 빠졌다).
    #    어절 첫머리에서만 시작해 '안녕하세요 입니다'의 '하세요'를 이름으로 뽑지 않는다.
    match = re.search(
        r'(?<![가-힣])([가-힣]{2,4}?)\s?'
        r'(?:이라고\s*(?:합니다|해요|불러)|라고\s*(?:합니다|해요|불러)'
        r'|이라고요|이라고|라고요|라고'
        r'|입니다|이에요|예요|이야|이고|이며|이라)',
        text,
    )
    if match and (nm := _clean(match.group(1))):
        return nm

    # 명확한 자기소개가 없음 → 억지로 뽑지 않고 None.
    return None




# instruction 타입
InstructionType = Literal[
    "SESSION_ABORT_3STRIKE",
    "SESSION_ABORT_WARNING",
    "NAME_RECONFIRM",
    "RAPPORT_BUILDING",
    "DIAGNOSIS_INTRO",
    "DIAGNOSIS_CONFIRM",
    "COMPETENCY_ASK",
    "COMPETENCY_ALIGN",
    # (2026-11-04 BEI) 사례 단계 — 결정기는 EPISODE_PROBE 를 내고, 라우트의 BEI 단계가 슬롯 판정 뒤 아래 넷으로 덮어쓴다
    "EPISODE_PROBE",
    "EPISODE_OPEN",
    "NO_CASE_REFRAME",
    "SWEEP_ANCHOR",
    "SWEEP_FOLLOWUP",
    "ABORT_CONFIRM",
    "ABORT_DISENGAGED",
    "CHAPTER_READY_TO_END",
    "USER_REQUESTS_PAUSE",
    "PROMPT_INJECTION_DETECTED",
    "META_QUESTION_FROM_USER",
    "INVALID_INPUT",
    # 2026-09-16: 챕터 전환 직후(정의 질문 전) 버튼 대신 친 자유 텍스트 → 안내만, 상태 무변경
    "AWAIT_NEXT_CHAPTER_CHOICE",
]

# 챕터 전환 팝업에서 버튼 대신 텍스트로 '확인'한 것으로 볼 표현(이중 방어).
#   시작 어절(네/예/알겠/좋아요…)로 열거나, 짧은 문장(≤25자)에 다음/계속/진행 키워드가 있을 때만.
#   ("…분석하기 시작했죠" 같은 이전 챕터 답변이 '시작' 한 글자로 동의로 오인되지 않게)
_NEXT_CONSENT_OPENER = re.compile(r"^(네|예|넵|넹|응|좋아요|좋습니다|좋아|알겠|그래요|괜찮아요|오케이|ok|okay|yes)", re.I)
NEXT_CHAPTER_CONSENT_KEYWORDS = ("다음", "계속", "진행", "넘어가", "이어가", "갑시다", "가시죠", "가요")
_NEXT_CONSENT_NEG = ("아니", "아직", "잠깐", "잠시", "글쎄", "모르", "쉴", "쉬고", "그만", "중단", "안 ")


def is_next_chapter_consent(text: str | None) -> bool:
    """'네/알겠습니다/좋아요/다음' 계열 → 확인으로 간주."""
    if not text:
        return False
    t = text.strip()
    if any(n in t for n in _NEXT_CONSENT_NEG):
        return False
    if is_user_consent(t) or _NEXT_CONSENT_OPENER.match(t):
        return True
    return len(t) <= 25 and any(k in t for k in NEXT_CHAPTER_CONSENT_KEYWORDS)


# 챕터별 최대 턴 수 (user 메시지 기준) — 안전망.
#   (2026-11-04 BEI) 챕터 종료는 라우트의 사례 단계(services/bei_engine, 리더 턴 예산 16~20)가 먼저 닫는다. 아래 값(35~50)은
#   그 로직이 깨졌을 때만 작동한다. test_guard_ordering 이 예산 < MAX_TURNS 를 고정한다.
MAX_TURNS: dict[str, int] = {
    "organization_management": 40,
    "performance_management": 40,
    "people_management": 50,
    "work_management": 40,
    "self_management": 35,
    "supplementary": 15,
}


def _force_rapport_category(rapport_turn_count: int) -> str:
    """라포 user 메시지 수 기반으로 이번 AI 턴의 카테고리를 강제 결정.

    rapport_turn_count = build_turn_state 실행 시점의 chapter=None user 메시지 수
    (현재 user 메시지는 아직 chapter=None 아님 → 직접 인덱스로 사용).

    0 → 일상 (시간대 활용, 첫 AI 라포 응답 — 시스템 템플릿)
    1 → 스몰톡 (2026-10-21: LLM 되받기 1~2문장 + 리더 발화에서 나온 가벼운 되물음 1개 허용. 고정 질문 없음)
    2 → 담당업무 (LLM 되받기 1문장 + 백엔드 역할 질문 RAPPORT_ROLE_QUESTION)
    3+ → 기대 (LLM 역할 반응 1문장 + 백엔드 기대 질문 RAPPORT_EXPECTATION_QUESTION, READY_FOR_INTRO 는 백엔드가 확정)
    (2026-10-19) 진단_대화 턴 삭제 — 기대 답변 다음 턴은 바로 DIAGNOSIS_INTRO.
    """
    if rapport_turn_count == 0:
        return "일상"
    elif rapport_turn_count == 1:
        return "스몰톡"
    elif rapport_turn_count == 2:
        return "담당업무"
    return "기대"


def resume_pending_for(store: dict, latest_model_msg, chapter: str | None) -> dict | None:
    """(2026-10-22 P1-1) 일시정지 제안 턴이 삼킨 instruction(pending)을 이번 턴에 재개해야 하는가.
    직전 코치 턴이 SUGGEST_PAUSE(제안) 또는 USER_REQUESTS_PAUSE(제안 뒤 '다음에' → 재개)이고 pending 챕터가 같을 때만."""
    pend = (store or {}).get("pending_instruction")
    if not isinstance(pend, dict) or not pend.get("instruction") or latest_model_msg is None:
        return None
    if pend.get("chapter") != chapter:
        return None
    if latest_model_msg.probe_type_used == "SUGGEST_PAUSE" or latest_model_msg.instruction_used == "USER_REQUESTS_PAUSE":
        return dict(pend)
    return None


def extract_expectation_answer(msgs: list) -> str | None:
    """(2026-10-16) INTRO 턴에 주입할 '기대 질문 답변'을 메시지 열에서 찾는다.

    라포 순서는 결정론: 담당 업무 질문(probe ROLE_ASK) → user(담당 업무 답) → model(기대 질문) → user(기대 답).
    즉 ROLE_ASK 모델 메시지 뒤 두 번째 user 메시지가 기대 답변이다. 마커가 없으면 None(→ 가이드가 paraphrase 를 생략).
    """
    seq = sorted(msgs, key=lambda m: (m.created_at is None, m.created_at, getattr(m, "turn_index", None) or 0))
    idx = next((i for i, m in enumerate(seq)
                if (m.role == MessageRole.MODEL or m.role == "model") and m.probe_type_used == "ROLE_ASK"), None)
    if idx is None:
        return None
    users_after = [m for m in seq[idx + 1:] if (m.role == MessageRole.USER or m.role == "user")]
    if len(users_after) < 2:
        return None
    return (users_after[1].content or "").strip() or None


def is_user_consent(text: str | None) -> bool:
    """사용자 답변이 동의/진행 의사인지 판단.

    rapport_turn_count >= 3 안전장치에서 [READY_FOR_INTRO] 강제 여부 결정.
    """
    if not text:
        return False
    stripped = text.strip().rstrip(".,!?~")
    consent_words = {
        "네", "예", "응", "좋아요", "괜찮아요", "그래요", "알겠어요",
        "ok", "OK", "oK", "Ok", "yes", "Yes", "YES", "네요", "넵", "넹",
    }
    if stripped in consent_words:
        return True
    if len(stripped) <= 12:
        negative_words = {"아니", "아직", "잠깐", "글쎄", "모르"}
        if any(neg in stripped for neg in negative_words):
            return False
        if stripped.startswith("네") or stripped.startswith("예"):
            return True
    return False


OBJECTION_KEYWORDS = [
    "얘기한 적 없",
    "말한 적 없",
    "그런 말 안",
    "말한 적이 없",
    "얘기한 적이 없",
    "한 적 없는데",
    "동의한 적 없",
    "그런 적 없",
    "언제 그런",
    "그런 말 한",
    "내가 언제",
    # 흐름 모순 지적 ("이미/지금 그거 하고 있는데?") — 상태 강제 전진 방지.
    # 일반 발화 오탐을 피하려 '지금/그거/이미/방금+반문' 조합으로 좁게 매칭.
    "지금 그거",
    "그거 하고 있",
    "지금 하고 있잖",
    "이미 했잖",
    "방금 했잖",
    "이미 말했",
    "방금 말했잖",
    "아까 말했잖",
    "이미 대답했",
    "왜 또 물어",
    "또 물어보",
    "같은 질문",
    "질문이 이상",
]

# 🔁 중복 지적(2026-09-14): "이 질문은 아까 한 것 같은데요" 류 — 항의로 잡아
#   META_QUESTION_FROM_USER 로 보내되(프로브 턴 소비 X), 가이드에서 '인정 + 이번엔
#   무엇을 다르게 보려는지 한 줄' 을 요구한다. 기존 "네, 유사한 질문이었습니다." 처럼
#   인정만 하고 옛 사건으로 되돌아가던 응답을 막는다.
DUPLICATE_CLAIM_KEYWORDS = [
    "아까 한 것 같", "아까 한것 같", "아까 했던 질문", "아까 물어", "아까 물으", "아까 질문",
    "이미 물어", "이미 물으", "전에 물어", "전에 물으", "앞에서 물", "앞서 물어",
    "비슷한 질문", "같은 질문", "같은 걸 물", "같은 거 물", "질문이 반복", "반복되는 질문",
    "또 묻", "또 물어", "방금 물어", "방금 물으", "이미 대답", "이미 답했", "아까 대답",
    "아까 답했", "아까 말씀드렸", "아까 말씀 드렸", "이미 말씀드렸",
]
OBJECTION_KEYWORDS += [k for k in DUPLICATE_CLAIM_KEYWORDS if k not in OBJECTION_KEYWORDS]


OBJECTION_MAX_LEN = 200   # 2026-09-21: 항의는 짧다. 긴 사례 서술에 '같은 질문' 같은 어절이 섞여도 항의가 아니다.


def detect_user_objection(user_response: str) -> bool:
    """사용자가 진행 흐름에 항의하는지 감지(짧은 발화 또는 물음표가 있을 때만)."""
    if not user_response:
        return False
    t = user_response.strip()
    if len(t) > OBJECTION_MAX_LEN and "?" not in t:
        return False
    return any(kw in t for kw in OBJECTION_KEYWORDS)


def detect_duplicate_claim(user_response: str | None) -> bool:
    """사용자가 '이 질문 아까 했다/같은 질문이다' 고 지적하는가(중복 지적)."""
    if not user_response:
        return False
    t = user_response.strip()
    return any(kw in t for kw in DUPLICATE_CLAIM_KEYWORDS)


def _pause_req(state: dict, text: str | None = None) -> bool:
    """(2026-10-29 P1 p13) 일시정지 요청 판정의 단일 입구 — 낱말 감지 + 실질 답변 예외(정의 답 30자·일반 60자 이상은 요청이 아님).
    p13: Lucas 자기관리 정의 답('…잠깐 쉬면서…')이 5/5 세션에서 여전히 paused — 예외가 없는 호출 지점이 남아 있었다."""
    t = state.get("last_user_response") if text is None else text
    if not detect_pause_request(t):
        return False
    return not _is_substantive_definition_answer({**state, "last_user_response": t or ""})


def _is_substantive_definition_answer(state: dict) -> bool:
    """직전 코치 턴이 정의 질문(COMPETENCY_ASK·DIAGNOSIS_CONFIRM)이고 리더 답이 30자 이상이면 '정의 답변'이다.
    일시정지·항의·메타 감지의 예외(정의 답 속 '쉬어'·'왜' 같은 낱말이 의도로 오인되는 것을 막는다)."""
    _last = state.get("last_user_response") or ""
    _n = len(_last.replace(" ", ""))
    # (2026-10-29 P1 p12) 정의 질문 뒤가 아니어도 60자 이상의 실질 답변은 일시정지 요청이 아니다 — p121_6: 정의 답이 ALIGN 뒤 한 턴 늦게 와
    #   '잠깐 쉬면서'로 세션이 paused 됐다. 실제 일시정지 요청은 짧다('잠시 쉬었다 할게요').
    if _n >= 60:
        return True
    return (state.get("last_instruction") in ("COMPETENCY_ASK", "DIAGNOSIS_CONFIRM") and _n >= 30)


def decide_instruction(state: dict) -> InstructionType:
    """현재 상태 기반으로 LLM 에게 줄 instruction 결정.

    우선순위 순서로 체크. 위에서부터 매칭되면 즉시 반환.
    """
    # === 0순위: 프롬프트 주입/역할 탈취 시도 — 어떤 단계에서든 최우선 차단 ===
    #   (내부 지시 노출·규칙 무시·역할 변경 요구, 제어 마커 직접 입력 등.
    #    가드가 없으면 라포·경계 대기 등 모든 분기가 주입 문장을 '답변'으로
    #    취급해 흐름이 오염된다.)
    if detect_prompt_injection(state.get("last_user_response")):
        return "PROMPT_INJECTION_DETECTED"

    # === 0.5순위: 3-Strike 강제 종료 + 최후 의향 확인(Warning) ===
    #   비생산 응답(남탓·욕설·비아냥·거부) 누적으로 세션을 손절하되, 곧바로
    #   끊지 않고 '경고 1턴'을 사이에 끼워 사용자에게 마지막 선택권을 준다.
    #     · 누적 2회 도달 & 아직 경고 안 함  → SESSION_ABORT_WARNING (1회)
    #     · 누적 3회 도달                    → SESSION_ABORT_3STRIKE (종료)
    #     · 경고 후에도 유효 답변 없이 회피/억지 → 즉시 SESSION_ABORT_3STRIKE
    #   (경고는 종료보다 앞서지만, 이미 3회면 바로 종료. 동의를 구하지 않음.)
    _defl = state.get("session_deflection_count", 0)
    _warned = state.get("session_already_warned", False)
    if _defl >= 3:
        return "SESSION_ABORT_3STRIKE"
    if _warned and is_unproductive_response(state.get("last_user_response")):
        # 이미 경고를 줬는데도 구체적 답변 없이 또 회피/억지 → 즉시 종료.
        return "SESSION_ABORT_3STRIKE"
    if _defl >= 2 and not _warned:
        return "SESSION_ABORT_WARNING"

    # === 0.6순위 (2026-10-22 P1-1): 일시정지 제안(SUGGEST_PAUSE) 직후 — pending instruction 그대로 실행 ===
    #   제안 턴은 되받기 + 안내만 내고 질문을 삼켰다. 리더가 '계속'이면 그 턴에 나갔어야 할 탐침을 그대로(새 앵커 금지),
    #   '다음에/잠시 쉬' 면 일시중지. 원장은 제안 턴에서 되돌려 두었으므로 같은 타겟이 다시 잡힌다.
    _pend = state.get("resume_pending")
    if _pend:
        if _pause_req(state):
            return "USER_REQUESTS_PAUSE"
        state["route_reason"] = "resume_pending"
        return _pend["instruction"]

    # === 🚦 A: 참여 이탈(disengagement) 중단 흐름 (BEI 컨텍스트에서만) ===
    #   중단 트리거는 '근거 부족'이 아니라 '참여 이탈'(A-0). 카운터/판정은
    #   diagnoses.py 가 store 에 영속하고 여기서 읽는다(pending_abort/streak).
    if state.get("chapter"):
        # A-3: 직전 ABORT_CONFIRM 에 대한 답변으로 중단 확정된 경우.
        if state.get("pending_abort"):
            return "ABORT_DISENGAGED"
        # H4: 휴식·미루기 요청(pause)은 이탈이 아니다 — ABORT_CONFIRM 보다 먼저
        #   USER_REQUESTS_PAUSE 로 분기한다(→ 11-b paused, 재개 가능). 프론트의
        #   '잠시 쉬기/다음에 하기' 버튼 문구가 이 경로를 탄다. (과거엔 A-2 가
        #   먼저 평가돼 pause 문구가 ABORT_CONFIRM → aborted_disengaged 로 갔다.)
        #   (2026-10-29) 정의 질문에 대한 실질 답변(30자 이상)은 예외 — s291 Lucas 자기관리 정의 답 '…잠깐 쉬면서 다시 집중하는 것도'
        #   의 '쉬면서'가 여기(H4)서 일시정지로 읽혀 Stage 4 의 예외에 닿기 전에 USER_REQUESTS_PAUSE 가 나갔다.
        if _pause_req(state):
            return "USER_REQUESTS_PAUSE"
        # A-2: 중단 확인 진입 — 명시적 거부(즉시) OR 연속 3회 이탈 & 최소 5사이클.
        #   (계속 선택 시 diagnoses.py 가 streak 리셋 → 여기 재진입 안 함)
        if not state.get("awaiting_abort_decision"):
            _refuse = state.get("last_refusal", False)
            _stk = state.get("disengagement_streak", 0)
            _cyc = state.get("probe_cycles", 0)
            if _refuse or (_stk >= 3 and _cyc >= 5):
                return "ABORT_CONFIRM"

    # === 최우선: 챕터 종료 후 '계속/휴식' 의사 대기 중이면 사용자 답변으로 분기 ===
    #   직전 AI 턴(CHAPTER_READY_TO_END)이 "계속할까요, 쉴까요?"를 물었고
    #   아직 챕터를 전환하지 않은 상태. 사용자 답변 의도로 분기한다.
    #   - 항의/메타 질문 → META_QUESTION_FROM_USER (🛡️ 상태 보존: 강제 전진
    #     금지. "지금 그거 하고 있잖아" 같은 예외 지적을 '계속 동의'로
    #     오판해 다음 챕터 ALIGN 으로 밀어붙이면 AI 가 하위 역량을 지어내는
    #     환각이 발생한다. 다음 턴에 조건이 유지되면 경계 질문을 다시 묻는다.)
    #   - 휴식 의도 → USER_REQUESTS_PAUSE (일시중지, 챕터 전환 차단)
    #   - 명확한 계속/동의 → CHAPTER_CONTINUE_CONFIRMED (다음 챕터로 전환)
    # (2026-09-17) 경계 '계속/휴식' 대기 분기 삭제 — 마커가 어디서도 세워지지 않던 죽은 경로.
    #   전환 팝업 대기는 아래 awaiting_next_chapter_choice 가 맡는다.

    # === 0.55순위(2026-09-16): 챕터 전환 직후 '다음 챕터로 이동' 팝업 대기 중 텍스트 도착 ===
    #   직전 코치 발화가 CHAPTER_READY_TO_END(전환 예고)였고 새 챕터의 정의 질문이 아직 안 나갔다.
    #   '네/알겠습니다/좋아요/다음' 계열은 확인으로 간주 → 아래 정의 질문(COMPETENCY_ASK) 경로로 통과.
    #   휴식 의도 → 일시중지. 그 외 텍스트 → "버튼으로 선택해 주세요" 안내만 돌려주고 상태를 바꾸지
    #   않는다(이전 챕터 탐침 재개·정의 답변 오인 방지 — 프론트 입력 잠금과 이중 방어).
    if state.get("awaiting_next_chapter_choice"):
        _txt = state.get("last_user_response") or ""
        if _pause_req(state, _txt):
            return "USER_REQUESTS_PAUSE"
        if detect_user_objection(_txt) or detect_meta_question(_txt):
            return "META_QUESTION_FROM_USER"
        if not is_next_chapter_consent(_txt):
            return "AWAIT_NEXT_CHAPTER_CHOICE"

    # === 0.7순위: 사용자의 '종료 수용/요청' 감지 (상태 동기화 버그 방어) ===
    #   사용자가 "이제 끝내죠/마무리하죠/감사합니다" 로 종료 의사를 밝혔는데
    #   회피(AVOIDANCE)로 오분류되면, 코치는 작별 인사를 하면서도 상태는
    #   in_progress 에 머물러 프론트가 무한 루프에 빠진다.
    #   - 마지막 챕터(자기관리): 명시적 종료 → 즉시 CHAPTER_READY_TO_END
    #     (→ Grand Finale → status=completed, 5번째 뱃지 점등).
    #     감사/작별 인사(soft)는 어느 정도 진행된 뒤에만 종료로 해석
    #     (초반의 예의상 인사를 종료로 오판 방지).
    #   - 중간 챕터: 명시적 종료 요청은 일시중지(재개 가능)로 처리.
    #     soft(감사 인사)는 무시 — 대화 중 예의 표현일 뿐.
    if state.get("chapter_started"):
        _closing = detect_closing_intent(state.get("last_user_response"))
        if _closing:
            _is_final = state.get("chapter") == "self_management"
            if _is_final:
                _progressed = (
                    state.get("turn_count", 0) >= 3
                    or state.get("events_collected", 0) >= 1
                )
                # 명시적 종료 = 사용자 자율성 우선(즉시 종료). soft(감사 인사)는 진행된 뒤, 사례 단계가 SWEEP 이후일 때만.
                if _closing == "explicit":
                    return "CHAPTER_READY_TO_END"
                if _progressed and state.get("bei_state") in ("sweep", "close"):
                    return "CHAPTER_READY_TO_END"
            elif _closing == "explicit":
                # (2026-11-04 BEI) 중간 챕터의 명시적 종료 요청: 바로 요약 + 다음 챕터('하나만 더' 폐지). 못 들은 하위역량은 미탐색으로 남는다.
                return "CHAPTER_READY_TO_END"

    # === 7단계 코칭 프로세스: 한 턴에 한 스텝, 엄격한 순서 (압축·건너뛰기 금지) ===
    #   Step1 인사+이름확인 → Step2 라포(아이스브레이킹) → Step3 시작 동의 →
    #   Step4 로드맵 안내 → Step5 평소 생각/정의 묻기 →
    #   Step6 수용+공식정의·하위역량 → Step7 STAR 경험 진단
    rapport_complete = state.get("rapport_complete", False)
    intro_done = state.get("intro_done", False)
    chapter_started = state.get("chapter_started", False)
    rapport_turn_count = state.get("rapport_turn_count", 0)
    turn_count_total = state.get("turn_count", 0) + rapport_turn_count
    ONBOARDING_MAX_TURNS = 8
    RAPPORT_MAX_TURNS = 5  # 무한 라포 방지 안전장치 (2026-10-21: 스몰톡 턴 추가로 정상 라포는 4턴에 끝난다)

    # Step 1-0: 이름 재확인 (Fallback) — 첫 발화에서 명확한 성함을 못 뽑았고
    #   아직 재확인을 안 했다면, 임의 명사를 이름으로 부르지 말고 1회에 한해
    #   호칭을 정중히 되묻는다. (예: '환영은 무슨...' 비아냥 → '환영은' 오추출
    #   방지). 재확인 후에도 못 뽑으면 marker 가 남아 기본 호칭 '리더님'으로 폴백.
    if (not rapport_complete
            and state.get("name_extraction_failed", False)
            and not state.get("name_reconfirm_asked", False)):
        return "NAME_RECONFIRM"

    # Step 1-3: 라포 (이름확인 → 아이스브레이킹 1~2 → 시작 동의)
    # 사용자 '시작 동의'([READY_FOR_INTRO]) 전까지 라포 유지. 동의 없이 진도 X.
    if not rapport_complete and rapport_turn_count < RAPPORT_MAX_TURNS:
        return "RAPPORT_BUILDING"

    # Step 4: 진단 목적·로드맵 안내 (전체 1회, 첫 영역에서)
    if not intro_done:
        return "DIAGNOSIS_INTRO"

    # §7-1: 온보딩 하드 캡 — 라포가 상한을 넘으면 항의·일시중지·메타 분기를 건너뛰고
    #   곧바로 정의 질문(DIAGNOSIS_CONFIRM)으로 간다. 미확보 정보(호칭 등)는 기본값.
    #   (2026-10-16 kjpark 사고) 과거엔 '라포 + 현재 메시지(turn_count=1)' 합이 6 이면
    #   COMPETENCY_ALIGN 으로 직행해 정의 질문이 통째로 빠졌다 — 정상 온보딩(이름·일상·
    #   담당업무·기대·진단_대화 5턴 + 인트로)에서도 발동하는 off-by-one 이었다.
    #   · 비교는 rapport_turn_count 만(현재 메시지 +1 제외).
    #   · 목적지는 항상 DIAGNOSIS_CONFIRM. 정의 질문 없이 ALIGN 이 나가는 경로는 없다.
    #   · CONFIRM 무한 반복(투머치토커 71턴 사고)은 CONFIRM 이 START_CHAPTER 로 태깅돼
    #     다음 턴 chapter_started=True 가 되는 것으로 이미 막힌다.
    ONBOARDING_HARD_CAP = 6   # (2026-10-21) 스몰톡 턴 추가로 정상 온보딩은 CONFIRM 시점 rapport_turn_count=5
    if not chapter_started and rapport_turn_count >= ONBOARDING_HARD_CAP:
        return "DIAGNOSIS_CONFIRM"

    # Step 5: 해당 역량 평소 생각/정의 묻기 (챕터별)
    # 챕터 2+ 는 직전 영역과 브리지하며 진입 (CONFIRM 가이드가 분기).
    if not chapter_started:
        _last0 = state.get("last_user_response") or ""
        if detect_user_objection(_last0):
            return "META_QUESTION_FROM_USER"
        if _pause_req(state, _last0):
            return "USER_REQUESTS_PAUSE"
        if detect_meta_question(_last0):
            return "META_QUESTION_FROM_USER"
        return "DIAGNOSIS_CONFIRM"

    # Stage 4 진입 전: 사용자 항의·일시중지·메타 우선 처리
    # chapter_started(또는 competency_aligned)이면 스크립트가 이미 진행 중
    # → 이 시점에 사용자 항의가 오면 스크립트 강행 금지
    if chapter_started or state.get("competency_aligned"):
        _last = state.get("last_user_response") or ""
        # (2026-10-29) 정의 질문(COMPETENCY_ASK·DIAGNOSIS_CONFIRM)에 대한 '실질 답변'(30자 이상)은 일시정지·메타로 돌리지 않는다.
        #   10/28 Lucas 자기관리: 정의 답 "…잠깐 쉬어가는 것도 중요하게" 의 '쉬어'가 일시정지로 읽혀 정의→ALIGN 사이에 탐침 턴이 끼었다.
        _is_definition_answer = _is_substantive_definition_answer(state)
        if detect_user_objection(_last) and not _is_definition_answer:
            state["route_reason"] = "objection"
            return "META_QUESTION_FROM_USER"
        if _pause_req(state, _last):
            return "USER_REQUESTS_PAUSE"
        if detect_meta_question(_last) and not _is_definition_answer:
            state["route_reason"] = "meta"
            return "META_QUESTION_FROM_USER"

    # Stage 4: 챕터 진입 (역량 합의 → 첫 BEI)
    # 작업 24: COMPETENCY_INTRO 단계 skip (CONFIRM 에서 통합됨).
    # 사용자 정의 답변 → 바로 COMPETENCY_ALIGN.
    if chapter_started or turn_count_total > ONBOARDING_MAX_TURNS:
        competency_aligned = state.get("competency_aligned", False)
        chapter_msg_count = state.get("chapter_message_count", 0)

        # 4-0: 정의 '질문'(Step 5) — 챕터마다 1회. 브릿지의 조기 START_CHAPTER
        #   태깅으로 chapter_started 가 미리 True 여도, 이 챕터에서 아직 정의를
        #   묻지 않았으면 먼저 묻는다(①질문). 다음 턴 사용자 답변 후 ②COMPETENCY_ALIGN.
        if not state.get("definition_asked", False) and not competency_aligned:
            return "COMPETENCY_ASK"

        # 4-1: 역량 합의 (사용자 답변 반영 + 공식 정의 + 하위역량 목록)
        #   불변식: 이 챕터에서 정의 질문(definition_asked)이 나간 뒤에만 ALIGN. (4-0 이 먼저 걸러주지만 명시)
        if not competency_aligned and state.get("definition_asked", False):
            return "COMPETENCY_ALIGN"

    last_response = state.get("last_user_response")

    # 2. 의미 없는 입력
    if is_invalid_input(last_response):
        return "INVALID_INPUT"

    # 3. 사용자 종료 요청 (회피보다 우선) — (2026-10-29 P1 p13) 실질 답변 예외 포함 단일 입구
    if _pause_req(state, last_response):
        return "USER_REQUESTS_PAUSE"

    # 4. 메타 질문
    if detect_meta_question(last_response):
        return "META_QUESTION_FROM_USER"

    # 5. 안전망: 챕터 user 턴이 MAX_TURNS(35~50)를 넘으면 닫는다 — 정상 흐름에선 사례 단계 예산(16~20)이 먼저 닫는다.
    if state["turn_count"] >= MAX_TURNS.get(state["chapter"], 40):
        state["route_reason"] = "max_turns"
        return "CHAPTER_READY_TO_END"

    # 6. (2026-11-04 BEI) 사례 단계가 이미 '닫힘'이면 종료 턴
    if state.get("bei_state") == "close":
        return "CHAPTER_READY_TO_END"

    # 7. 기본: 사례 탐침. 사례 열기(EPISODE_OPEN)·재질문(EPISODE_RETRY)·보완(SWEEP_ANCHOR/FOLLOWUP)·종료는 라우트의 BEI 단계가
    #    슬롯 판정(Haiku) 뒤에 결정해 덮어쓴다 — 회피·단답은 instruction 이 아니라 사례 카드의 '신호' 한 줄로 LLM 에 전달된다.
    return "EPISODE_PROBE"


async def build_turn_state(
    db: AsyncSession,
    session_id: UUID,
    chapter: str,
    *,
    messages: list | None = None,
    events_all: list | None = None,
) -> dict:
    """매 턴마다 호출되어 Layer 3 state dict 생성.

    (2026-09-22) 턴 스냅샷: 호출자가 세션의 전체 메시지·사건을 한 번 읽어 넘기면 여기서는 SQL 을 내지 않는다
    (이전엔 같은 chat_messages 를 조건만 바꿔 22번 읽었다 — Render→DB 왕복 4.7초의 주범). 넘기지 않으면 2번만 읽는다.
    """
    if messages is None:
        _mr = await db.execute(
            select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at.asc())
        )
        messages = list(_mr.scalars().all())
    if events_all is None:
        _er = await db.execute(select(Event).where(Event.session_id == session_id).order_by(Event.sequence_num))
        events_all = list(_er.scalars().all())

    def _is_model(m) -> bool:
        return m.role == MessageRole.MODEL or m.role == "model"

    def _is_user(m) -> bool:
        return m.role == MessageRole.USER or m.role == "user"

    _msgs = sorted(messages, key=lambda m: (m.created_at is None, m.created_at, m.turn_index or 0))
    _model_msgs = [m for m in _msgs if _is_model(m)]
    _ch_model = [m for m in _model_msgs if m.chapter == chapter]

    # 1. 사건 정보 수집
    events = [e for e in events_all if e.chapter == chapter]

    # 2. 이 챕터의 user 메시지 수 (turn_count)
    user_messages = [m for m in _msgs if _is_user(m) and m.chapter == chapter]
    # 1-c: 최근 사용자 답변의 '실질 응답' 연속 수(engaged & 공백 제외 30자 이상).
    #   무수확 최후통첩은 이 값이 2 이상이면 발동하지 않는다(성실 응답자 추궁 금지).
    turn_count = len(user_messages)

    # 2-b. 🚨 3-Strike: 세션 '전체'(챕터 무관)의 비생산 응답 누적 카운트.
    all_user_msgs = [m for m in _msgs if _is_user(m)]
    session_deflection_count = sum(
        1 for m in all_user_msgs if detect_session_abort_signal(m.content)
    )

    # 3. 마지막 user 메시지
    last_response = user_messages[-1].content if user_messages else None

    # 6. 이전 챕터 사건(지난 사례 참고용)
    prev_events = [e for e in events_all if e.chapter != chapter and e.is_complete]

    # 6-b. Global Memory: 전 챕터 + 현재 챕터의 '완료된' 모든 사건 요약.
    #   LLM 이 챕터 전환 후에도 과거 사례 전체를 기억해 '복붙 중복'을 캐치.
    from diag_project.data.competencies import COMPETENCY_FRAMEWORK as _CF
    _all_done_events = list(prev_events) + [e for e in events if e.is_complete]
    all_collected_events = []
    for e in _all_done_events:
        _cname = _CF.get(e.chapter, {}).get("name", e.chapter)
        _title = e.summary or (e.core_action or "")[:60] or "(요약 없음)"
        all_collected_events.append({
            "chapter": _cname,
            "summary": _title,
            "mapped_subcompetency": getattr(e, "mapped_subcompetency", None),
        })

    # 7. 회피 감지
    contains_avoidance = check_avoidance(last_response)

    # 8-0b. 세션 강제 종료 '경고(Warning)'를 이미 1회 냈는지 (probe 마커).
    #   경고를 이미 줬다면 다음 회피 턴에서 곧바로 종료(재경고 루프 방지).
    session_already_warned = any(m.probe_type_used == "ABORT_WARNING" for m in _model_msgs)

    # 8-0c. 이름 재확인(NAME_RECONFIRM)을 이미 1회 물었는지 (probe 마커).
    #   재확인 후에도 성함을 못 뽑으면 기본 호칭 '리더님'으로 폴백(재질문 X).
    name_reconfirm_asked = any(m.probe_type_used == "NAME_RECONFIRM" for m in _model_msgs)

    # 8-a. 마커 1: 라포 완료 → 인트로 진입 ([READY_FOR_INTRO] 또는 하위호환 RAPPORT_COMPLETE)
    rapport_complete = any(m.probe_type_used in ("READY_FOR_INTRO", "RAPPORT_COMPLETE") for m in _model_msgs)

    # 8-a2. 마커 2: 인트로 완료 (instruction_used == "DIAGNOSIS_INTRO" 인 model 메시지)
    intro_done = any(m.instruction_used == "DIAGNOSIS_INTRO" for m in _model_msgs)

    # 8-a3. 마커 3: 챕터 시작 신호 (probe_type_used == "START_CHAPTER" 인 model 메시지)
    chapter_started = any(m.probe_type_used == "START_CHAPTER" for m in _ch_model)

    # 8-a3b. 직전(가장 최근) AI 메시지 — 전환 예고 직후 판정(awaiting_next_chapter_choice)에 쓴다.
    latest_model_msg = _model_msgs[-1] if _model_msgs else None
    # 2026-09-16: 전환 예고(CHAPTER_READY_TO_END) 직후 = 프론트 '다음 챕터로 이동' 팝업 대기.
    #   정의 질문(definition_asked)이 나가기 전까지만 True. (아래 definition_asked 계산 뒤 확정)
    _after_transition = (
        latest_model_msg is not None
        and latest_model_msg.instruction_used == "CHAPTER_READY_TO_END"
        and latest_model_msg.probe_type_used == "START_CHAPTER"
    )

    # 8-a3c. 코치의 '조기 종료 제안(SUGGEST_PAUSE)' 누적 횟수.
    #   2-Strike 규칙: 제안은 최대 2회 — 2회를 넘기면 3번째부터는 제안이
    #   아니라 강제 종료(SESSION_END_EARLY)로 전환해야 한다.
    suggest_pause_count = sum(1 for m in _model_msgs if m.probe_type_used == "SUGGEST_PAUSE")

    # 8-a4. CONFIRM 턴 수 (DIAGNOSIS_CONFIRM 으로 저장된 model 메시지 수)
    confirm_turn_count = sum(1 for m in _model_msgs if m.instruction_used == "DIAGNOSIS_CONFIRM")

    # 8-b. 라포 턴 수 (chapter=NULL 인 user 메시지 — 라포 완료 후 소급 변경된 것들)
    rapport_messages = [m for m in all_user_msgs if m.chapter is None]
    rapport_turn_count = len(rapport_messages)

    # 8-c. 이 챕터의 실제 BEI AI 메시지 수 (CHAPTER_OPENING 발화 판별용).
    # 진단 전 단계(INTRO/CONFIRM/ALIGN/INTRO)는 제외 — 아직 BEI 시작 전이므로.
    # ⚠️ DIAGNOSIS_CONFIRM 은 START_CHAPTER 마커 때문에 chapter 로 태깅되므로
    #    반드시 제외해야 CHAPTER_OPENING(첫 BEI 템플릿)이 정상 발화함.
    from diag_project.services.event_tracker import INPUT_ANOMALY_INSTRUCTIONS as _IAI
    _NON_BEI = {"COMPETENCY_INTRO", "COMPETENCY_ALIGN", "DIAGNOSIS_CONFIRM", "DIAGNOSIS_INTRO",
                # 종결+전환 경계·'계속' 브릿지는 다음 챕터로 태깅되므로 제외해야 첫 BEI(CHAPTER_OPENING) 판별이 맞는다
                "CHAPTER_READY_TO_END", "CHAPTER_CONTINUE_CONFIRMED"} | set(_IAI)   # (2026-10-28 P0-4) 입력 이상 턴도 BEI 아님
    # SQL NOT IN 은 NULL 을 제외했으므로 instruction_used 가 None 인 행도 세지 않는다(동일 의미 유지)
    chapter_message_count = sum(1 for m in _ch_model if m.instruction_used is not None and m.instruction_used not in _NON_BEI)

    # 8-d. 역량 합의 마커
    competency_intro_done = any(m.instruction_used == "COMPETENCY_INTRO" for m in _ch_model)

    competency_aligned = any(m.instruction_used == "COMPETENCY_ALIGN" for m in _ch_model)

    # 🐛 fix(1·5): 정의 '질문' 스텝은 챕터마다 1회여야 한다. 기존엔 첫 챕터의
    #   DIAGNOSIS_CONFIRM 에만 융합돼 있고, 2번째 챕터부터는 전환 브릿지의 조기
    #   START_CHAPTER 태깅 때문에 chapter_started 가 미리 True 가 되어 질문 스텝
    #   (474)이 도달 불가였다. → 챕터별 게이트: 이 챕터에 정의 질문(COMPETENCY_ASK)
    #   또는 (첫 챕터의) DIAGNOSIS_CONFIRM 이 이미 있었는지로 판정한다.
    definition_asked = any(m.instruction_used in ("COMPETENCY_ASK", "DIAGNOSIS_CONFIRM") for m in _ch_model)
    awaiting_next_chapter_choice = bool(_after_transition and not definition_asked)

    # 8-e. 첫 세부 역량 이름 (CHAPTER_OPENING 가이드용) + 역량 framework
    from diag_project.data.competencies import COMPETENCY_FRAMEWORK
    chapter_competency = COMPETENCY_FRAMEWORK.get(chapter, {})
    indicators = chapter_competency.get("indicators", {})
    first_subcompetency_name = ""
    if indicators:
        first_key = next(iter(indicators))
        first_subcompetency_name = indicators[first_key].get("name", "")

    all_subcompetencies = [
        v.get("name", "") for v in indicators.values() if v.get("name")
    ]

    # 🔒 T2(제어 역전): asked 는 '영속 원장'(session.self_assessment_data
    #   ["asked_subs"][chapter])에서만 읽는다. 백엔드가 LLM 호출 이전에 기록한
    #   결정론적 신호 — 텍스트 스캔/LLM 판정 의존 폐기(§1-1). 넓이 지표.
    from diag_project.services.traversal import asked_for_chapter
    from diag_project.models.diagnosis_session import (
        DiagnosisSession as _DS,
    )
    _sess_asked = await db.get(_DS, session_id)
    _store = (getattr(_sess_asked, "self_assessment_data", None) or {}) \
        if _sess_asked else {}
    asked_in_chapter = asked_for_chapter(_store, chapter)
    # (2026-11-04 BEI) 사례 단계 상태 — 결정기의 종료 분기와 라우트의 BEI 단계가 같은 원장을 본다
    from diag_project.services import bei_engine as _bei
    bei_state = _bei.chapter_state(_store, chapter) if chapter else None
    # 🚦 A: 참여 이탈 상태(diagnoses.py 가 매 턴 갱신·영속). 중단 확인 판정용.
    disengagement_streak = int(_store.get("disengagement_streak", 0))
    probe_cycles = int(_store.get("probe_cycles", 0))
    last_refusal = bool(_store.get("last_refusal", False))
    awaiting_abort_decision = bool(_store.get("awaiting_abort_decision", False))
    abort_confirm_count = int(_store.get("abort_confirm_count", 0))
    pending_abort = bool(_store.get("pending_abort", False))

    # #6 문체 반복 추적: 최근 코치 발화 3개의 '시작 패턴'을 계산해 LLM 에 제약으로
    #   준다("네, ~하셨군요" 연속 2턴 금지 / 요약 되받기 3턴 1회 이하).
    #   LLM 은 스스로 턴을 세지 못하므로 백엔드가 센다.
    _recent_coach = [(m.content or "") for m in _model_msgs[-3:][::-1]]
    # 복창 판정용: 각 코치 발화 '직전'의 사용자 발화(최신 순). 이번 턴 user 메시지는
    #   아직 저장 전이므로 최신 3개가 직전 코치 턴들과 1:1 로 짝지어진다.
    _recent_user = [(m.content or "") for m in all_user_msgs[-3:][::-1]]
    from diag_project.services.style_tracker import compute_style_constraints
    style_constraints = compute_style_constraints(_recent_coach, _recent_user)

    # 직전 코치(assistant) 턴의 instruction — 2단 폴백이 '한 번만' 발동하도록.
    last_instruction = latest_model_msg.instruction_used if latest_model_msg else None

    # COMPETENCY_ALIGN 가이드용: 정의 + 세부역량 이름 목록
    if chapter_competency:
        chapter_framework_state = {
            "name": chapter_competency.get("name", ""),
            "description": chapter_competency.get("description", ""),
            "indicator_names": [
                v["name"] for v in indicators.values()
            ],
        }
    else:
        chapter_framework_state = None

    # 8-f. 호칭 확정 (P1-2) — HR 마스터(참가자명, 리포트 헤더와 동일 소스)를
    #   1순위로 사용한다. 대화 추출은 마스터가 없을 때만 폴백으로 쓴다.
    #   추출 실패 시 재질문 1회만 하고, 그래도 실패하면 조용히 '리더'로 폴백.
    user_name = "리더"
    name_extraction_failed = False

    # (1) HR 마스터 데이터 1순위
    _hr_name = None
    try:
        from diag_project.models.diagnosis_session import DiagnosisSession
        from diag_project.models.participant import Participant
        _sess = await db.get(DiagnosisSession, session_id)
        if _sess is not None:
            _p = await db.get(Participant, _sess.user_id)
            if _p is not None and getattr(_p, "name", None):
                _cand = str(_p.name).strip()
                # 마스터 값도 불용어/역할어면 폴백 (예: 'User', 'Leader')
                if _cand and not _is_blacklisted_name(_cand) \
                        and _cand.lower() not in ("user", "leader", "test"):
                    _hr_name = _cand
    except Exception:  # noqa: BLE001 — 마스터 조회 실패는 추출 폴백으로 흡수
        _hr_name = None

    if _hr_name:
        user_name = _hr_name
    else:
        # (2) 대화 추출 폴백 (불용어 필터 적용된 _extract_user_name)
        _named = next(
            (n for n in (_extract_user_name(m.content) for m in all_user_msgs)
             if n),
            None,
        )
        if _named:
            user_name = _named
        elif all_user_msgs and (all_user_msgs[0].content or "").strip():
            name_extraction_failed = True

    # 9. state 조립
    state = {
        "chapter": chapter,
        "turn_count": turn_count,
        "events_collected": len(events),
        # 회피 + 남탓/비아냥/도발을 합산 — Fail-Fast(비생산 응답 3회) 근거.
        # (단순 회피어만 세면 공격형의 남탓·비아냥이 안 잡혀 손절이 안 됨)
        "avoidance_count_in_chapter": sum(
            1 for m in user_messages if is_unproductive_response(m.content)
        ),
        "all_collected_events": all_collected_events,  # Global Memory
        "last_user_response": last_response,
        "response_length": len(last_response) if last_response else 0,
        "contains_avoidance_keywords": contains_avoidance,
        "rapport_complete": rapport_complete,
        "intro_done": intro_done,
        "chapter_started": chapter_started,
        "confirm_turn_count": confirm_turn_count,
        "rapport_turn_count": rapport_turn_count,
        "chapter_message_count": chapter_message_count,
        "competency_intro_done": competency_intro_done,
        "competency_aligned": competency_aligned,
        "definition_asked": definition_asked,
        "awaiting_next_chapter_choice": awaiting_next_chapter_choice,  # 2026-09-16 전환 팝업 대기
        # 2026-09-17 온보딩 담당 업무: 직전 코치 턴이 역할 질문(ROLE_ASK)이면 이번 사용자 답을 저장
        "role_ask_pending": bool(latest_model_msg is not None
                                 and latest_model_msg.probe_type_used == "ROLE_ASK"),
        "participant_context": _store.get("participant_context") or None,
        "suggest_pause_count": suggest_pause_count,
        "session_deflection_count": session_deflection_count,
        "session_already_warned": session_already_warned,
        "name_extraction_failed": name_extraction_failed,
        "name_reconfirm_asked": name_reconfirm_asked,
        "first_subcompetency_name": first_subcompetency_name,
        "all_subcompetencies": all_subcompetencies,
        "asked_in_chapter": asked_in_chapter,  # 파생 원장(covered ∪ SWEEP) — 분석과 같은 소스
        "bei_state": bei_state,  # (2026-11-04 BEI) confirm|align|episode|sweep|close
        "bei_turns": _bei.bei_turns(_store, chapter) if chapter else 0,
        "style_constraints": style_constraints,  # #6 문체 반복 제약(시스템 계산)
        # #2: ALIGN 턴에 첫 앵커가 이미 붙었는가(원장 표식) → CHAPTER_OPENING 재발화 방지
        "opening_merged": bool(
            (_store.get("opening_merged") or {}).get(chapter)
        ) if chapter else False,
        "last_instruction": last_instruction,  # 2단 폴백 1회 제한용
        "disengagement_streak": disengagement_streak,  # 🚦 A 연속 이탈
        "probe_cycles": probe_cycles,
        "last_refusal": last_refusal,
        "awaiting_abort_decision": awaiting_abort_decision,
        "abort_confirm_count": abort_confirm_count,
        "pending_abort": pending_abort,
        "user_name": user_name,
        "chapter_framework": chapter_framework_state,
        # (2026-10-16) INTRO 가이드 변수: 리더가 '기대' 질문에 실제로 한 답(없으면 None → paraphrase 생략)
        "expectation_answer": extract_expectation_answer(_msgs),
        # (2026-10-22 P1-1) 직전 코치 턴이 일시정지 제안(또는 그 직후 일시중지)이고 pending 이 같은 챕터면 → 그대로 실행
        "resume_pending": resume_pending_for(_store, latest_model_msg, chapter),
    }

    # 9-d. 시간 정보 (라포 단계 LLM 자연스러운 응답 위해)
    from diag_project.services.time_greeting import get_time_greeting
    time_info = get_time_greeting()
    state["current_hour_text"] = time_info["hour_text"]
    state["current_time_tone"] = time_info["tone"]
    state["current_ampm_phrase"] = time_info["ampm_phrase"]
    state["current_greeting_question"] = time_info.get("greeting_question")   # (2026-11-04 P3-5) 11~12시 '오전 마무리는 어떠세요?'

    # 9-e. 라포 카테고리 강제 결정 (가이드 약속이 아닌 시스템 명령)
    state["forced_rapport_category"] = _force_rapport_category(rapport_turn_count)

    # 9-f. (2026-10-19) READY_FOR_INTRO 는 백엔드가 확정한다 — 기대 질문을 붙이는 턴(rapport_turn_count>=2)이면
    #   라포 완료. 기대 답변 다음 턴은 바로 DIAGNOSIS_INTRO(사이의 진단_대화 턴 삭제). LLM 마커·동의 판정에 기대지 않는다.
    force_ready_for_intro = rapport_turn_count >= 3   # (2026-10-21) 기대 질문 턴은 rapport_turn_count==3
    state["force_ready_for_intro"] = force_ready_for_intro

    # 10. instruction 결정
    state["instruction_for_this_turn"] = decide_instruction(state)

    return state
