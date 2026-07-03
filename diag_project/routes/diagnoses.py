import logging
import os
import random
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
from diag_project.services.chapter_translator import (
    topic_to_chapter,
    chapter_to_topic,
    get_next_chapter,
)
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
from diag_project.services.time_greeting import (
    build_rapport_greeting,
    build_rapport_first_turn_response,
)
from diag_project.services.intro_messages import (
    build_intro_anchor_section,
    build_align_framework_section,
    build_chapter_opening_with_user_def,
    build_chapter_transition_question,
    build_chapter_thought_question,
)
from diag_project.prompts.phase3a.layer2_chapters import CHAPTER_CONTEXTS
from diag_project.prompts.phase3a.layer3_state import format_turn_state_for_llm

logger = logging.getLogger(__name__)

# 시스템 제어 마커 패턴: [CHAPTER_COMPLETE], [EVENT_COMPLETE] 등
# '[대문자/숫자/언더바]' 전부. 프론트로 나가는 텍스트에서 완벽 제거용.
_MARKER_RE = re.compile(r"\[[A-Z][A-Z0-9_]*\]")

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

    # 1. 가장 최근의 '진행 중/일시중지' 세션 찾기 (이어하기)
    # paused(휴식 선택) 세션도 반드시 이어하기 대상 — 빠뜨리면 새 세션이 생성돼
    # 기존 진행 내역이 유실된다.
    existing_query = select(DiagnosisSession).where(
        DiagnosisSession.user_id == request.participant_id,
        DiagnosisSession.status.in_(["in_progress", "paused"])
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

    # 1-a. 🛡️ [무한 루프 차단 — 최우선] 완료된 세션은 상태 머신에 절대 재진입 금지.
    #   가드가 없으면 topic_to_chapter("Completed") 가 fallback 으로 '첫 챕터'를
    #   반환해, 끝난 진단이 조직관리부터 좀비처럼 재주행하며 "다음 역량인
    #   ○○로 넘어갈까요?" 를 반복하는 루프가 발생한다.
    if session.status == "completed" or session.current_topic == "Completed":
        _all_topics = _get_topic_order()
        return {
            "coach_response_message": (
                "리더님, 이번 진단은 이미 모두 마무리되었어요. 함께해 주셔서 "
                "감사합니다. 결과 리포트에서 여정을 확인해 보시겠어요?"
            ),
            "is_topic_completed": False,
            "is_session_starting": False,
            "is_session_completed": True,
            "is_session_paused": False,
            "is_awaiting_continue": False,
            "has_next_chapter": False,
            "next_topic": None,
            "reward": None,
            "completed_topics": _all_topics[:],
            "_phase3a_metadata": {"guard": "SESSION_ALREADY_COMPLETED"},
        }

    # 1-b. 일시중지 세션 재개: 사용자가 다시 말을 걸면 paused → in_progress 복원.
    #   (이번 턴이 다시 pause 로 끝나면 11-b 블록이 다시 paused 로 되돌린다.)
    if session.status == "paused":
        session.status = "in_progress"
        db.add(session)
        await db.commit()
        logger.info(f"▶️ paused 세션 재개: {session.id}")

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

    # 4-a. user 메시지 메타데이터 소급 기록 (ML 학습 데이터 구조화):
    #   - 진단 전 단계면 chapter 를 NULL 로 소급 변경 (라포 사담 분리)
    #   - turn_index: 세션 내 누적 user 턴 번호 (user/model 쌍 페어링 키)
    #   - instruction_used: 이 발화가 촉발한 instruction (학습 라벨)
    instruction_used = state.get("instruction_for_this_turn")
    PRE_DIAGNOSIS_INSTRUCTIONS = {
        "RAPPORT_BUILDING",
        "DIAGNOSIS_INTRO",
        "DIAGNOSIS_CONFIRM",
    }
    _turn_index = (
        state.get("turn_count", 0) + state.get("rapport_turn_count", 0)
    )
    if instruction_used in PRE_DIAGNOSIS_INSTRUCTIONS:
        user_msg.chapter = None
    user_msg.turn_index = _turn_index
    user_msg.instruction_used = instruction_used
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
        # 구버전 '챕터 시작 스크립트'(일반 질문 + 중립성 선언 + 위로성 backup)는
        # 첫 질문이 시스템 템플릿(CHAPTER_OPENING)으로 대체되어 더 이상 불필요.
        # LLM 이 이를 그대로 echo 하는 문제 방지를 위해 BEI 턴 컨텍스트에서 제거.
        chapter_context = chapter_context.split("## 챕터 시작 스크립트")[0].rstrip()
    turn_state_text = format_turn_state_for_llm(state)

    # 페르소나 통합 system prompt (코치별 톤 반영)
    coach_key = COACH_UUID_TO_KEY.get(str(session.coach_id), "1")
    user_name = state.get("user_name", "리더")
    system_prompt = build_layer1_with_persona(
        coach_id=coach_key,
        user_name=user_name,
        visit_count=1,
    )

    # 7. 응답 생성 — 라포 1턴 / CHAPTER_OPENING 은 시스템 직접 출력 (LLM 우회)
    # 두 턴은 LLM 확률적 행동(자기소개 반복·정의 누락)이 반복되어
    # 템플릿으로 고정. 나머지 턴은 기존대로 LLM 생성.
    system_override_text = None

    if (instruction_used == "RAPPORT_BUILDING"
            and state.get("rapport_turn_count", 0) == 0):
        # 라포 1턴 (이름 받은 직후) — Step1 이름수용 + Step2 아이스브레이킹.
        # 자기소개 반복 절대 금지 (인사말에서 이미 함). 템플릿으로 고정.
        system_override_text = build_rapport_first_turn_response(
            user_name=user_name,
            current_ampm_phrase=state.get("current_ampm_phrase", "오늘"),
        )
    elif instruction_used == "CHAPTER_OPENING":
        # 챕터 도입 — '목차 노출형'(역량명 호명) 대신, 리더의 직전 답변에서
        # 추출된 키워드(직전 챕터 마지막 사건의 summary)를 브릿지로 삼아
        # 대화가 이전 답변에서 파생되는 느낌을 준다. (첫 챕터엔 키워드 없음)
        _collected = state.get("all_collected_events") or []
        _bridge_ctx = None
        for _ev in reversed(_collected):
            _kw = (_ev.get("summary") or "").strip()
            if _kw:
                _bridge_ctx = _kw
                break
        system_override_text = build_chapter_opening_with_user_def(
            chapter=chapter,
            user_definition=state.get("last_user_response", "") or "",
            first_subcompetency_name=state.get("first_subcompetency_name", ""),
            bridge_context=_bridge_ctx,
        )

    if system_override_text is not None:
        reply = system_override_text
        llm_state = {}
        event_metadata = None
    else:
        # 경량 모드: BEI 진입 전 턴(라포·INTRO·CONFIRM·ALIGN 등)은
        # state·event_metadata 가 불필요 → JSON 봉투 생략 (지연 최소화).
        _LIGHT_MODE_INSTRUCTIONS = {
            "RAPPORT_BUILDING",
            "DIAGNOSIS_INTRO",
            "DIAGNOSIS_CONFIRM",
            "COMPETENCY_ALIGN",
            "META_QUESTION_FROM_USER",
            "USER_REQUESTS_PAUSE",
            "INVALID_INPUT",
            # 주입 대응 턴: 사건 수집 없음 — 거절+복귀 문장만 (경량)
            "PROMPT_INJECTION_DETECTED",
            # 경계 브릿지 턴: 한 문장 브릿지만 (경량)
            "CHAPTER_CONTINUE_CONFIRMED",
        }
        llm_output = await llm.generate_phase3a_interaction(
            system_prompt=system_prompt,
            chapter_context=chapter_context,
            turn_state_text=turn_state_text,
            compressed_history=compressed_history,
            user_message=request.content,
            light_mode=(instruction_used in _LIGHT_MODE_INSTRUCTIONS),
        )
        reply = llm_output["reply"]
        llm_state = llm_output.get("state") or {}
        event_metadata = llm_output.get("event_metadata")

    # 8. 제어 태그 처리 (감사 위험 #4 해결)
    is_chapter_completed = "[CHAPTER_COMPLETE]" in reply
    is_session_paused = "[SESSION_PAUSE]" in reply
    is_ready_for_intro = "[READY_FOR_INTRO]" in reply
    is_chapter_starting = "[START_CHAPTER]" in reply
    is_diagnosis_complete = "[DIAGNOSIS_COMPLETE]" in reply
    # Core Rule 7/9: 코치가 능동적으로 세션을 중단하는 조기 종료 마커
    # (극심한 스트레스·거부감, 동문서답 3진 아웃). 일시중지로 처리해
    # 사용자가 준비되면 이어서 재개할 수 있게 한다.
    is_session_end_early = "[SESSION_END_EARLY]" in reply

    # 🛡️ [방어 로직 — 최우선] 남은 역량(챕터)이 있으면 '전체 진단 종료'를 절대
    # 허용하지 않는다. LLM 이 [DIAGNOSIS_COMPLETE] 를 환각으로 내보내거나 로직이
    # 오판해도, 다음 챕터가 존재하는 한 강제 종료를 원천 차단한다.
    # (사람관리 뒤 일관리·자기관리가 남았는데 종료되던 버그의 근본 방어선)
    _next_chapter_guard = _get_next_chapter(chapter)
    if _next_chapter_guard is not None and is_diagnosis_complete:
        logger.warning(
            "⛔ 조기 종료 차단: chapter=%s 뒤에 '%s'(외 남은 역량)이 있는데 "
            "[DIAGNOSIS_COMPLETE] 감지됨 → 전체 종료 무시하고 다음 역량으로 전환.",
            chapter, _next_chapter_guard,
        )
        is_diagnosis_complete = False

    # 🛡️ [환각 게이트] 챕터 완료/일시중지 마커는 '그 결정이 정당한 instruction'
    # 에서 나왔을 때만 신뢰한다. (예: STAR_INCOMPLETE 도중 LLM 이
    # [CHAPTER_COMPLETE] 를 환각으로 내면 챕터가 조기 전환되던 구멍 차단.
    # 8-d/8-e 블록이 READY_TO_END/CONTINUE_CONFIRMED 의 플래그를 코드로
    # 확정하므로, 이 게이트는 그 외 턴의 환각만 걸러낸다.)
    _COMPLETE_ALLOWED = {
        "CHAPTER_READY_TO_END",       # 최종 챕터 Grand Finale (코드가 확정)
        "CHAPTER_CONTINUE_CONFIRMED",  # 사용자 '계속' 동의 (코드가 확정)
        "MAX_TURNS_REACHED",           # 강제 종료 지시 턴
    }
    if is_chapter_completed and instruction_used not in _COMPLETE_ALLOWED:
        logger.warning(
            "⛔ 환각 차단: instruction=%s 턴에서 [CHAPTER_COMPLETE] 감지 → 무시.",
            instruction_used,
        )
        is_chapter_completed = False
    if is_session_paused and instruction_used != "USER_REQUESTS_PAUSE":
        logger.warning(
            "⛔ 환각 차단: instruction=%s 턴에서 [SESSION_PAUSE] 감지 → 무시.",
            instruction_used,
        )
        is_session_paused = False

    # [SESSION_END_EARLY] 게이트: 코치의 능동적 조기 종료(Core Rule 7/9)는
    # '실제 대화 턴'에서만 신뢰한다. 시스템 조립/전환 턴(INTRO·ALIGN·경계 등)
    # 에서 나오면 환각으로 간주해 무시 — 정당하면 일시중지로 전환.
    _EARLY_END_ALLOWED = {
        "CONTINUE_NORMAL", "STAR_INCOMPLETE", "STAR_COMPLETE_NEW_EVENT",
        "CONTRARY_NEEDED", "AVOIDANCE_DETECTED", "DUPLICATE_SUSPECTED",
        "CROSS_CHAPTER_OPPORTUNITY", "META_QUESTION_FROM_USER",
        "FIRST_TURN_AVOIDANCE", "INVALID_INPUT", "RAPPORT_BUILDING",
        "PROMPT_INJECTION_DETECTED",
    }
    if is_session_end_early:
        if instruction_used in _EARLY_END_ALLOWED:
            logger.info(
                "🛑 코치 판단 조기 종료(SESSION_END_EARLY): instruction=%s "
                "→ 세션 일시중지로 전환.", instruction_used,
            )
            is_session_paused = True
            # 조기 종료 턴에는 챕터 전환/완료 마커가 있어도 무효
            is_chapter_completed = False
            is_chapter_starting = False
            is_diagnosis_complete = False
        else:
            logger.warning(
                "⛔ 환각 차단: instruction=%s 턴에서 [SESSION_END_EARLY] "
                "감지 → 무시.", instruction_used,
            )
            is_session_end_early = False

    # 시스템 제어 마커 완벽 제거 — 고정 목록 replace 는 [EVENT_COMPLETE] 같은
    # 목록 밖 마커가 새어 나가므로, '[대문자_언더바]' 패턴 전체를 정규식으로
    # 스트립한다. (상태 전진용 파싱은 위에서 원본 reply 로 이미 완료됨)
    clean_reply = _MARKER_RE.sub("", reply).strip()
    # 개행 정규화: 정규식 파서가 못 푼 '\n' 리터럴이 프론트에 노출되는 버그 방지.
    # (json.loads 로 이미 풀린 경우엔 리터럴이 없어 무해)
    clean_reply = (
        clean_reply.replace("\\n", "\n").replace('\\"', '"').replace("\\t", "\t")
    )

    # 일시중지 확정: USER_REQUESTS_PAUSE 면 LLM 의 [SESSION_PAUSE] 마커 누락과
    # 무관하게 무조건 일시중지 처리 (챕터 전환 차단 + 세션 대기 전환).
    if instruction_used == "USER_REQUESTS_PAUSE":
        is_session_paused = True

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

    # 8-c. CHAPTER_OPENING 은 Step 7 에서 시스템이 전체 출력 (하이브리드 폐지).
    # build_chapter_opening_with_user_def 가 정의 + 첫 BEI 질문까지 포함하므로
    # 별도 후처리 불필요.

    _next_ch = _get_next_chapter(chapter)

    # 8-d. CHAPTER_READY_TO_END 하이브리드 (종결 후 '계속/휴식' 의사 확인):
    #   중간 챕터: LLM 이 wrap-up(요약+공감) + '계속/휴식 질문'을 생성한다.
    #   여기서는 챕터를 전환하지 않고 사용자 답변을 '대기'한다 (AWAIT_CONTINUE).
    #   → 다음 턴에 decider 가 계속/휴식으로 분기.
    if instruction_used == "CHAPTER_READY_TO_END":
        wrap_up = clean_reply.strip() or "이 영역, 여기서 잘 매듭짓겠습니다."
        if _next_ch:
            # 질문 누락 시에만 시스템이 다변화된 계속/휴식 질문을 덧붙임.
            if "?" not in wrap_up:
                wrap_up = f"{wrap_up}\n\n{build_chapter_transition_question(_next_ch)}"
            clean_reply = wrap_up
            # 🚧 전환 보류: 완료/시작 마커를 세우지 않는다 (사용자 답변까지 대기).
            is_chapter_completed = False
            is_chapter_starting = False
        else:
            # 🏁 마지막 챕터 — Grand Finale 만, 전환 없음.
            #   [START_CHAPTER] 절대 X, 대신 [DIAGNOSIS_COMPLETE] 로 진단 종료 확정.
            clean_reply = wrap_up
            is_chapter_completed = True
            is_chapter_starting = False
            is_diagnosis_complete = True

    # 8-e. CHAPTER_CONTINUE_CONFIRMED (사용자가 '계속' 동의):
    #   짧은 브릿지 멘트 + 이제 실제로 챕터 완료·다음 챕터 시작 마커를 세운다.
    #   → 다음 턴에 다음 영역 COMPETENCY_ALIGN 으로 자연스럽게 진입.
    if instruction_used == "CHAPTER_CONTINUE_CONFIRMED":
        clean_reply = clean_reply.strip() or "좋습니다. 그럼 바로 이어가 볼게요."
        # 🛡️ 대화 정체 방지: 브릿지만 나가고 질문이 없으면 사용자가 무엇을
        # 답해야 할지 알 수 없다(다음 턴 ALIGN 이 받을 '사용자 생각'도 미수집).
        # 다음 역량에 대한 생각을 여는 질문을 시스템이 이어 붙인다.
        if _next_ch and "?" not in clean_reply:
            clean_reply = (
                f"{clean_reply}\n\n{build_chapter_thought_question(_next_ch)}"
            )
        is_chapter_completed = True
        is_chapter_starting = True

    # 8-f. 🦜 앵무새 방어: 직전 AI 멘트와 '동일한' 응답이 또 생성되면
    #   (상태 정체 + 사용자 '네' 단답 시 같은 요약을 반복하는 병목),
    #   반복 대신 대화를 앞으로 미는 진행 유도 질문으로 교체한다.
    if system_override_text is None and clean_reply:
        _last_model_q = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session.id)
            .where(ChatMessage.role == "model")
            .order_by(ChatMessage.created_at.desc())
            .limit(1)
        )
        _last_model_msg = _last_model_q.scalars().first()
        if (_last_model_msg
                and _last_model_msg.content
                and _last_model_msg.content.strip() == clean_reply.strip()):
            logger.warning("🦜 동일 응답 반복 감지 → 진행 유도 멘트로 교체")
            clean_reply = random.choice([
                "네, 이 부분은 충분히 나눈 것 같아요. 조금 다른 각도에서 "
                "여쭤볼게요 — 최근 이와 관련해 새롭게 고민되셨던 지점이 "
                "있다면 어떤 걸까요?",
                "좋습니다, 여기까지는 잘 정리된 것 같아요. 그럼 한 걸음 더 "
                "들어가서, 그 상황에서 리더님이 내리신 판단의 기준이 "
                "궁금해지는데요 — 어떤 기준이었어요?",
                "말씀 감사해요. 이 이야기는 여기서 잘 매듭짓고, 이어서 "
                "여쭤보고 싶은 게 하나 있어요 — 비슷한 상황이 다시 온다면 "
                "그때도 같은 선택을 하실까요?",
            ])

    # 8-g. 최종 안전망: 하이브리드 조립 이후에도 남아있을 수 있는 시스템
    #   마커를 프론트 전달 직전에 한 번 더 완벽 제거.
    clean_reply = _MARKER_RE.sub("", clean_reply).strip()

    # 9. 사건 생명주기 처리 + AI 메시지 저장
    probe_type_used = llm_state.get("probe_type_used")

    # 사용자가 '계속' 동의(CHAPTER_CONTINUE_CONFIRMED)했을 때만 다음 챕터를
    # '시작됨'으로 표시해, 중간 CONFIRM 턴 없이 바로 다음 영역 합의(ALIGN)로
    # 이어지게 한다. (CHAPTER_READY_TO_END 는 이제 전환하지 않고 대기만 한다.)
    _seamless_next_chapter = None
    if (instruction_used == "CHAPTER_CONTINUE_CONFIRMED"
            and is_chapter_completed and is_chapter_starting):
        _seamless_next_chapter = _get_next_chapter(chapter)

    # 마커 → probe_type_used 에 저장 (우선순위: READY_FOR_INTRO > AWAIT_CONTINUE
    # > START_CHAPTER)
    if instruction_used == "RAPPORT_BUILDING" and is_ready_for_intro:
        probe_type_used = "READY_FOR_INTRO"
    elif instruction_used == "DIAGNOSIS_CONFIRM" and is_chapter_starting:
        probe_type_used = "START_CHAPTER"
    elif instruction_used == "CHAPTER_READY_TO_END" and _next_ch:
        # 중간 챕터 종료: '계속/휴식' 질문 던지고 대기 중임을 마커로 표시.
        probe_type_used = "AWAIT_CONTINUE"
    elif _seamless_next_chapter:
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

    # START_CHAPTER 마커 메시지는 진단 전 단계라도 해당 챕터로 태깅.
    # (chapter_started 쿼리가 chapter 별로 스코프되므로 — 안 그러면
    #  마커가 chapter=None 에 저장돼 chapter_started 가 영영 False)
    # 종결+전환 1턴(CHAPTER_READY_TO_END)이면 마커를 '다음 챕터'로 태깅해
    # 새 챕터를 시작됨으로 만든다.
    if probe_type_used == "START_CHAPTER":
        ai_msg_chapter = _seamless_next_chapter or chapter
    else:
        ai_msg_chapter = None if is_pre_diagnosis else chapter

    ai_msg = ChatMessage(
        session_id=session.id,
        role="model",
        content=clean_reply,
        chapter=ai_msg_chapter,
        event_id=None if is_pre_diagnosis else real_event_id,
        probe_type_used=probe_type_used,
        instruction_used=instruction_used,
        turn_index=_turn_index,  # user 메시지와 동일 값 → ML 페어링 키
    )
    db.add(ai_msg)
    await db.commit()

    # 11. 챕터 전진 처리
    is_session_completed = False
    if is_chapter_completed:
        next_chapter = _get_next_chapter(chapter)
        if next_chapter:
            # 🛡️ 다음 역량이 존재하면 '무조건' 다음으로 전환한다.
            #   (is_diagnosis_complete 는 위 방어 로직에서 이미 False 로 정정됐지만,
            #    이중 안전장치로 next_chapter 존재를 최우선 조건으로 둔다.)
            session.current_topic = chapter_to_topic(next_chapter)
            if is_diagnosis_complete:
                logger.warning(
                    "⛔ 종료 플래그 무시: '%s' 역량이 남아있어 전환 우선.",
                    next_chapter,
                )
                is_diagnosis_complete = False
        else:
            # 진짜 마지막 챕터(다음 없음) → 진단 종료 확정
            session.current_topic = "Completed"
            session.status = "completed"
            is_session_completed = True
        db.add(session)
        await db.commit()

    # 11-b. 일시중지: 세션을 '대기(paused)' 상태로 전환.
    #   비정상 챕터 전환 없이(위 전진 블록은 is_chapter_completed=False 라 스킵)
    #   진단을 보류하고, 프론트가 대기 상태로 인지하도록 status 를 바꾼다.
    #   현재 챕터/토픽은 그대로 두어 나중에 이어서 재개할 수 있게 한다.
    if is_session_paused and session.status != "completed":
        session.status = "paused"
        db.add(session)
        await db.commit()

    # 12-a. 누적 완료 역량 계산 (Hall of Achievements 배지 유지용).
    #   매 턴 빈 배열을 반환하면 프론트가 배지를 덮어써 초기화되는 버그 →
    #   현재 진행 토픽 기준으로 '이미 완료된 토픽'을 누적해서 반환.
    _topic_order = _get_topic_order()
    if session.status == "completed" or session.current_topic == "Completed":
        completed_topics = _topic_order[:]
    elif session.current_topic in _topic_order:
        completed_topics = _topic_order[: _topic_order.index(session.current_topic)]
    else:
        completed_topics = []

    # 12-b. [안전장치 — req 3] 다음 역량 정보 노출.
    #   혹시라도 종료로 오판되더라도, 프론트가 '다음 항목 확인'을 시도할 수 있게
    #   현재 챕터 기준 '다음 역량' 존재 여부와 이름을 함께 반환한다.
    #   has_next_chapter=True 인데 is_session_completed 라면 프론트는 종료 대신
    #   '다음 항목 확인'을 노출해야 한다 (조기 종료 방어의 클라이언트측 안전망).
    _safety_next_chapter = _get_next_chapter(chapter)
    _safety_next_topic = (
        chapter_to_topic(_safety_next_chapter) if _safety_next_chapter else None
    )

    # 12. 응답 (감사 위험 #3 해결: reply → coach_response_message 매핑)
    return {
        "coach_response_message": clean_reply,
        "is_topic_completed": is_chapter_completed,
        "is_session_starting": False,
        "is_session_completed": is_session_completed,
        "is_session_paused": is_session_paused,
        # 챕터 경계에서 '계속/휴식' 답변을 기다리는 중 — 프론트가 선택 버튼 노출
        "is_awaiting_continue": probe_type_used == "AWAIT_CONTINUE",
        "has_next_chapter": _safety_next_chapter is not None,
        "next_topic": _safety_next_topic,
        "reward": None,
        "completed_topics": completed_topics,
        "_phase3a_metadata": {
            "chapter": chapter,
            "instruction_used": instruction_used,
            "probe_type_used": probe_type_used,
            "turn_count": state.get("turn_count"),
            "events_collected": state.get("events_collected"),
        },
    }


def _get_next_chapter(current_chapter: str) -> str | None:
    """다음 챕터 결정 — chapter_translator 의 단일 소스에 위임.

    (순서 리스트 중복 정의가 next_chapter 어긋남 버그의 온상이라 제거함.)
    """
    return get_next_chapter(current_chapter)


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

    # 상태 재동기화(Sync)용 부가 정보 — 프론트가 현재 단계를 명확히 인지하고
    # '진단 계속하기'/'다음 챕터로 이동' 버튼을 정확히 노출할 수 있도록 제공.
    _is_completed = (
        session.status == "completed" or session.current_topic == "Completed"
    )
    _next_chapter = None
    _next_topic = None
    if not _is_completed:
        _cur_chapter = topic_to_chapter(session.current_topic)
        _next_chapter = _get_next_chapter(_cur_chapter)
        _next_topic = chapter_to_topic(_next_chapter) if _next_chapter else None

    # 챕터 경계 '계속/휴식' 대기 여부 — 마지막 AI 메시지의 AWAIT_CONTINUE 마커.
    # (새로고침/재동기화 후에도 프론트가 선택 버튼을 복원할 수 있도록 제공)
    _last_model_msg = next(
        (m for m in reversed(messages) if m.role == "model"), None
    )
    _is_awaiting_continue = (
        _last_model_msg is not None
        and _last_model_msg.probe_type_used == "AWAIT_CONTINUE"
        and not _is_completed
    )

    return {
        "session_id": session.id,
        "current_topic": session.current_topic,
        "completed_topics": completed_topics,
        "status": session.status,
        "is_paused": session.status == "paused",
        "is_completed": _is_completed,
        "is_awaiting_continue": _is_awaiting_continue,
        "has_next_chapter": _next_chapter is not None,
        "next_topic": _next_topic,
        "messages": formatted_messages
    }