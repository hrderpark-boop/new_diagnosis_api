import logging
import os
import uuid
from uuid import UUID
import re
import json
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func, delete, desc
from pydantic import BaseModel

from diag_project.database import get_db
from diag_project.models.diagnosis_session import DiagnosisSession, ChatMessage
from diag_project.models.coach_persona import CoachPersona
from diag_project.models.participant import Participant
from diag_project.llm_service import GeminiService
from diag_project.data.coaches_persona import COACHES_PERSONA
from diag_project.services.chapter_translator import topic_to_chapter, chapter_to_topic
from diag_project.services.instruction_decider import build_turn_state
from diag_project.services.conversation_compressor import compress_conversation_history
from diag_project.services.event_service import (
    create_event, update_event_star, complete_event,
    increment_probe_count, get_active_event, get_chapter_events,
)
from diag_project.prompts.phase3a.layer1_system import (
    LAYER1_SYSTEM_PROMPT,
    build_layer1_with_persona,
)
from diag_project.services.time_greeting import build_rapport_greeting
from diag_project.services.intro_messages import (
    build_intro_anchor_section,
    build_align_framework_section,
)
from diag_project.prompts.phase3a.layer2_chapters import CHAPTER_CONTEXTS
from diag_project.prompts.phase3a.layer3_state import format_turn_state_for_llm

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["Diagnosis Flow"],
)

# ------------------------------------------------------------------
# Pydantic Models
# ------------------------------------------------------------------
class DiagnosisStartRequest(BaseModel):
    coach_id: uuid.UUID
    participant_id: uuid.UUID
    template_id: uuid.UUID
    coach_persona_id: Optional[uuid.UUID] = None

class ChatMessageRequest(BaseModel):
    session_id: uuid.UUID
    diagnosis_id: Optional[uuid.UUID] = None 
    content: str

class ResetRequest(BaseModel):
    participant_id: Optional[uuid.UUID] = None 

# ------------------------------------------------------------------
# Constants & Data
# ------------------------------------------------------------------
_topic_order_cache = None


def _get_topic_order() -> list:
    global _topic_order_cache
    if _topic_order_cache is None:
        from diag_project.services.framework_service import get_topics
        _topic_order_cache = [t.name for t in get_topics().topics]
    return _topic_order_cache


# coaches.py가 반환하는 UUID와 COACHES_PERSONA 딕셔너리 키("1"~"6")를 연결.
# coaches.py UUID 규칙: 끝 두 자리 = int(key) + 10
COACH_UUID_TO_KEY = {
    f"10000000-0000-0000-0000-0000000000{int(k) + 10:02d}": k
    for k in COACHES_PERSONA
}


def _resolve_persona(coach_id: uuid.UUID, user_name: str, visit_count: int):
    """
    coach_id UUID → (CoachPersona DTO, opening 문자열) 반환.
    알 수 없는 coach_id면 HTTPException 400을 발생시킨다.
    """
    key = COACH_UUID_TO_KEY.get(str(coach_id))
    if not key:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown coach_id: {coach_id}. Valid IDs end with 11~16."
        )
    data = COACHES_PERSONA[key]
    formatted_prompt = data["system_prompt"].format(
        user_name=user_name, visit_count=visit_count
    )
    opening_template = data["opening_returning"] if visit_count > 1 else data["opening_new"]
    opening = opening_template.format(user_name=user_name)
    persona = CoachPersona(
        name=data["name"],
        system_prompt=formatted_prompt,
        coach_id=coach_id,
    )
    return persona, opening

# ------------------------------------------------------------------
# [1] 진단 세션 시작 (POST /start) - ✅ 이어하기 기능 부활!
# ------------------------------------------------------------------
@router.post("/start", status_code=status.HTTP_201_CREATED)
async def start_diagnosis(
    request: DiagnosisStartRequest, 
    db: AsyncSession = Depends(get_db),
    llm: GeminiService = Depends(GeminiService) 
):
    user = await db.get(Participant, request.participant_id)
    user_name = user.name if user else "리더"

    # 1. 가장 최근의 '진행 중'인 세션 찾기 (이어하기)
    # created_at 내림차순(desc)으로 정렬하여 가장 마지막 세션을 가져옵니다.
    existing_query = select(DiagnosisSession).where(
        DiagnosisSession.user_id == request.participant_id,
        DiagnosisSession.status == "in_progress"
    ).order_by(desc(DiagnosisSession.created_at))
    
    result = await db.execute(existing_query)
    existing_session = result.scalars().first()

    # [Case A] 진행 중인 세션이 있다! -> 이어하기(Resume)
    if existing_session:
        logger.info(f"🔄 Resuming existing session: {existing_session.id}")
        
        # 마지막 AI 메시지 가져오기 (문맥 유지용)
        last_msg_query = select(ChatMessage).where(
            ChatMessage.session_id == existing_session.id,
            ChatMessage.role == "model"
        ).order_by(desc(ChatMessage.created_at))
        last_msg_res = await db.execute(last_msg_query)
        last_message = last_msg_res.scalars().first()
        
        # 메시지가 없으면 기본 멘트
        response_msg = last_message.content if last_message else "리더님, 다시 만나서 반가워요. 이어서 진행해볼까요?"

        return {
            "diagnosis_id": existing_session.id,
            "session_id": existing_session.id,
            "coach_response_message": response_msg,
            "next_action": "resume" # 프론트엔드에 '이어하기'임을 알림
        }

    # [Case B] 진행 중인 게 없다 -> 새 세션 생성 (New Game)
    logger.info(f"🆕 Creating NEW session for user: {request.participant_id}")
    
    # 방문 횟수 계산
    count_query = select(func.count(DiagnosisSession.id)).where(DiagnosisSession.user_id == request.participant_id)
    result = await db.execute(count_query)
    past_session_count = result.scalar() or 0
    visit_count = past_session_count + 1 

    # 코치 페르소나 조회 (알 수 없는 coach_id면 400 반환)
    persona, opening = _resolve_persona(request.coach_id, user_name, visit_count)

    # DB 저장
    new_session = DiagnosisSession(
        id=uuid.uuid4(),
        user_id=request.participant_id,
        coach_id=request.coach_id,
        diagnosis_template_id=request.template_id,
        status="in_progress",
        current_topic="General",
        created_at=datetime.now(),
        updated_at=datetime.now()
    )
    db.add(new_session)
    await db.commit()
    await db.refresh(new_session)

    use_phase3a = os.getenv("USE_PHASE3A", "false").lower() == "true"

    if use_phase3a:
        # Phase 3-A: 라포 단계로 시작 (챕터 스크립트는 라포 완료 후)
        first_msg_content = build_rapport_greeting(persona.name)
        first_message = ChatMessage(
            session_id=new_session.id,
            role="model",
            content=first_msg_content,
            chapter=None,
            instruction_used="RAPPORT_BUILDING",
        )
        db.add(first_message)
        await db.commit()
        return {
            "diagnosis_id": new_session.id,
            "session_id": new_session.id,
            "coach_response_message": first_msg_content,
            "next_action": None,
        }
    else:
        # Legacy: LLM 으로 첫 인사 생성 (기존 그대로)
        ai_response = await llm.generate_initial_response(
            persona,
            user_name,
            specific_opening=opening,
        )
        first_message = ChatMessage(
            session_id=new_session.id,
            role="model",
            content=ai_response["coach_response_message"],
        )
        db.add(first_message)
        await db.commit()
        return {
            "diagnosis_id": new_session.id,
            "session_id": new_session.id,
            "coach_response_message": ai_response["coach_response_message"],
            "next_action": ai_response.get("next_action"),
        }

# ------------------------------------------------------------------
# [2] 메시지 전송 및 응답 (POST /submit_message)
# ------------------------------------------------------------------
@router.post("/submit_message", status_code=status.HTTP_201_CREATED)
async def submit_message(
    request: ChatMessageRequest,
    db: AsyncSession = Depends(get_db),
    llm: GeminiService = Depends(GeminiService),
):
    use_phase3a = os.getenv("USE_PHASE3A", "false").lower() == "true"
    if use_phase3a:
        return await _submit_message_phase3a(request, db, llm)
    return await _submit_message_legacy(request, db, llm)


async def _submit_message_legacy(
    request: ChatMessageRequest,
    db: AsyncSession,
    llm: GeminiService,
):
    """기존 흐름. USE_PHASE3A=false 시 사용. 본문 변경 금지."""
    session = await db.get(DiagnosisSession, request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    user = await db.get(Participant, session.user_id)
    user_name = user.name if user else "리더"

    count_query = select(func.count(DiagnosisSession.id)).where(DiagnosisSession.user_id == session.user_id)
    result = await db.execute(count_query)
    visit_count = result.scalar() or 1

    current_topic = session.current_topic if session.current_topic else "General"

    # 코치 페르소나 조회 (opening은 초기 인사용이므로 대화 중엔 불필요)
    persona, _ = _resolve_persona(session.coach_id, user_name, visit_count)

    # 유저 메시지 저장
    user_msg = ChatMessage(session_id=session.id, role="user", content=request.content)
    db.add(user_msg)
    await db.commit()

    # 대화 히스토리 로드
    history_query = select(ChatMessage).where(ChatMessage.session_id == session.id).order_by(ChatMessage.created_at.asc())
    history_result = await db.execute(history_query)
    history_messages = history_result.scalars().all()
    formatted_history = [{"role": msg.role, "parts": msg.content} for msg in history_messages]

    # 완료된 토픽 계산
    topic_order = _get_topic_order()
    completed_competencies_list = []
    if current_topic in topic_order:
        curr_idx = topic_order.index(current_topic)
        completed_competencies_list = topic_order[:curr_idx]
    elif current_topic == "Completed":
        completed_competencies_list = topic_order[:]

    # LLM 호출
    ai_response_json = await llm.generate_next_interaction(
        persona=persona,
        history=formatted_history,
        user_answer=request.content,
        user_name=user_name,
        visit_count=visit_count,
        current_topic=current_topic,
        completed_competencies=completed_competencies_list,
        unfinished_topic=None,
        last_session_summary=""
    )

    ai_content = ai_response_json.get("coach_response_message", "오류가 발생했습니다.")

    # 리워드 데이터 추출
    reward_data = None
    reward_match = re.search(r'\[REWARD_JSON:(.*?)\]', ai_content)

    if reward_match:
        try:
            json_str = reward_match.group(1)
            reward_data = json.loads(json_str)
            ai_content = ai_content.replace(reward_match.group(0), "").strip()
        except Exception as e:
            logger.error(f"Reward JSON parsing failed: {e}")

    # 상태 업데이트
    is_session_starting = ai_response_json.get("is_session_starting", False)
    is_topic_completed = ai_response_json.get("is_topic_completed", False)

    if is_session_starting and current_topic == "General":
        first_topic = topic_order[0]
        session.current_topic = first_topic
        db.add(session)
        await db.commit()

    if is_topic_completed:
        try:
            current_idx = topic_order.index(current_topic)
            if current_idx + 1 >= len(topic_order):
                next_topic = "Completed"
            else:
                next_topic = topic_order[current_idx + 1]
        except ValueError:
            logger.warning(
                f"Unknown current_topic={current_topic!r}, "
                f"expected one of {topic_order}. Resetting to first topic."
            )
            next_topic = topic_order[0]

        session.current_topic = next_topic
        db.add(session)
        await db.commit()

    if "진단 종료" in request.content:
        ai_response_json["is_session_completed"] = True
        ai_content = "네, 알겠습니다. 분석 리포트를 생성해 드리겠습니다."
        session.status = "completed"
        db.add(session)
        await db.commit()

    # UI용 완료 목록 재계산
    completed_topics_for_frontend = []
    updated_topic = session.current_topic

    if session.status == "completed" or updated_topic == "Completed":
        completed_topics_for_frontend = topic_order[:]
    elif updated_topic in topic_order:
        curr_idx = topic_order.index(updated_topic)
        completed_topics_for_frontend = topic_order[:curr_idx]

    # AI 응답 저장
    ai_msg = ChatMessage(session_id=session.id, role="model", content=ai_content)
    db.add(ai_msg)
    await db.commit()

    return {
        "coach_response_message": ai_content,
        "is_topic_completed": is_topic_completed,
        "is_session_starting": is_session_starting,
        "is_session_completed": ai_response_json.get("is_session_completed", False),
        "reward": reward_data,
        "completed_topics": completed_topics_for_frontend,
    }


async def _submit_message_phase3a(
    request: ChatMessageRequest,
    db: AsyncSession,
    llm: GeminiService,
):
    """Phase 3-A 흐름. USE_PHASE3A=true 시 활성."""
    # 1. 세션 조회
    session = await db.get(DiagnosisSession, request.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # 2. 현재 챕터 결정 (current_topic 한국어 → 영문 key)
    chapter = topic_to_chapter(session.current_topic)

    # 3. 사용자 메시지 저장 (chapter 임시 채움 — 라포 여부 확인 후 소급 수정)
    user_msg = ChatMessage(
        session_id=session.id,
        role="user",
        content=request.content,
        chapter=chapter,
    )
    db.add(user_msg)
    await db.commit()

    # 4. Turn State 빌드
    state = await build_turn_state(db, session.id, chapter)

    # 4-a. 진단 전 단계면 user_msg.chapter 를 NULL 로 소급 변경
    instruction_used = state.get("instruction_for_this_turn")
    PRE_DIAGNOSIS_INSTRUCTIONS = {"RAPPORT_BUILDING", "DIAGNOSIS_INTRO", "DIAGNOSIS_CONFIRM"}
    if instruction_used in PRE_DIAGNOSIS_INSTRUCTIONS:
        user_msg.chapter = None
        db.add(user_msg)
        await db.commit()

    # 5. 대화 이력 압축
    compressed_history = await compress_conversation_history(db, session.id, chapter)

    # 6. 3-Layer 프롬프트 조립
    # Layer 2: COMPETENCY_INTRO/ALIGN 단계에선 챕터 시작 스크립트가
    # LLM 응답에 섞이는 문제 방지를 위해 빈 값 전달.
    # 두 instruction 은 state.chapter_framework 로 필요 정보 받음.
    _LAYER2_EXCLUDED = {"COMPETENCY_INTRO", "COMPETENCY_ALIGN", "DIAGNOSIS_INTRO"}
    if instruction_used in _LAYER2_EXCLUDED:
        chapter_context = ""
    else:
        chapter_context = CHAPTER_CONTEXTS.get(
            chapter, CHAPTER_CONTEXTS["organization_management"]
        )
    turn_state_text = format_turn_state_for_llm(state)

    # 페르소나 통합 system prompt (코치별 톤 반영)
    coach_key = COACH_UUID_TO_KEY.get(str(session.coach_id), "1")
    user_name = state.get("user_name", "리더")
    system_prompt = build_layer1_with_persona(
        coach_id=coach_key,
        user_name=user_name,
        visit_count=1,
    )

    # 7. LLM 호출
    llm_output = await llm.generate_phase3a_interaction(
        system_prompt=system_prompt,
        chapter_context=chapter_context,
        turn_state_text=turn_state_text,
        compressed_history=compressed_history,
        user_message=request.content,
    )

    reply = llm_output["reply"]
    llm_state = llm_output.get("state") or {}
    event_metadata = llm_output.get("event_metadata")

    # 8. 제어 태그 처리 (감사 위험 #4 해결)
    is_chapter_completed = "[CHAPTER_COMPLETE]" in reply
    is_session_paused = "[SESSION_PAUSE]" in reply
    is_ready_for_intro = "[READY_FOR_INTRO]" in reply
    is_chapter_starting = "[START_CHAPTER]" in reply
    clean_reply = (
        reply
        .replace("[CHAPTER_COMPLETE]", "")
        .replace("[SESSION_PAUSE]", "")
        .replace("[READY_FOR_INTRO]", "")
        .replace("[START_CHAPTER]", "")
        .strip()
    )

    # 8-a. DIAGNOSIS_INTRO 하이브리드: LLM 호응 + 시스템 진단 안내 본문 합치기
    if instruction_used == "DIAGNOSIS_INTRO":
        llm_acknowledgment = clean_reply
        if not llm_acknowledgment or "죄송합니다" in llm_acknowledgment:
            llm_acknowledgment = "말씀 감사합니다."
        anchor_section = build_intro_anchor_section()
        clean_reply = f"{llm_acknowledgment}\n\n{anchor_section}"

    # 8-b. COMPETENCY_ALIGN 하이브리드: LLM 호응 + 시스템 framework 합치기
    if instruction_used == "COMPETENCY_ALIGN":
        llm_acknowledgment = clean_reply
        if not llm_acknowledgment or "죄송합니다" in llm_acknowledgment:
            llm_acknowledgment = "네, 리더님 말씀 잘 들었습니다."
        framework_section = build_align_framework_section(chapter)
        clean_reply = f"{llm_acknowledgment}\n\n{framework_section}"

    # 9. 사건 생명주기 처리 + AI 메시지 저장
    probe_type_used = llm_state.get("probe_type_used")

    # 마커 → probe_type_used 에 저장 (우선순위: READY_FOR_INTRO > START_CHAPTER)
    if instruction_used == "RAPPORT_BUILDING" and is_ready_for_intro:
        probe_type_used = "READY_FOR_INTRO"
    elif instruction_used == "DIAGNOSIS_CONFIRM" and is_chapter_starting:
        probe_type_used = "START_CHAPTER"

    # 진단 전 단계는 사건 생명주기 스킵
    is_pre_diagnosis = (instruction_used in PRE_DIAGNOSIS_INSTRUCTIONS)
    if is_pre_diagnosis:
        real_event_id = None
    else:
        real_event_id = await _handle_event_lifecycle(
            db=db,
            session_id=session.id,
            chapter=chapter,
            llm_state=llm_state,
            event_metadata=event_metadata,
            user_message_text=request.content,
        )

    ai_msg = ChatMessage(
        session_id=session.id,
        role="model",
        content=clean_reply,
        chapter=None if is_pre_diagnosis else chapter,
        event_id=None if is_pre_diagnosis else real_event_id,
        probe_type_used=probe_type_used,
        instruction_used=instruction_used,
    )
    db.add(ai_msg)
    await db.commit()

    # 11. 챕터 전진 처리
    is_session_completed = False
    if is_chapter_completed:
        next_chapter = _get_next_chapter(chapter)
        if next_chapter:
            session.current_topic = chapter_to_topic(next_chapter)
        else:
            session.current_topic = "Completed"
            session.status = "completed"
            is_session_completed = True
        db.add(session)
        await db.commit()

    # 12. 응답 (감사 위험 #3 해결: reply → coach_response_message 매핑)
    return {
        "coach_response_message": clean_reply,
        "is_topic_completed": is_chapter_completed,
        "is_session_starting": False,
        "is_session_completed": is_session_completed,
        "is_session_paused": is_session_paused,
        "reward": None,
        "completed_topics": [],
        "_phase3a_metadata": {
            "chapter": chapter,
            "instruction_used": instruction_used,
            "probe_type_used": probe_type_used,
            "turn_count": state.get("turn_count"),
            "events_collected": state.get("events_collected"),
        },
    }


def _get_next_chapter(current_chapter: str) -> str | None:
    """다음 챕터 결정. 마지막 챕터면 None 반환."""
    chapter_order = [
        "organization_management",
        "performance_management",
        "people_management",
        "work_management",
        "self_management",
    ]
    try:
        idx = chapter_order.index(current_chapter)
        return chapter_order[idx + 1] if idx + 1 < len(chapter_order) else None
    except ValueError:
        return None


async def _handle_event_lifecycle(
    db: AsyncSession,
    session_id: UUID,
    chapter: str,
    llm_state: dict,
    event_metadata: dict | None,
    user_message_text: str,
) -> UUID | None:
    """LLM 신호를 기반으로 사건 생명주기 관리.

    LLM 의 임시 ID ("evt_1") 는 신호로만 사용.
    실제 DB UUID 는 이 함수가 생성/조회해서 반환.

    Returns:
        진짜 event UUID (있으면) 또는 None
    """
    llm_signals_active_event = bool(llm_state.get("current_event_id"))
    turn_intent = llm_state.get("turn_intent", "")
    star_coverage = llm_state.get("star_coverage") or {}

    active_event = await get_active_event(db, session_id, chapter)

    # 케이스 1: LLM 이 사건 신호 없음 → 추적 안 함
    if not llm_signals_active_event:
        return None

    # 케이스 2: LLM 이 사건 신호 있음, DB 에 활성 사건 없음 → 새 사건 생성
    if not active_event:
        existing = await get_chapter_events(db, session_id, chapter)
        sequence_num = len(existing) + 1
        new_event = await create_event(
            db=db,
            session_id=session_id,
            chapter=chapter,
            sequence_num=sequence_num,
        )
        if user_message_text:
            await update_event_star(
                db=db,
                event_id=new_event.id,
                situation=user_message_text[:500],
            )
        await increment_probe_count(db, new_event.id)
        return new_event.id

    # 케이스 3: LLM 이 사건 신호 있음, DB 에 활성 사건 있음 → STAR 갱신 + 탐침 카운트
    update_kwargs: dict = {}
    if user_message_text:
        if not active_event.action and star_coverage.get("A"):
            update_kwargs["action"] = user_message_text[:500]
        elif not active_event.result and star_coverage.get("R"):
            update_kwargs["result"] = user_message_text[:500]
        elif not active_event.task and star_coverage.get("T"):
            update_kwargs["task"] = user_message_text[:500]

    if update_kwargs:
        await update_event_star(db=db, event_id=active_event.id, **update_kwargs)

    await increment_probe_count(db, active_event.id)

    if turn_intent == "EVENT_COMPLETE" and event_metadata:
        await complete_event(db=db, event_id=active_event.id, metadata=event_metadata)

    return active_event.id


# ------------------------------------------------------------------
# [3] 데이터 초기화 (Reset)
# ------------------------------------------------------------------
@router.post("/reset", status_code=status.HTTP_200_OK)
async def reset_diagnosis_data(
    request: ResetRequest,
    db: AsyncSession = Depends(get_db)
):
    if not request.participant_id:
        raise HTTPException(status_code=400, detail="participant_id is required for safety.")

    sessions_query = select(DiagnosisSession.id).where(DiagnosisSession.user_id == request.participant_id)
    result = await db.execute(sessions_query)
    session_ids = result.scalars().all()

    if not session_ids:
        return {"message": "No data found for this user."}

    delete_msgs = delete(ChatMessage).where(ChatMessage.session_id.in_(session_ids))
    await db.execute(delete_msgs)

    delete_sessions = delete(DiagnosisSession).where(DiagnosisSession.user_id == request.participant_id)
    await db.execute(delete_sessions)
    
    await db.commit()
    return {"message": "Reset complete."}

# ------------------------------------------------------------------
# [4] 세션 상태 조회 (GET /state)
# ------------------------------------------------------------------
@router.get("/{session_id}/state")
async def get_session_state(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db)
):
    session = await db.get(DiagnosisSession, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    history_query = select(ChatMessage).where(ChatMessage.session_id == session_id).order_by(ChatMessage.created_at.asc())
    history_result = await db.execute(history_query)
    messages = history_result.scalars().all()
    formatted_messages = [{"role": msg.role, "content": msg.content} for msg in messages]

    topic_order = _get_topic_order()
    completed_topics = []
    if session.status == "completed":
        completed_topics = topic_order[:]
    elif session.current_topic in topic_order:
        curr_idx = topic_order.index(session.current_topic)
        completed_topics = topic_order[:curr_idx]
    elif session.current_topic == "Completed":
        completed_topics = topic_order[:]

    return {
        "session_id": session.id,
        "current_topic": session.current_topic,
        "completed_topics": completed_topics,
        "messages": formatted_messages
    }