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


# 19가지 instruction 타입
InstructionType = Literal[
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


def decide_instruction(state: dict) -> InstructionType:
    """현재 상태 기반으로 LLM 에게 줄 instruction 결정.

    우선순위 순서로 체크. 위에서부터 매칭되면 즉시 반환.
    """
    # 0-3. 4단계 온보딩 (라포 → 인트로 → 확인 → 챕터)
    rapport_complete = state.get("rapport_complete", False)
    intro_done = state.get("intro_done", False)
    chapter_started = state.get("chapter_started", False)
    turn_count_total = state.get("turn_count", 0) + state.get("rapport_turn_count", 0)
    ONBOARDING_MAX_TURNS = 8

    # Stage 1: 라포 (rapport_complete 신호 없음, 또는 최소 턴 미달)
    rapport_turn_count = state.get("rapport_turn_count", 0)
    RAPPORT_MIN_TURNS = 2  # 최소 2턴 (사용자 답변 짧아도 보장)
    if not rapport_complete and turn_count_total <= 6:
        return "RAPPORT_BUILDING"
    if rapport_complete and rapport_turn_count < RAPPORT_MIN_TURNS:
        return "RAPPORT_BUILDING"

    # Stage 2: 진단 인트로 (라포 끝, 인트로 미완)
    if rapport_complete and not intro_done:
        return "DIAGNOSIS_INTRO"

    # Stage 3: 시작 확인 (인트로 완료, 챕터 미시작)
    if intro_done and not chapter_started:
        return "DIAGNOSIS_CONFIRM"

    # Stage 4: 챕터 진입 (역량 정의 합의 → 첫 BEI)
    if chapter_started or turn_count_total > ONBOARDING_MAX_TURNS:
        competency_intro_done = state.get("competency_intro_done", False)
        competency_aligned = state.get("competency_aligned", False)
        chapter_msg_count = state.get("chapter_message_count", 0)

        # 4-1: 역량 정의 소개 (LLM 이 리더의 역량 정의 묻기)
        if not competency_intro_done:
            return "COMPETENCY_INTRO"

        # 4-2: 역량 합의 (시스템이 프레임워크 정의 + 세부 역량 제시)
        if not competency_aligned:
            return "COMPETENCY_ALIGN"

        # 4-3: 챕터 오프닝 (첫 BEI 질문)
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
        .where(ChatMessage.role == "model")
        .where(ChatMessage.probe_type_used == "START_CHAPTER")
    )
    chapter_started = chapter_started_result.scalars().first() is not None

    # 8-b. 라포 턴 수 (chapter=NULL 인 user 메시지 — 라포 완료 후 소급 변경된 것들)
    rapport_turn_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .where(ChatMessage.role == "user")
        .where(ChatMessage.chapter == None)  # noqa: E711
    )
    rapport_turn_count = len(rapport_turn_result.scalars().all())

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

    # 8-e. 첫 세부 역량 이름 (CHAPTER_OPENING 가이드용)
    from diag_project.data.competencies import COMPETENCY_FRAMEWORK
    chapter_competency = COMPETENCY_FRAMEWORK.get(chapter, {})
    indicators = chapter_competency.get("indicators", {})
    first_subcompetency_name = ""
    if indicators:
        first_key = next(iter(indicators))
        first_subcompetency_name = indicators[first_key].get("name", "")

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
        "rapport_turn_count": rapport_turn_count,
        "chapter_message_count": chapter_message_count,
        "competency_intro_done": competency_intro_done,
        "competency_aligned": competency_aligned,
        "first_subcompetency_name": first_subcompetency_name,
    }

    # 9-d. 시간 정보 (라포 단계 LLM 자연스러운 응답 위해)
    from diag_project.services.time_greeting import get_time_greeting
    time_info = get_time_greeting()
    state["current_hour_text"] = time_info["hour_text"]
    state["current_time_tone"] = time_info["tone"]
    state["current_ampm_phrase"] = time_info["ampm_phrase"]

    # 10. instruction 결정
    state["instruction_for_this_turn"] = decide_instruction(state)

    return state
