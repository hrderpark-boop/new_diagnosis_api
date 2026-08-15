"""Instruction Decider (Phase 3-A 두뇌)

매 턴마다 LLM 에게 줄 명시적 지시 (instruction) 를 결정한다.
15가지 instruction 중 하나를 선택해 LLM 의 다음 행동을 결정.

설계 출처: docs/phase3a/01_design.md (Section 7.4-7.5)
"""

from typing import Literal
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from diag_project.models.event import Event
from diag_project.models.diagnosis_session import ChatMessage
from diag_project.services.avoidance_detector import (
    check_avoidance,
    is_unproductive_response,
    detect_deflection,
    detect_rush,
    detect_session_abort_signal,
    detect_pause_request,
    detect_meta_question,
    detect_prompt_injection,
    detect_abstract_avoidance,
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
    import re
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
    match = re.search(
        r'([가-힣]{2,4}?)'
        r'(?:이라고\s*(?:합니다|해요|불러)|라고\s*(?:합니다|해요|불러)'
        r'|이라고요|이라고|라고요|라고'
        r'|입니다|이에요|예요|이야|이고|이며|이라)',
        text,
    )
    if match and (nm := _clean(match.group(1))):
        return nm

    # 명확한 자기소개가 없음 → 억지로 뽑지 않고 None.
    return None


def _norm_sub(text: str) -> str:
    """하위역량 이름 정규화 — 공백·괄호 내용 제거 (방어 매칭용)."""
    return text.strip().replace(" ", "").split("(")[0]


def _match_subcompetency(
    tagged: str | None, all_names: list[str]
) -> str | None:
    """LLM 이 태깅한 하위역량 값을 4개 정식 이름 중 하나로 안전 매칭.

    정확히 일치하지 않아도(예: '변화 관리' vs '변화관리(변화지향)')
    정규화·부분일치로 보정. 매칭 실패 시 None (방어 — 엉뚱한 값 무시).
    """
    if not tagged:
        return None
    t = tagged.strip()
    if t in all_names:
        return t
    tn = _norm_sub(t)
    if not tn:
        return None
    for name in all_names:
        nn = _norm_sub(name)
        if nn == tn or tn in nn or nn in tn:
            return name
    return None


# instruction 타입
InstructionType = Literal[
    "SESSION_ABORT_3STRIKE",
    "SESSION_ABORT_WARNING",
    "NAME_RECONFIRM",
    "ONBOARDING_LAUNCH",
    "CHAPTER_OPENING",
    "RAPPORT_BUILDING",
    "DIAGNOSIS_INTRO",
    "DIAGNOSIS_CONFIRM",
    "COMPETENCY_INTRO",
    "COMPETENCY_ALIGN",
    "CONTINUE_NORMAL",
    "STAR_INCOMPLETE",
    "STAR_COMPLETE_NEW_EVENT",
    "CONTRARY_NEEDED",
    "AVOIDANCE_DETECTED",
    "ABSTRACT_AVOIDANCE",
    "CHAPTER_NO_YIELD_ULTIMATUM",
    "DUPLICATE_SUSPECTED",
    "CROSS_CHAPTER_OPPORTUNITY",
    "CHAPTER_READY_TO_END",
    "CHAPTER_CONTINUE_CONFIRMED",
    "MAX_TURNS_REACHED",
    "USER_REQUESTS_PAUSE",
    "PROMPT_INJECTION_DETECTED",
    "META_QUESTION_FROM_USER",
    "FIRST_TURN_AVOIDANCE",
    "INVALID_INPUT",
]


# 챕터별 최소 사건 수
# T2: 두 축을 분리한다.
#  · MIN_EVENTS = 한 하위역량에서 확보할 STAR 사례의 '깊이'(사건 수)
#  · MIN_EXPLORED = 한 대역량에서 앵커를 발화할 하위역량의 '개수'(넓이)
#    = max(3, ceil(n*0.6)) — 큰 대역량일수록 더 많이 탐색(사람관리 편중 방지)
import math as _math  # noqa: E402
MIN_EVENTS: dict[str, int] = {
    "organization_management": 3,
    "performance_management": 3,
    "people_management": 3,
    "work_management": 3,
    "self_management": 3,
}
_SUB_COUNTS = {
    "organization_management": 4, "performance_management": 5,
    "people_management": 9, "work_management": 5, "self_management": 3,
}
MIN_EXPLORED: dict[str, int] = {
    k: max(3, _math.ceil(n * 0.6)) for k, n in _SUB_COUNTS.items()
}  # → 조직 3 / 성과 3 / 사람 6 / 일 3 / 자기 3 (합 18)

# 챕터별 최대 턴 수 (user 메시지 기준)
MAX_TURNS: dict[str, int] = {
    "organization_management": 40,
    "performance_management": 40,
    "people_management": 50,
    "work_management": 40,
    "self_management": 35,
    "supplementary": 15,
}

# 챕터별 '최소' BEI 턴 수 — 이 바닥을 채우기 전에는 종료 경계
# (CHAPTER_READY_TO_END)로 진입하지 않는다. 사건 수·반례 조건이 일찍
# 충족돼도 심층 질문 없이 성급하게 종료 배너가 뜨는 것을 방지.
MIN_TURNS_BEFORE_END: dict[str, int] = {
    "organization_management": 8,
    "performance_management": 8,
    "people_management": 10,
    "work_management": 8,
    "self_management": 8,
}

# N턴 무수확 방어: 한 챕터 BEI 질문을 이만큼 던졌는데도 강한 STAR(≥0.7)
# 사건이 하나도 없으면 '무한 개념화 루프'로 간주 → 최후통첩 후 강제 전환.
NO_YIELD_TURNS = 5


def _force_rapport_category(rapport_turn_count: int) -> str:
    """라포 user 메시지 수 기반으로 이번 AI 턴의 카테고리를 강제 결정.

    rapport_turn_count = build_turn_state 실행 시점의 chapter=None user 메시지 수
    (현재 user 메시지는 아직 chapter=None 아님 → 직접 인덱스로 사용).

    0 → 일상 (시간대 활용, 첫 AI 라포 응답)
    1 → 기대 (감사 + 의미 부여 + 답하기 쉬운 기대 질문)
    2+ → 진단_대화 (마무리, 사용자 시작 의지 확인)
    """
    if rapport_turn_count == 0:
        return "일상"
    elif rapport_turn_count == 1:
        return "기대"
    else:
        return "진단_대화"


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


def detect_user_objection(user_response: str) -> bool:
    """사용자가 진행 흐름에 항의하는지 감지."""
    if not user_response:
        return False
    return any(kw in user_response.strip() for kw in OBJECTION_KEYWORDS)


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

    # === 최우선: 챕터 종료 후 '계속/휴식' 의사 대기 중이면 사용자 답변으로 분기 ===
    #   직전 AI 턴(CHAPTER_READY_TO_END)이 "계속할까요, 쉴까요?"를 물었고
    #   아직 챕터를 전환하지 않은 상태. 사용자 답변 의도로 분기한다.
    #   - 항의/메타 질문 → META_QUESTION_FROM_USER (🛡️ 상태 보존: 강제 전진
    #     금지. "지금 그거 하고 있잖아" 같은 예외 지적을 '계속 동의'로
    #     오판해 다음 챕터 ALIGN 으로 밀어붙이면 AI 가 하위 역량을 지어내는
    #     환각이 발생한다. 다음 턴에 조건이 유지되면 경계 질문을 다시 묻는다.)
    #   - 휴식 의도 → USER_REQUESTS_PAUSE (일시중지, 챕터 전환 차단)
    #   - 명확한 계속/동의 → CHAPTER_CONTINUE_CONFIRMED (다음 챕터로 전환)
    if state.get("awaiting_continue_decision"):
        _decision = state.get("last_user_response") or ""
        if detect_user_objection(_decision) or detect_meta_question(_decision):
            return "META_QUESTION_FROM_USER"
        if detect_pause_request(_decision):
            return "USER_REQUESTS_PAUSE"
        if is_invalid_input(_decision):
            return "INVALID_INPUT"
        return "CHAPTER_CONTINUE_CONFIRMED"

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
                if _closing == "explicit" or _progressed:
                    return "CHAPTER_READY_TO_END"
            elif _closing == "explicit":
                return "USER_REQUESTS_PAUSE"

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
    RAPPORT_MAX_TURNS = 5  # 무한 라포 방지 안전장치

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

    # Step 5: 해당 역량 평소 생각/정의 묻기 (챕터별)
    # 챕터 2+ 는 직전 영역과 브리지하며 진입 (CONFIRM 가이드가 분기).
    if not chapter_started:
        _last0 = state.get("last_user_response") or ""
        if detect_user_objection(_last0):
            return "META_QUESTION_FROM_USER"
        if detect_pause_request(_last0):
            return "USER_REQUESTS_PAUSE"
        if detect_meta_question(_last0):
            return "META_QUESTION_FROM_USER"
        return "DIAGNOSIS_CONFIRM"

    # Stage 4 진입 전: 사용자 항의·일시중지·메타 우선 처리
    # chapter_started(또는 competency_aligned)이면 스크립트가 이미 진행 중
    # → 이 시점에 사용자 항의가 오면 스크립트 강행 금지
    if chapter_started or state.get("competency_aligned"):
        _last = state.get("last_user_response") or ""
        if detect_user_objection(_last):
            return "META_QUESTION_FROM_USER"
        if detect_pause_request(_last):
            return "USER_REQUESTS_PAUSE"
        if detect_meta_question(_last):
            return "META_QUESTION_FROM_USER"

    # Stage 4: 챕터 진입 (역량 합의 → 첫 BEI)
    # 작업 24: COMPETENCY_INTRO 단계 skip (CONFIRM 에서 통합됨).
    # 사용자 정의 답변 → 바로 COMPETENCY_ALIGN.
    if chapter_started or turn_count_total > ONBOARDING_MAX_TURNS:
        competency_aligned = state.get("competency_aligned", False)
        chapter_msg_count = state.get("chapter_message_count", 0)

        # 4-1: 역량 합의 (LLM 호응 + 시스템 framework)
        if not competency_aligned:
            return "COMPETENCY_ALIGN"

        # 4-2: 챕터 오프닝 (첫 BEI 질문)
        if chapter_msg_count == 0:
            return "CHAPTER_OPENING"

    last_response = state.get("last_user_response")

    # 2. 의미 없는 입력
    if is_invalid_input(last_response):
        return "INVALID_INPUT"

    # 3. 사용자 종료 요청 (회피보다 우선)
    if detect_pause_request(last_response):
        return "USER_REQUESTS_PAUSE"

    # 4. 메타 질문
    if detect_meta_question(last_response):
        return "META_QUESTION_FROM_USER"

    # 4-a. 🛡️ Fail-Fast: 회피/남탓/비아냥 3회 반복 → 즉시 강제 전환
    #   유효 데이터(강한 STAR) 없이 회피성 응답이 한 챕터에서 3회 이상이면,
    #   더 구슬리지 않고 "유의미한 진단 불가"를 선언하며 다음 역량으로
    #   강제 전환한다. (극단 회피 페르소나가 한 챕터에서 수십 턴 헛도는 것
    #   방지 — 최후통첩보다 먼저, 더 빠르게 손절한다.)
    _bei_turns = state.get("chapter_message_count", 0)
    _no_strong = state.get("events_with_star_70", 0) == 0
    _avoid_count = state.get("avoidance_count_in_chapter", 0)
    if _no_strong and _avoid_count >= 3 and _bei_turns >= 3:
        return "CHAPTER_READY_TO_END"  # no_yield_forced 로 무수확 강제 전환

    # 4-b. 🛡️ N턴 무수확 방어 (무한 개념화 루프 탈출):
    #   BEI 질문을 NO_YIELD_TURNS 이상 던졌는데도 강한 STAR 사건이 0이면,
    #   추상적 회피에 끌려다니는 상태 → 최후통첩 1회 후 강제 전환.
    if _bei_turns >= NO_YIELD_TURNS and _no_strong:
        if not state.get("no_yield_ultimatum_given"):
            return "CHAPTER_NO_YIELD_ULTIMATUM"      # 최후통첩 (1회)
        # 최후통첩 후에도 무수확 → 이 역량 미달 기록하고 강제 전환.
        return "CHAPTER_READY_TO_END"

    # 5. 첫 턴 회피 (라포 회복)
    if state["turn_count"] <= 2 and state["contains_avoidance_keywords"]:
        return "FIRST_TURN_AVOIDANCE"

    # 6. 일반 회피 (단답/모르겠음)
    if state["contains_avoidance_keywords"]:
        return "AVOIDANCE_DETECTED"

    # 6-b. 🛡️ 추상적 회피('그럴듯한 공허함') — 개념/이론만 늘어놓고 구체가 없음.
    #   BEI 진입 후(최소 1회 질문)에만, 구체 장면을 정면으로 압박한다.
    if _bei_turns >= 1 and detect_abstract_avoidance(last_response):
        return "ABSTRACT_AVOIDANCE"

    # 7. 중복 의심
    if state.get("duplicate_suspected"):
        return "DUPLICATE_SUSPECTED"

    # 8. 최대 턴 초과
    chapter_max = MAX_TURNS.get(state["chapter"], 40)
    if state["turn_count"] >= chapter_max:
        return "MAX_TURNS_REACHED"

    # 9. 종료 가능 체크 — T2(재도입): 깊이·넓이 두 축 + 서킷브레이커.
    #   asked 가 결정론적 원장(store)에서 오므로 넓이 게이트를 안전하게 재도입.
    from diag_project.services.traversal import (
        breadth_satisfied, chapter_over_budget,
    )
    min_events = MIN_EVENTS.get(state["chapter"], 3)
    min_turns = MIN_TURNS_BEFORE_END.get(state["chapter"], 8)
    min_explored = MIN_EXPLORED.get(state["chapter"], 3)
    _asked_ct = len(state.get("asked_in_chapter") or [])
    _depth_ok = (state["events_with_star_70"] >= min_events
                 and state["has_contrary_probe"]
                 and state["turn_count"] >= min_turns)
    _breadth_ok = breadth_satisfied(_asked_ct, min_explored)
    if _depth_ok and _breadth_ok:
        return "CHAPTER_READY_TO_END"
    # 🛡️ 서킷브레이커: 챕터 턴 상한 초과 → 미탐색은 남긴 채 강제 종료(235턴 방지)
    if chapter_over_budget(state["turn_count"], min_explored):
        return "CHAPTER_READY_TO_END"

    # 10. 반례 탐침 필요
    if should_do_contrary(state):
        return "CONTRARY_NEEDED"

    # 11. 자기관리 크로스 챕터 (특수)
    if (state["chapter"] == "self_management"
            and state["turn_count"] >= 12
            and state.get("cross_chapter_signals")):
        return "CROSS_CHAPTER_OPPORTUNITY"

    # 12. 사건 진행 상태에 따라
    _all_subs = state.get("all_subcompetencies") or []
    _all_explored = bool(_all_subs) and not state.get(
        "unexplored_subcompetencies"
    )
    if state.get("current_event_id"):
        coverage = state.get("current_event_star_coverage") or {}
        if coverage and all(coverage.values()):
            # 🛡️ 탈출구 A: 사건은 완결됐고 더 탐색할 하위역량이 없으면
            # 새 사건을 청하지 말고 즉시 종료 경계로 전진.
            # (마지막 챕터면 CHAPTER_READY_TO_END → Grand Finale →
            #  DIAGNOSIS_COMPLETE 로 확실히 종결 — 제자리 루프 방지)
            if _all_explored:
                return "CHAPTER_READY_TO_END"
            return "STAR_COMPLETE_NEW_EVENT"
        else:
            return "STAR_INCOMPLETE"

    # 12-b. 🛡️ 탈출구 B: 활성 사건도 없고 모든 하위역량 탐색 완료.
    #   #9(사건 수·반례·최소 턴) 카운터가 태깅 누락 등으로 뒤처져 있어도,
    #   실질적으로 더 물을 것이 없는 상태 → 종료 경계로 강제 전진.
    #   (이 탈출구가 없으면 CONTINUE_NORMAL 에 갇혀 같은 요약을 반복하는
    #    앵무새 루프가 발생한다. 사용자 '네' 단답도 여기로 흡수돼 전진.)
    if _all_explored and state.get("events_collected", 0) >= 1:
        return "CHAPTER_READY_TO_END"

    # 13. 기본 진행
    return "CONTINUE_NORMAL"


def should_do_contrary(state: dict) -> bool:
    """반례 탐침을 지금 수행해야 하는지 판단."""
    if state["has_contrary_probe"]:
        return False  # 이미 했음

    # 타이밍 1: 첫 사건 완료 직후
    if (state["events_with_star_70"] >= 1
            and state["events_collected"] == 1):
        return True

    # 타이밍 2: 사건 사이 (현재 활성 사건 없음)
    if (state["events_with_star_70"] >= 1
            and not state.get("current_event_id")):
        return True

    # 타이밍 3: 안전망 (챕터 후반부)
    chapter_max = MAX_TURNS.get(state["chapter"], 40)
    if state["turn_count"] >= chapter_max - 5:
        return True

    return False


async def build_turn_state(
    db: AsyncSession,
    session_id: UUID,
    chapter: str,
) -> dict:
    """매 턴마다 호출되어 Layer 3 state dict 생성.

    DB에서 이 챕터의 모든 정보를 모아 LLM 호출 전 state 객체로 반환.
    """
    # 1. 사건 정보 수집
    event_result = await db.execute(
        select(Event)
        .where(Event.session_id == session_id)
        .where(Event.chapter == chapter)
        .order_by(Event.sequence_num)
    )
    events = event_result.scalars().all()

    # 2. 이 챕터의 user 메시지 수 (turn_count)
    msg_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .where(ChatMessage.chapter == chapter)
        .where(ChatMessage.role == "user")
    )
    user_messages = msg_result.scalars().all()
    turn_count = len(user_messages)

    # 2-b. 🚨 3-Strike: 세션 '전체'(챕터 무관)의 비생산 응답 누적 카운트.
    #   남탓·욕설·비아냥·거부(detect_deflection)가 세션 통틀어 3회 도달하면
    #   챕터 전환이 아니라 세션 자체를 강제 종료(Abort)한다.
    all_user_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .where(ChatMessage.role == "user")
        .order_by(ChatMessage.created_at.asc())
    )
    all_user_msgs = list(all_user_result.scalars().all())
    # 세션 강제 종료 누적 카운트: 남탓·비아냥·도발(deflection) + 재촉·시간불평
    #   (rush) 을 함께 센다. 성실한 단답형의 단순 짧은 답변은 제외(챕터
    #   Fail-Fast 가 처리). → "빨리 합시다"류 재촉도 종료 카운트에 포함.
    session_deflection_count = sum(
        1 for m in all_user_msgs if detect_session_abort_signal(m.content)
    )

    # 3. 마지막 user 메시지
    last_response = user_messages[-1].content if user_messages else None

    # 4. 활성 사건 (is_complete == False)
    active_event = next((e for e in events if not e.is_complete), None)

    # 5. STAR 커버리지
    if active_event:
        coverage = {
            "S": bool(active_event.situation),
            "T": bool(active_event.task),
            "A": bool(active_event.action),
            "R": bool(active_event.result),
        }
    else:
        coverage = None

    # 6. 이전 챕터 사건 (중복 검출용 메타데이터)
    prev_result = await db.execute(
        select(Event)
        .where(Event.session_id == session_id)
        .where(Event.chapter != chapter)
        .where(Event.is_complete == True)  # noqa: E712
    )
    prev_events = prev_result.scalars().all()

    existing_for_check = [
        {
            "event_id": str(e.id),
            "chapter": e.chapter,
            "summary": e.summary,
            "key_person": e.key_person,
            "time_context": e.time_context,
            "core_action": e.core_action,
            "tags": e.tags,
        }
        for e in prev_events
    ]

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

    # 8. 반례 수행 여부 (probe_type_used == "CONTRARY" 인 assistant 메시지)
    contrary_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .where(ChatMessage.chapter == chapter)
        .where(ChatMessage.role == "model")
        .where(ChatMessage.probe_type_used == "CONTRARY")
    )
    has_contrary = contrary_result.scalars().first() is not None

    # 8-0. N턴 무수확 '최후통첩'을 이 챕터에서 이미 던졌는지 (probe 마커).
    ultimatum_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .where(ChatMessage.chapter == chapter)
        .where(ChatMessage.role == "model")
        .where(ChatMessage.probe_type_used == "NO_YIELD_ULTIMATUM")
    )
    no_yield_ultimatum_given = ultimatum_result.scalars().first() is not None

    # 8-0b. 세션 강제 종료 '경고(Warning)'를 이미 1회 냈는지 (probe 마커).
    #   경고를 이미 줬다면 다음 회피 턴에서 곧바로 종료(재경고 루프 방지).
    warning_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .where(ChatMessage.role == "model")
        .where(ChatMessage.probe_type_used == "ABORT_WARNING")
    )
    session_already_warned = warning_result.scalars().first() is not None

    # 8-0c. 이름 재확인(NAME_RECONFIRM)을 이미 1회 물었는지 (probe 마커).
    #   재확인 후에도 성함을 못 뽑으면 기본 호칭 '리더님'으로 폴백(재질문 X).
    reconfirm_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .where(ChatMessage.role == "model")
        .where(ChatMessage.probe_type_used == "NAME_RECONFIRM")
    )
    name_reconfirm_asked = reconfirm_result.scalars().first() is not None

    # 8-a. 마커 1: 라포 완료 → 인트로 진입 ([READY_FOR_INTRO] 또는 하위호환 RAPPORT_COMPLETE)
    rapport_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .where(ChatMessage.role == "model")
        .where(ChatMessage.probe_type_used.in_(["READY_FOR_INTRO", "RAPPORT_COMPLETE"]))
    )
    rapport_complete = rapport_result.scalars().first() is not None

    # 8-a2. 마커 2: 인트로 완료 (instruction_used == "DIAGNOSIS_INTRO" 인 model 메시지)
    intro_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .where(ChatMessage.role == "model")
        .where(ChatMessage.instruction_used == "DIAGNOSIS_INTRO")
    )
    intro_done = intro_result.scalars().first() is not None

    # 8-a3. 마커 3: 챕터 시작 신호 (probe_type_used == "START_CHAPTER" 인 model 메시지)
    chapter_started_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .where(ChatMessage.chapter == chapter)
        .where(ChatMessage.role == "model")
        .where(ChatMessage.probe_type_used == "START_CHAPTER")
    )
    chapter_started = chapter_started_result.scalars().first() is not None

    # 8-a3b. 챕터 종료 후 '계속/휴식' 의사 대기 여부.
    #   직전(가장 최근) AI 메시지가 AWAIT_CONTINUE 마커면, 방금 "계속할까요/
    #   쉴까요?"를 물어놓고 사용자 답을 기다리는 상태 → 이번 user 턴이 '결정 턴'.
    latest_model_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .where(ChatMessage.role == "model")
        .order_by(ChatMessage.created_at.desc())
        .limit(1)
    )
    latest_model_msg = latest_model_result.scalars().first()
    awaiting_continue_decision = (
        latest_model_msg is not None
        and latest_model_msg.probe_type_used == "AWAIT_CONTINUE"
    )

    # 8-a3c. 코치의 '조기 종료 제안(SUGGEST_PAUSE)' 누적 횟수.
    #   2-Strike 규칙: 제안은 최대 2회 — 2회를 넘기면 3번째부터는 제안이
    #   아니라 강제 종료(SESSION_END_EARLY)로 전환해야 한다.
    suggest_pause_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .where(ChatMessage.role == "model")
        .where(ChatMessage.probe_type_used == "SUGGEST_PAUSE")
    )
    suggest_pause_count = len(list(suggest_pause_result.scalars().all()))

    # 8-a4. CONFIRM 턴 수 (DIAGNOSIS_CONFIRM 으로 저장된 model 메시지 수)
    confirm_msg_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .where(ChatMessage.role == "model")
        .where(ChatMessage.instruction_used == "DIAGNOSIS_CONFIRM")
    )
    confirm_turn_count = len(list(confirm_msg_result.scalars().all()))

    # 8-b. 라포 턴 수 (chapter=NULL 인 user 메시지 — 라포 완료 후 소급 변경된 것들)
    rapport_turn_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .where(ChatMessage.role == "user")
        .where(ChatMessage.chapter == None)  # noqa: E711
    )
    rapport_messages = rapport_turn_result.scalars().all()
    rapport_turn_count = len(rapport_messages)

    # 8-c. 이 챕터의 실제 BEI AI 메시지 수 (CHAPTER_OPENING 발화 판별용).
    # 진단 전 단계(INTRO/CONFIRM/ALIGN/INTRO)는 제외 — 아직 BEI 시작 전이므로.
    # ⚠️ DIAGNOSIS_CONFIRM 은 START_CHAPTER 마커 때문에 chapter 로 태깅되므로
    #    반드시 제외해야 CHAPTER_OPENING(첫 BEI 템플릿)이 정상 발화함.
    chapter_msg_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .where(ChatMessage.chapter == chapter)
        .where(ChatMessage.role == "model")
        .where(ChatMessage.instruction_used.not_in([
            "COMPETENCY_INTRO",
            "COMPETENCY_ALIGN",
            "DIAGNOSIS_CONFIRM",
            "DIAGNOSIS_INTRO",
            # 종결+전환 경계 메시지가 다음 챕터로 태깅되므로 제외해야
            # 새 챕터의 CHAPTER_OPENING(첫 BEI)이 정상 발화함.
            "CHAPTER_READY_TO_END",
            # '계속' 확정 브릿지도 다음 챕터로 태깅됨 → 첫 BEI 판별에서 제외.
            "CHAPTER_CONTINUE_CONFIRMED",
        ]))
    )
    chapter_message_count = len(list(chapter_msg_result.scalars().all()))

    # 8-d. 역량 합의 마커
    competency_intro_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .where(ChatMessage.chapter == chapter)
        .where(ChatMessage.role == "model")
        .where(ChatMessage.instruction_used == "COMPETENCY_INTRO")
    )
    competency_intro_done = competency_intro_result.scalars().first() is not None

    competency_align_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .where(ChatMessage.chapter == chapter)
        .where(ChatMessage.role == "model")
        .where(ChatMessage.instruction_used == "COMPETENCY_ALIGN")
    )
    competency_aligned = competency_align_result.scalars().first() is not None

    # 8-e. 첫 세부 역량 이름 (CHAPTER_OPENING 가이드용) + 역량 framework
    from diag_project.data.competencies import COMPETENCY_FRAMEWORK
    chapter_competency = COMPETENCY_FRAMEWORK.get(chapter, {})
    indicators = chapter_competency.get("indicators", {})
    first_subcompetency_name = ""
    if indicators:
        first_key = next(iter(indicators))
        first_subcompetency_name = indicators[first_key].get("name", "")

    # 8-e2. 하위역량 탐색 상태 추적 (동적 태깅 — LLM 추론/환각 방지)
    #   각 사건의 mapped_subcompetency(실제 스토리 기반 태깅)를 모아 탐색
    #   세트 구성. 질문 순서가 아니라 '실제 답변 내용'으로 체크리스트 관리.
    all_subcompetencies = [
        v.get("name", "") for v in indicators.values() if v.get("name")
    ]
    _explored_set = set()
    for _e in events:
        _matched = _match_subcompetency(
            getattr(_e, "mapped_subcompetency", None), all_subcompetencies
        )
        if _matched:
            _explored_set.add(_matched)
    explored_subcompetencies = [
        n for n in all_subcompetencies if n in _explored_set
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
    # 아직 타겟팅되지 않은(asked=False) 하위역량 — 순회 대상 큐
    unexplored_subcompetencies = [
        n for n in all_subcompetencies if n not in asked_in_chapter
    ]

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
        "events_with_star_70": sum(
            1 for e in events if e.star_coverage >= 0.7
        ),
        "current_event_id": str(active_event.id) if active_event else None,
        "current_event_star_coverage": coverage,
        "current_event_probe_count": (
            active_event.probe_count if active_event else 0
        ),
        "has_contrary_probe": has_contrary,
        "contrary_retry_count": 0,  # TODO: Phase 3-A 후속에서 정밀 추적
        # 회피 + 남탓/비아냥/도발을 합산 — Fail-Fast(비생산 응답 3회) 근거.
        # (단순 회피어만 세면 공격형의 남탓·비아냥이 안 잡혀 손절이 안 됨)
        "avoidance_count_in_chapter": sum(
            1 for m in user_messages if is_unproductive_response(m.content)
        ),
        "last_avoidance_type": None,
        "avoidance_retry_count": 0,
        "existing_events": existing_for_check,
        "all_collected_events": all_collected_events,  # Global Memory
        "cross_chapter_signals": None,  # 자기관리 챕터에서 별도 채움 (Step 5+)
        "last_user_response": last_response,
        "response_length": len(last_response) if last_response else 0,
        "contains_avoidance_keywords": contains_avoidance,
        "duplicate_suspected": False,  # Step 5의 duplicate_detector 통합 후 채움
        "rapport_complete": rapport_complete,
        "intro_done": intro_done,
        "chapter_started": chapter_started,
        "confirm_turn_count": confirm_turn_count,
        "rapport_turn_count": rapport_turn_count,
        "chapter_message_count": chapter_message_count,
        "competency_intro_done": competency_intro_done,
        "competency_aligned": competency_aligned,
        "awaiting_continue_decision": awaiting_continue_decision,
        "suggest_pause_count": suggest_pause_count,
        "session_deflection_count": session_deflection_count,
        "session_already_warned": session_already_warned,
        "name_extraction_failed": name_extraction_failed,
        "name_reconfirm_asked": name_reconfirm_asked,
        "no_yield_ultimatum_given": no_yield_ultimatum_given,
        "first_subcompetency_name": first_subcompetency_name,
        "all_subcompetencies": all_subcompetencies,
        "explored_subcompetencies": explored_subcompetencies,
        "unexplored_subcompetencies": unexplored_subcompetencies,
        "asked_in_chapter": asked_in_chapter,  # T2: 실시간 탐색(넓이) 지표
        "user_name": user_name,
        "chapter_framework": chapter_framework_state,
    }

    # 9-d. 시간 정보 (라포 단계 LLM 자연스러운 응답 위해)
    from diag_project.services.time_greeting import get_time_greeting
    time_info = get_time_greeting()
    state["current_hour_text"] = time_info["hour_text"]
    state["current_time_tone"] = time_info["tone"]
    state["current_ampm_phrase"] = time_info["ampm_phrase"]

    # 9-e. 라포 카테고리 강제 결정 (가이드 약속이 아닌 시스템 명령)
    state["forced_rapport_category"] = _force_rapport_category(rapport_turn_count)

    # 9-f. 무한 루프 방지 안전장치 (라포 3턴 이상 + 동의 신호 → [READY_FOR_INTRO] 강제)
    force_ready_for_intro = False
    last_rapport_response = rapport_messages[-1].content if rapport_messages else None
    if rapport_turn_count >= 3 and is_user_consent(last_rapport_response):
        force_ready_for_intro = True
    state["force_ready_for_intro"] = force_ready_for_intro

    # 9-g. 무수확 강제 전환 플래그 (READY_TO_END 가이드가 문구를 바꾸도록):
    #   강한 STAR 가 0인 채로 종료가 결정되는 두 경로 모두에서 True:
    #     ① 최후통첩까지 했는데도 무수확(기존 NO_YIELD 경로)
    #     ② 회피/남탓/비아냥 3회 반복으로 Fail-Fast 강제 전환(4-a)
    #   → 챕터 종료 멘트를 '강점 요약' 대신 '유의미한 진단 불가 → 전환'으로.
    _avoid_ct = state.get("avoidance_count_in_chapter", 0)
    state["no_yield_forced"] = (
        state["events_with_star_70"] == 0
        and (
            (chapter_message_count >= NO_YIELD_TURNS and no_yield_ultimatum_given)
            or (_avoid_ct >= 3 and chapter_message_count >= 3)
        )
    )

    # 10. instruction 결정
    state["instruction_for_this_turn"] = decide_instruction(state)

    return state
