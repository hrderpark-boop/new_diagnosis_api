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
    detect_pause_request,
    detect_meta_question,
    is_invalid_input,
)


def _extract_user_name(text: str) -> str:
    """첫 user 메시지에서 이름 추출.

    예시:
    - "안녕하세요 박기진입니다" → "박기진"
    - "박기진이라고 합니다"     → "박기진"
    - "박기진이에요"            → "박기진"
    - "안녕하세요"              → "리더"
    - ""                       → "리더"
    """
    import re

    # 패턴 1: "[이름]입니다" / "[이름]이라고" / "[이름]이에요" / "[이름]예요"
    match = re.search(
        r'([가-힣]{2,4})(?:입니다|이라고|이에요|예요|이라|라고)',
        text,
    )
    if match:
        return match.group(1)

    # 패턴 2: 한글 2-4자 중 인사말 제외
    excluded = {"안녕", "반갑", "감사", "고맙"}
    for m in re.findall(r'[가-힣]{2,4}', text):
        if not any(exc in m for exc in excluded):
            return m

    return "리더"


# 19가지 instruction 타입
InstructionType = Literal[
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
    "DUPLICATE_SUSPECTED",
    "CROSS_CHAPTER_OPPORTUNITY",
    "CHAPTER_READY_TO_END",
    "MAX_TURNS_REACHED",
    "USER_REQUESTS_PAUSE",
    "META_QUESTION_FROM_USER",
    "FIRST_TURN_AVOIDANCE",
    "INVALID_INPUT",
]


# 챕터별 최소 사건 수
MIN_EVENTS: dict[str, int] = {
    "organization_management": 2,
    "performance_management": 2,
    "people_management": 3,
    "work_management": 2,
    "self_management": 2,
}

# 챕터별 최대 턴 수 (user 메시지 기준)
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

    # 5. 첫 턴 회피 (라포 회복)
    if state["turn_count"] <= 2 and state["contains_avoidance_keywords"]:
        return "FIRST_TURN_AVOIDANCE"

    # 6. 일반 회피
    if state["contains_avoidance_keywords"]:
        return "AVOIDANCE_DETECTED"

    # 7. 중복 의심
    if state.get("duplicate_suspected"):
        return "DUPLICATE_SUSPECTED"

    # 8. 최대 턴 초과
    chapter_max = MAX_TURNS.get(state["chapter"], 40)
    if state["turn_count"] >= chapter_max:
        return "MAX_TURNS_REACHED"

    # 9. 종료 가능 체크 (반례 있고, 사건 충분)
    min_events = MIN_EVENTS.get(state["chapter"], 2)
    if (state["events_with_star_70"] >= min_events
            and state["has_contrary_probe"]):
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
    if state.get("current_event_id"):
        coverage = state.get("current_event_star_coverage") or {}
        if coverage and all(coverage.values()):
            return "STAR_COMPLETE_NEW_EVENT"
        else:
            return "STAR_INCOMPLETE"

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

    # 8-c. 이 챕터의 AI 메시지 수 (CHAPTER_OPENING vs 첫 턴 판별용)
    # COMPETENCY_INTRO / COMPETENCY_ALIGN 은 제외 — 아직 BEI 시작 전이므로
    chapter_msg_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .where(ChatMessage.chapter == chapter)
        .where(ChatMessage.role == "model")
        .where(ChatMessage.instruction_used.not_in(["COMPETENCY_INTRO", "COMPETENCY_ALIGN"]))
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

    # 8-f. user_name 추출 (세션 첫 user 메시지에서 이름 파싱)
    first_user_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .where(ChatMessage.role == "user")
        .order_by(ChatMessage.created_at.asc())
        .limit(1)
    )
    first_user_msg = first_user_result.scalars().first()
    user_name = "리더"
    if first_user_msg and first_user_msg.content:
        user_name = _extract_user_name(first_user_msg.content)

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
        "avoidance_count_in_chapter": sum(
            1 for m in user_messages if check_avoidance(m.content)
        ),
        "last_avoidance_type": None,
        "avoidance_retry_count": 0,
        "existing_events": existing_for_check,
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
        "first_subcompetency_name": first_subcompetency_name,
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

    # 10. instruction 결정
    state["instruction_for_this_turn"] = decide_instruction(state)

    return state
