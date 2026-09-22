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
from sqlalchemy import func, desc
from pydantic import BaseModel

from diag_project.config import phase3a_enabled
from diag_project.database import get_db
from diag_project.models.diagnosis_session import DiagnosisSession, ChatMessage, MessageRole
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
from diag_project.services.avoidance_detector import (
    detect_deflection,
    detect_rush,
)
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
    build_chapter_opening_with_user_def,
)
from diag_project.data.competencies import COMPETENCY_FRAMEWORK
from diag_project.prompts.phase3a.layer2_chapters import CHAPTER_CONTEXTS
from diag_project.prompts.phase3a.layer3_state import format_turn_state_for_llm
from diag_project.services.traversal import (
    advanced_to_new_target, is_result_probe_text,
)
from diag_project.services.style_tracker import is_recap_turn, starts_with_ne_recap

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
    # 2단계 '새로 시작': True 면 재개 가능한 기존 세션을 abandoned(보관, 삭제 아님)로
    # 바꾸고 새 세션을 만든다. 기본 False = 기존대로 재개.
    force_new: bool = False


class AbandonRequest(BaseModel):
    participant_id: uuid.UUID


class RestoreRequest(BaseModel):
    """4(c) 복원: abandoned 세션을 다시 in_progress 로(상태 전이 표의 '복원 경로').
    (참가자 경로는 파일럿 범위라 인증 없음 — (B) 에서 소유자 검증. 관리자 경로는 require_admin.)"""
    session_id: uuid.UUID

class ChatMessageRequest(BaseModel):
    session_id: uuid.UUID
    diagnosis_id: Optional[uuid.UUID] = None 
    content: str

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


def _coach_key_from_id(coach_id) -> str:
    """🐛 fix: 사용자가 '선택한' coach_id → COACHES_PERSONA 키("1"~"6").

    (구 _session_coach_key 는 세션 UUID 로 코치를 '랜덤 배정'해 사용자 선택을
    무력화했다 — 선택한 Ella/Jessica 를 골라도 인사·페르소나가 세션-랜덤 코치로
    나오던 버그. 이제 저장된 선택 coach_id 를 그대로 읽는다.)

    매핑 실패(미존재/None)면 기본 "1" 로 폴백하되, '조용한 오배정' 재발을 막기
    위해 반드시 경고 로그를 남긴다.
    """
    key = COACH_UUID_TO_KEY.get(str(coach_id))
    if not key:
        logger.warning(
            "🚨 코치 매핑 실패 — coach_id=%r 를 COACHES_PERSONA 키로 해석 못함. "
            "기본 '1'(Ella)로 폴백. 선택이 무시되고 있으니 즉시 점검할 것.",
            coach_id)
        return "1"
    return key


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
# [0] 진행 중 세션 사전 확인 (GET /active) — 코치 선택 화면에서 미리 안내용.
#   진행 중/일시중지 세션이 있으면 그 세션의 '원래 코치'를 함께 알려, 코치를
#   새로 골라도 재개 시 원래 코치로 이어짐을 미리 고지할 수 있게 한다.
# ------------------------------------------------------------------
# 🔁 H3: '이어하기' 대상 상태의 단일 정의. /active·/start·submit_message 1-b 가
#   전부 이 집합을 본다. aborted_disengaged(A-4 참여 이탈 중단)는 설계상 '원장
#   보존 + 재개 가능'인데 과거엔 in_progress/paused 만 재개돼 새 세션이 생기며
#   원장이 고아가 됐다. aborted(3-Strike)는 재개 불가 — 여기 넣지 않는다.
RESUMABLE_STATUSES = ("in_progress", "paused", "aborted_disengaged")
# 2단계 '새로 시작': 리더가 기존 진단을 두고 새로 시작하면 기존 세션은 이 상태로
# '보관'된다(삭제 아님 — 원장·대화 유지, 리포트 파이프라인 미호출). 재개 대상이
# 아니므로 RESUMABLE_STATUSES 에 넣지 않는다. analyze 도 이 상태를 덮어쓰지 않는다.
ABANDONED = "abandoned"


def mark_abandoned(sessions) -> int:
    """재개 가능한 세션 객체들을 abandoned 로 표시하고 개수를 돌려준다(순수, 커밋은 호출자).

    RESUMABLE_STATUSES 가 아닌 세션(completed/aborted 등)은 건드리지 않는다.
    """
    n = 0
    for s in sessions or []:
        if getattr(s, "status", None) in RESUMABLE_STATUSES:
            s.status = ABANDONED
            s.updated_at = datetime.now()
            n += 1
    return n


# ── 세션 상태 전이 표 — docs/session_state_transitions.md 와 항상 동일하게 유지 ──
#   in_progress ⇄ paused                      (휴식 / 재개: submit_message)
#   in_progress → completed                    (분석 완료: reports.analyze)
#   in_progress → aborted                      (3-Strike 강제 종료 — 종점, 재개·복원 불가)
#   in_progress → aborted_disengaged → in_progress   (참여 이탈 중단 / 재개: submit_message)
#   in_progress·paused·aborted_disengaged → abandoned   (새로 시작: /abandon, /start force_new)
#   abandoned → in_progress                    (복원 — 이 경로만: /restore, /admin/sessions/{id}/restore)
#   이 표에 없는 전이는 만들지 않는다(빈틈 방지).


def apply_restore(target, others) -> dict:
    """4(c) 복원(순수, 커밋은 호출자).

    - target: abandoned → in_progress. paused/aborted_disengaged 도 in_progress 로.
      이미 in_progress 면 멱등(두 번 복원해도 꼬이지 않음).
    - others: 같은 참가자의 다른 재개 가능 세션 → abandoned (진행 중인 새 세션은 보관).
    - completed / aborted 는 복원 불가 → ValueError (호출자가 409).
    - 원장·메시지·이벤트 무변경. 상태만 바뀐다.
    """
    st = getattr(target, "status", None)
    if st not in (ABANDONED,) + tuple(RESUMABLE_STATUSES):
        raise ValueError(f"복원할 수 없는 상태입니다: {st}")
    already = st == "in_progress"
    target.status = "in_progress"
    target.updated_at = datetime.now()
    tid = getattr(target, "id", None)
    n = mark_abandoned([o for o in (others or []) if getattr(o, "id", None) != tid])
    return {"restored": True, "already_in_progress": already, "abandoned_others": n}


async def restore_session_by_id(db: AsyncSession, session_id: uuid.UUID) -> dict:
    """복원 공용 처리 — 참가자 경로(/restore)와 관리자 경로(/admin/sessions/{id}/restore)가 함께 쓴다."""
    s = await db.get(DiagnosisSession, session_id)
    if not s:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")
    others_q = select(DiagnosisSession).where(
        DiagnosisSession.user_id == s.user_id,
        DiagnosisSession.status.in_(list(RESUMABLE_STATUSES)),
        DiagnosisSession.id != s.id,
    )
    others = (await db.execute(others_q)).scalars().all()
    try:
        r = apply_restore(s, others)
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    db.add(s)
    for o in others:
        db.add(o)
    await db.commit()
    key = _coach_key_from_id(s.coach_id)
    logger.info("♻️ 복원: session=%s participant=%s 다른 진행 세션 %d건 abandoned",
                s.id, s.user_id, r["abandoned_others"])
    return {
        **r,
        "session_id": str(s.id),
        "participant_id": str(s.user_id),
        "status": s.status,
        "coach_id": str(s.coach_id),
        "coach_name": COACHES_PERSONA[key]["name"],
    }


@router.get("/active")
async def get_active_session(
    participant_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    q = select(DiagnosisSession).where(
        DiagnosisSession.user_id == participant_id,
        DiagnosisSession.status.in_(list(RESUMABLE_STATUSES)),
    ).order_by(desc(DiagnosisSession.created_at))
    s = (await db.execute(q)).scalars().first()
    if not s:
        return {"has_active": False}
    key = _coach_key_from_id(s.coach_id)
    return {
        "has_active": True,
        "session_id": str(s.id),
        "coach_id": str(s.coach_id),
        "coach_name": COACHES_PERSONA[key]["name"],
    }


# ------------------------------------------------------------------
# [0-b] '새로 시작' — 재개 가능한 세션을 abandoned 로 보관 (POST /abandon)
#   코치 선택 화면의 재개 배너에서 확인 팝업을 거친 뒤 호출한다. 삭제가 아니라
#   상태 전환이므로 원장·대화는 남고, 이후 /start 는 새 세션을 만든다.
#   (참가자 인증은 (B) 작업에서 다른 참가자 API 와 함께 소유자 검증을 붙인다.)
# ------------------------------------------------------------------
@router.post("/abandon")
async def abandon_resumable_sessions(
    request: AbandonRequest,
    db: AsyncSession = Depends(get_db),
):
    q = select(DiagnosisSession).where(
        DiagnosisSession.user_id == request.participant_id,
        DiagnosisSession.status.in_(list(RESUMABLE_STATUSES)),
    )
    sessions = (await db.execute(q.order_by(desc(DiagnosisSession.created_at)))).scalars().all()
    n = mark_abandoned(sessions)
    for s in sessions:
        db.add(s)
    await db.commit()
    logger.info("🗂️ 새로 시작: participant=%s 세션 %d건 abandoned 보관",
                request.participant_id, n)
    # 4(a) 즉시 되돌리기용: 방금 보관한 세션(최신 순)과 코치를 돌려준다.
    return {
        "abandoned": n,
        "sessions": [
            {
                "session_id": str(s.id),
                "coach_id": str(s.coach_id),
                "coach_name": COACHES_PERSONA[_coach_key_from_id(s.coach_id)]["name"],
            }
            for s in sessions
        ],
    }


# ------------------------------------------------------------------
# [0-c] 복원 — abandoned → in_progress (POST /restore)  ※ 상태 전이 표의 유일한 복원 경로
#   4(a) 즉시 되돌리기(자가진단 상단 배너)가 호출한다. 같은 참가자의 다른 진행 세션
#   (방금 만든 빈 세션 등)은 abandoned 로. 참가자 인증은 (B) 에서 — 파일럿 범위 감수.
# ------------------------------------------------------------------
@router.post("/restore")
async def restore_abandoned_session(
    request: RestoreRequest,
    db: AsyncSession = Depends(get_db),
):
    return await restore_session_by_id(db, request.session_id)


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

    # 1. 가장 최근의 '이어하기 대상' 세션 찾기 (RESUMABLE_STATUSES 단일 정의)
    # paused(휴식)·aborted_disengaged(참여 이탈 중단, A-4) 모두 재개 대상 —
    # 빠뜨리면 새 세션이 생성돼 기존 원장(asked/measured)이 고아가 된다.
    existing_query = select(DiagnosisSession).where(
        DiagnosisSession.user_id == request.participant_id,
        DiagnosisSession.status.in_(list(RESUMABLE_STATUSES))
    ).order_by(desc(DiagnosisSession.created_at))
    
    result = await db.execute(existing_query)
    existing_session = result.scalars().first()

    # [Case A-0] '새로 시작'(force_new): 재개 가능한 세션을 전부 abandoned 로 보관하고
    #   새 세션으로 간다(/abandon 을 못 거친 경로의 안전망 — 같은 결과).
    if existing_session and request.force_new:
        _all_res = (await db.execute(existing_query)).scalars().all()
        _n = mark_abandoned(_all_res)
        for _s in _all_res:
            db.add(_s)
        await db.commit()
        logger.info("🗂️ force_new: participant=%s 세션 %d건 abandoned → 새 세션",
                    request.participant_id, _n)
        existing_session = None

    # [Case A] 진행 중인 세션이 있다! -> 이어하기(Resume)
    if existing_session:
        logger.info(f"🔄 Resuming existing session: {existing_session.id}")
        
        # 마지막 AI 메시지 가져오기 (문맥 유지용)
        last_msg_query = select(ChatMessage).where(
            ChatMessage.session_id == existing_session.id,
            ChatMessage.role == MessageRole.MODEL
        ).order_by(desc(ChatMessage.created_at))
        last_msg_res = await db.execute(last_msg_query)
        last_message = last_msg_res.scalars().first()
        
        # 메시지가 없으면 기본 멘트
        response_msg = last_message.content if last_message else "리더님, 다시 만나서 반가워요. 이어서 진행해볼까요?"

        # 재개 세션의 '원래 코치'를 함께 반환 — 프론트가 방금 클릭한 코치가 아니라
        #   이 세션의 코치로 프로필·안내를 표시하게 한다(재개 시 코치 불일치 방지).
        _resume_key = _coach_key_from_id(existing_session.coach_id)
        _resume_coach_name = COACHES_PERSONA[_resume_key]["name"]

        return {
            "diagnosis_id": existing_session.id,
            "session_id": existing_session.id,
            "coach_response_message": response_msg,
            "next_action": "resume",  # 프론트엔드에 '이어하기'임을 알림
            "coach_id": str(existing_session.coach_id),  # 재개 세션의 원래 코치
            "coach_name": _resume_coach_name,
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

    use_phase3a = phase3a_enabled()

    if use_phase3a:
        # Phase 3-A: 라포 단계로 시작 (챕터 스크립트는 라포 완료 후)
        # 🎭 세션별 랜덤 코치 배정 — 인사말의 코치 이름도 세션 코치로 통일.
        _coach_name = COACHES_PERSONA[
            _coach_key_from_id(new_session.coach_id)
        ]["name"]
        first_msg_content = build_rapport_greeting(_coach_name)
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
    use_phase3a = phase3a_enabled()
    if use_phase3a:
        return await _submit_message_phase3a(request, db, llm)
    return await _submit_message_legacy(request, db, llm)


async def _submit_message_legacy(
    request: ChatMessageRequest,
    db: AsyncSession,
    llm: GeminiService,
):
    """기존 흐름. USE_PHASE3A=false 시 사용. 본문 변경 금지.

    🚨 이 경로는 제어역전·넓이게이트·정의합의가 없는 '죽은 경로'다. 프로덕션은
    반드시 phase3a 여야 한다. 여기 진입했다는 것은 USE_PHASE3A 설정 실수 신호.
    """
    logger.warning(
        "🚨 레거시 흐름 진입 — USE_PHASE3A 가 꺼져 있다(품질 시스템 OFF). "
        "프로덕션이라면 즉시 USE_PHASE3A=true 로 설정할 것. session=%s",
        request.session_id)
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
    import time as _time
    # ⏱ (2026-09-18) 턴 계측: decider / LLM 1차 / 재생성 횟수·시간 / 후처리+DB. 로그 한 줄로 남긴다.
    _tm = {"t0": _time.perf_counter(), "decider": 0.0, "llm": 0.0, "regen_n": 0, "regen_s": 0.0}
    _style_tail = ""

    _gen = llm.generate_phase3a_interaction

    async def _timed_regen(**kw):
        """재생성 호출 래퍼 — 횟수·시간 누적 + 꼬리 블록 자동 전달."""
        _r0 = _time.perf_counter()
        _tm["regen_n"] += 1
        try:
            return await _gen(tail_block=_style_tail, **kw)
        finally:
            _tm["regen_s"] += _time.perf_counter() - _r0

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
            "has_next_chapter": False,
            "next_topic": None,
            "reward": None,
            "completed_topics": _all_topics[:],
            "_phase3a_metadata": {"guard": "SESSION_ALREADY_COMPLETED"},
        }

    # 1-a2. 🛡️ [무한 루프 차단] 강제 종료(aborted)된 세션도 상태 머신 재진입 금지.
    #   가드가 없으면 후속 입력마다 상태 머신을 다시 돌아 종료 멘트를 반복
    #   생성한다(프론트가 is_terminated 로 입력을 잠그지만 API 레벨 2차 방어).
    if session.status in ("aborted", ABANDONED):
        return {
            "coach_response_message": (
                "이 진단은 새로 시작하면서 보관되었습니다. 코치 선택 화면에서 "
                "새 진단을 이어가 주세요."
                if session.status == ABANDONED else
                "저는 현재 리더님께서 진단을 진행하실 준비가 필요하다고 "
                "생각됩니다. 진단 준비가 되셨을 때 다시 접속해 주시기 바랍니다. "
                "그럼 진단은 여기서 종료하겠습니다."
            ),
            "is_topic_completed": False,
            "is_session_starting": False,
            "is_session_completed": False,
            "is_session_paused": False,
            "has_next_chapter": False,
            "next_topic": None,
            "reward": None,
            "is_terminated": True,
            "session_status": session.status,
            "_phase3a_metadata": {"guard": "SESSION_ALREADY_ABORTED"},
        }

    # 1-b. 재개: 사용자가 다시 말을 걸면 paused / aborted_disengaged → in_progress.
    #   (이번 턴이 다시 pause 로 끝나면 11-b 가 paused 로, 다시 이탈 확정이면
    #    A-4 블록이 aborted_disengaged 로 되돌린다.) H3: aborted_disengaged 는
    #   설계상 '원장 보존·재개 가능'인데 과거엔 복원 분기가 없어 상태가 영영
    #   aborted_disengaged 인 채 상태 머신만 돌았다.
    if session.status in ("paused", "aborted_disengaged"):
        logger.info("▶️ %s 세션 재개 → in_progress: %s", session.status, session.id)
        session.status = "in_progress"
        db.add(session)
        await db.commit()

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

    # (2026-09-22) 전체 히스토리 1회 로드 — 직전 코치 문장(사건 슬롯·앵커 반복 방지)·한 자리 경과(일시중지 제안)에 쓴다.
    history_messages = (await db.execute(
        select(ChatMessage).where(ChatMessage.session_id == session.id).order_by(ChatMessage.created_at.asc())
    )).scalars().all()
    _recent_coach_texts: list[str] = [
        (m.content or "") for m in history_messages if (m.role == MessageRole.MODEL or m.role == "model")
    ][-2:][::-1]
    _prev_coach_text = _recent_coach_texts[0] if _recent_coach_texts else ""

    # 🚦 A: 참여 이탈(disengagement) 추적. 중단 트리거는 '근거 부족'이 아니라
    #   '참여 이탈'(A-0) — 부재 진술처럼 성실히 설명한 경우(engaged)는 카운트
    #   하지 않는다. build_turn_state 가 이 store 를 읽어 ABORT_CONFIRM/
    #   ABORT_DISENGAGED 를 결정한다.
    # 직전 코치 턴이 '실제 BEI 프로브'였을 때만 이탈 카운팅한다. 라포·인트로·
    #   컨펌·역량합의 등 온보딩 턴은 프로브가 아니므로 제외(조기 중단 방지).
    _BEI_PROBE_INSTR = {
        "CHAPTER_OPENING", "CONTINUE_NORMAL", "STAR_INCOMPLETE",
        "STAR_COMPLETE_NEW_EVENT", "CONTRARY_NEEDED", "ABSTRACT_AVOIDANCE",
        "AVOIDANCE_DETECTED", "ABSENCE_PROBE", "ABORT_CONFIRM",
        "CHAPTER_NO_YIELD_ULTIMATUM",
        "COMPETENCY_ALIGN",  # #2: ALIGN 턴이 첫 앵커를 품으므로 그 답변도 프로브 답변
    }
    _last_probe = None
    if chapter:
        _lp = await db.execute(
            select(ChatMessage.instruction_used)
            .where(ChatMessage.session_id == session.id)
            .where(ChatMessage.role == MessageRole.MODEL)  # 코치 메시지 role=model
            .order_by(ChatMessage.created_at.desc()).limit(1)
        )
        _last_probe = _lp.scalars().first()
        # 🚨 V-7: 코치 메시지가 있어야 정상인 지점에서 None 이면 role 조회 오류
        #   가능성(예: role 문자열 오타)을 조용히 넘기지 않고 경고한다.
        if _last_probe is None:
            _mc = await db.execute(
                select(func.count()).select_from(ChatMessage)
                .where(ChatMessage.session_id == session.id)
                .where(ChatMessage.role == MessageRole.MODEL)
            )
            if (_mc.scalar() or 0) > 0:
                logger.warning(
                    "⚠️ 직전 코치 instruction 조회가 None 인데 코치 메시지는 "
                    "존재 — role 조회 경로 점검 필요(세션 %s).", session.id,
                )
    if chapter and _last_probe in _BEI_PROBE_INSTR:
        from diag_project.services.avoidance_detector import (
            classify_engagement, detect_disengagement_refusal,
        )
        from diag_project.services.instruction_decider import is_user_consent
        from sqlalchemy.orm.attributes import flag_modified as _fm_eng
        _dstore = dict(session.self_assessment_data or {})
        _eng, _det = classify_engagement(request.content)
        if _dstore.get("awaiting_abort_decision"):
            # A-3: 직전 ABORT_CONFIRM 에 대한 답변으로 분기.
            _cont = (is_user_consent(request.content)
                     or (_eng == "engaged"
                         and not detect_disengagement_refusal(request.content)))
            _dstore["awaiting_abort_decision"] = False
            if _cont:                                  # 계속 → 카운터 리셋
                _dstore["disengagement_streak"] = 0
                _dstore["pending_abort"] = False
                _dstore["abort_confirm_count"] = int(
                    _dstore.get("abort_confirm_count", 0)) + 1
            else:                                      # 중단/무응답/거부 → 확정
                _dstore["pending_abort"] = True
        else:
            _cyc = int(_dstore.get("probe_cycles", 0)) + 1
            _prev_stk = int(_dstore.get("disengagement_streak", 0))
            if _eng == "engaged":
                _stk = 0
            elif _eng == "pause":
                # H4: 휴식 요청은 이탈이 아니다 — 연속 이탈 카운터를 올리지도
                #   리셋하지도 않는다(→ USER_REQUESTS_PAUSE 로 paused).
                _stk = _prev_stk
            else:
                _stk = _prev_stk + 1
            _dstore["probe_cycles"] = _cyc
            _dstore["disengagement_streak"] = _stk
            _dstore["last_refusal"] = (_eng == "refusal")
        _dstore["last_engagement"] = _eng
        session.self_assessment_data = _dstore
        _fm_eng(session, "self_assessment_data")
        await db.commit()
        logger.info(
            "🚦 참여상태 [%s] streak=%d cycles=%d awaiting=%s pending_abort=%s "
            "(%s len=%d sub=%s)", _eng,
            _dstore.get("disengagement_streak", 0),
            _dstore.get("probe_cycles", 0),
            _dstore.get("awaiting_abort_decision"),
            _dstore.get("pending_abort"), _det["reason"],
            _det["length"], _det["has_substance"],
        )

    # 4. Turn State 빌드
    state = await build_turn_state(db, session.id, chapter)
    _tm["decider"] = _time.perf_counter() - _tm["t0"]

    # 4-a. user 메시지 메타데이터 소급 기록 (ML 학습 데이터 구조화):
    #   - 진단 전 단계면 chapter 를 NULL 로 소급 변경 (라포 사담 분리)
    #   - turn_index: 세션 내 누적 user 턴 번호 (user/model 쌍 페어링 키)
    #   - instruction_used: 이 발화가 촉발한 instruction (학습 라벨)
    instruction_used = state.get("instruction_for_this_turn")
    # 6(2026-09-17) 담당 업무 답변 → session store participant_context {role_summary, team_size}.
    #   응답이 없거나 모호(≤3자·동의어만)하면 저장하지 않고 넘어간다. 스키마 변경 없이 JSONB store 에 둔다.
    if state.get("role_ask_pending") and (request.content or "").strip():
        from diag_project.services.instruction_decider import is_user_consent as _iuc
        _rt = request.content.strip()
        if len(_rt) > 3 and not _iuc(_rt):
            import re as _re_role
            _m = _re_role.search(r"(\d{1,4})\s*(명|인)", _rt)
            _pc_store = dict(session.self_assessment_data or {})
            _pc_store["participant_context"] = {
                "role_summary": _rt[:300],
                "team_size": int(_m.group(1)) if _m else None,
            }
            session.self_assessment_data = _pc_store
            from sqlalchemy.orm.attributes import flag_modified as _fm_pc
            _fm_pc(session, "self_assessment_data")
            await db.commit()
            state["participant_context"] = _pc_store["participant_context"]
            logger.info("🧩 participant_context 저장: team_size=%s role='%s'", _m.group(1) if _m else None, _rt[:40])
    PRE_DIAGNOSIS_INSTRUCTIONS = {
        "RAPPORT_BUILDING",
        "DIAGNOSIS_INTRO",
        "DIAGNOSIS_CONFIRM",
        "NAME_RECONFIRM",
        "SESSION_ABORT_WARNING",
        "SESSION_ABORT_3STRIKE",
    }

    # 🔒 T2 제어 역전(§0/§1-1): LLM 호출 '이전'에 다음 타겟 하위역량을 결정하고
    #   asked 원장(session.self_assessment_data)에 기록한다. 이 기록이 asked 의
    #   유일 소스이며, LLM 응답이 무엇이든 되돌리지 않는다. 그 타겟의 앵커를
    #   프롬프트에 주입(state["current_target_sub"]) → LLM 은 표현만.
    from diag_project.services.traversal import (
        apply_probe_turn, asked_for_chapter,
    )
    _PROBE_INSTR = {
        "CHAPTER_OPENING", "CONTINUE_NORMAL", "STAR_INCOMPLETE",
        "STAR_COMPLETE_NEW_EVENT", "CONTRARY_NEEDED", "ABSTRACT_AVOIDANCE",
        "AVOIDANCE_DETECTED", "ABSENCE_PROBE",
        # #2(2026-09-07): 정의 제시(ALIGN) 턴이 첫 앵커까지 한 메시지로 나간다.
        #   asked 기록은 여전히 LLM 호출 '이전'(이 스텝) — 합치는 것은 출력 조립만.
        "COMPETENCY_ALIGN",
    }
    current_target_sub = None
    _cur_before = None          # 프로브 스텝 '이전' 타겟(프로브 턴이 아니면 None 유지)
    # H5: LLM 호출 실패 시 이 턴의 원장 전진을 되돌리기 위한 스냅샷(프로브 턴만).
    _ledger_snapshot = None
    if chapter and instruction_used in _PROBE_INSTR:
        from diag_project.services.traversal import snapshot_ledger
        # 재개 테스트(T-E)와 동일한 순수 스텝을 공유한다 — 원장이 유일 소스.
        _store = dict(session.self_assessment_data or {})
        _ledger_snapshot = snapshot_ledger(_store)
        _all_subs = state.get("all_subcompetencies") or []
        # 4(2026-09-17) 부재 진술 2단: 직전 코치 턴이 폴백(ABSENCE_PROBE)이었는데도 또 부재 진술이면
        #   더 캐묻지 않고 이번 턴에 다음 하위역량으로 전진(현재 타겟 턴을 상한으로 올려 apply 가 전진하게).
        from diag_project.services.avoidance_detector import detect_absence_statement as _abs
        if (state.get("last_instruction") == "ABSENCE_PROBE" and _abs(request.content)
                and (_store.get("current_target") or {}).get(chapter)):
            from diag_project.services.traversal import MAX_TURNS_PER_SUB as _MAXT
            _store.setdefault("turns_on_target", {})[chapter] = _MAXT
            logger.info("🚫 부재 진술 2회(폴백 후) → [%s] 타겟 전진", chapter)
        _event_done = instruction_used == "STAR_COMPLETE_NEW_EVENT"
        # 🔑 타겟 전진 감지용: 스텝 '이전'의 현재 타겟(없으면 None=챕터 첫 앵커).
        _cur_before = (_store.get("current_target") or {}).get(chapter)
        _store, current_target_sub = apply_probe_turn(
            _store, chapter, _all_subs, _event_done, priority=[]
        )
        session.self_assessment_data = _store
        from sqlalchemy.orm.attributes import flag_modified as _flag_mod
        _flag_mod(session, "self_assessment_data")
        await db.commit()
        # 🔒 T2 기록=발화 결합(넓이 게이트 허수 방지): apply_probe_turn 이 '새'
        #   하위역량으로 타겟을 전진(record)시켰다면(=asked_subs 에 방금 1개 추가),
        #   그 턴의 instruction 을 앵커 발화형(STAR_COMPLETE_NEW_EVENT)으로
        #   오버라이드한다. 이렇게 해야 LLM 이 실제로 새 하위역량 앵커로 '피벗'해
        #   질문을 던지고, asked_subs 기록 수 == 실제 앵커 발화 지시 수가 된다.
        #   (기록 시점은 여전히 LLM 응답 '이전' — 텍스트 확인 방식으로 회귀 X.)
        #   · _cur_before is None → 챕터 첫 앵커(CHAPTER_OPENING 템플릿) → 유지.
        #   · 전진 조건은 apply_probe_turn 내부(STAR 완성 OR 3턴 상한). 상한 도달
        #     시엔 STAR 미완이어도 전진→피벗한다(넓이 > 깊이, 기존 결정 유지).
        #     3턴 이내엔 전진하지 않으므로 진행 중 STAR 를 끊지 않는다.
        from diag_project.services.traversal import advanced_to_new_target
        if (advanced_to_new_target(_cur_before, current_target_sub)
                and instruction_used != "STAR_COMPLETE_NEW_EVENT"):
            logger.info(
                "🧭 T2 타겟 전진 감지: [%s] %s→%s ⇒ instruction 오버라이드 "
                "%s→STAR_COMPLETE_NEW_EVENT (앵커 발화 강제)",
                chapter, _cur_before, current_target_sub, instruction_used,
            )
            instruction_used = "STAR_COMPLETE_NEW_EVENT"
            state["instruction_for_this_turn"] = "STAR_COMPLETE_NEW_EVENT"
        # 🎯 R 탐침 강제(2026-09-14): 이 하위역량의 마지막 프로브 턴(turns==상한)인데 아직
        #   결과(R)를 묻지 않았다면 이번 턴을 결과 탐침으로 고정한다. 3턴 상한은 그대로 —
        #   '묻지도 않고' 다음 앵커로 넘어가는 것만 막는다(답이 약해도 다음 턴엔 전진).
        #   앵커(전진) 턴·특수 처리(회피·부재 등) 턴은 대상이 아니다.
        from diag_project.services.traversal import needs_result_probe
        _target_advanced_now = (
            _cur_before is None
            or advanced_to_new_target(_cur_before, current_target_sub)
        )
        # 2026-09-17: decider 가 STAR 완결(LLM 자기보고)로 새 사건을 청하려 했지만 result_probed=False 라
        #   원장이 전진을 막은 턴 → 새 사건 대신 현재 사건의 결과(R)를 묻는다(깊이 유지).
        from diag_project.services.traversal import result_probed as _rp
        if (instruction_used == "STAR_COMPLETE_NEW_EVENT" and not _target_advanced_now
                and current_target_sub and not _rp(session.self_assessment_data, chapter)):
            logger.info("🧭 조기 전진 차단: [%s] target=%s STAR 완결 보고됐으나 result_probed=False → R 탐침",
                        chapter, current_target_sub)
            instruction_used = "STAR_INCOMPLETE"
            state["instruction_for_this_turn"] = "STAR_INCOMPLETE"
            state["force_result_probe"] = True
        _force_r = (
            not _target_advanced_now
            and instruction_used in ("CONTINUE_NORMAL", "CONTRARY_NEEDED", "STAR_INCOMPLETE")
            and needs_result_probe(session.self_assessment_data, chapter)
        ) or bool(state.get("force_result_probe"))
        state["force_result_probe"] = _force_r
        if _force_r and chapter:
            from diag_project.services.traversal import pick_result_probe as _pick_rp
            _rp_text, _st_rp2 = _pick_rp(session.self_assessment_data, chapter)
            session.self_assessment_data = _st_rp2
            from sqlalchemy.orm.attributes import flag_modified as _fm_rp2
            _fm_rp2(session, "self_assessment_data")
            state["result_probe_text"] = _rp_text
        if _force_r and instruction_used != "STAR_INCOMPLETE":
            logger.info(
                "🎯 R 탐침 강제: [%s] target=%s turns=%d instr %s→STAR_INCOMPLETE",
                chapter, current_target_sub,
                (session.self_assessment_data.get("turns_on_target") or {}).get(chapter, 0),
                instruction_used,
            )
            instruction_used = "STAR_INCOMPLETE"
            state["instruction_for_this_turn"] = "STAR_INCOMPLETE"
        logger.info(
            "🧭 T2 타겟: [%s] target=%s asked=%d turns=%d instr=%s force_R=%s",
            chapter, current_target_sub,
            len(asked_for_chapter(session.self_assessment_data, chapter)),
            (session.self_assessment_data.get("turns_on_target") or {}).get(chapter, 0),
            instruction_used, _force_r,
        )
    # (2026-09-21) 교정·재생성과 무관하게 모든 코치 턴은 turns_on_target 에 세어진다 — 프로브 집합 밖 턴
    #   (META_QUESTION_FROM_USER 등)은 전진 없이 턴 수만 +1.
    if chapter and instruction_used not in _PROBE_INSTR and instruction_used in (
            "META_QUESTION_FROM_USER", "DUPLICATE_SUSPECTED", "CROSS_CHAPTER_OPPORTUNITY"):
        from diag_project.services.traversal import bump_turns_only
        _st_b, _cur_b = bump_turns_only(session.self_assessment_data, chapter)
        if _cur_b:
            session.self_assessment_data = _st_b
            from sqlalchemy.orm.attributes import flag_modified as _fm_b
            _fm_b(session, "self_assessment_data")
            await db.commit()
            current_target_sub = _cur_b
    state["current_target_sub"] = current_target_sub
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
    # 페르소나 통합 system prompt — 사용자가 '선택한' 코치(session.coach_id) 기준.
    coach_key = _coach_key_from_id(session.coach_id)
    # #6: 매 턴 Layer3 상단에도 페르소나를 상기시킨다(Layer1 끝의 3줄만으로는
    #   가이드 예시 문장의 균일한 톤에 묻혀 어느 코치든 같은 말투가 나왔다).
    _persona = COACHES_PERSONA.get(coach_key) or {}
    state["coach_persona"] = {
        "name": _persona.get("name", ""),
        "coaching_style": _persona.get("coaching_style", ""),
        "tags": _persona.get("tags", ""),
    }
    # (2026-09-18) 문체 제약을 프롬프트 꼬리(사용자 메시지 직전)로. FM_STYLE_TAIL=0 이면 기존 위치(A/B 측정용).
    import os as _os_st
    state["style_at_tail"] = _os_st.getenv("FM_STYLE_TAIL", "1") != "0"
    turn_state_text = format_turn_state_for_llm(state)
    if state["style_at_tail"]:
        from diag_project.prompts.phase3a.layer3_state import build_style_tail
        _style_tail = build_style_tail(state)
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
    _llm_error = False  # H5: LLM 호출 실패 턴 표식(원장 롤백 + LLM_ERROR 태깅)

    # 2(2026-09-16) 챕터 전환 팝업 대기 중 자유 텍스트: 안내만, 상태 무변경(시스템 템플릿).
    if instruction_used == "AWAIT_NEXT_CHAPTER_CHOICE":
        _nm = chapter_to_topic(chapter) if chapter else "다음"
        system_override_text = (
            f"위 버튼으로 다음 단계를 선택해 주세요. '다음 챕터로 이동'을 누르시면 "
            f"'{_nm}' 영역으로 이어갑니다. 잠시 쉬고 싶으시면 '잠시 쉴게요'라고 적어 주셔도 됩니다."
        )

    # 🚨 3-Strike 강제 종료 (Session Abort) — 최우선 처리.
    #   세션 전체 비생산 응답 누적 → 정중한 종료 멘트 출력 후 세션 영구 종료.
    #   (3회 카운팅은 철저히 백엔드 내부 처리 — 멘트에 '3회' 등 수치 노출 금지.)
    #   LLM 을 우회해 정해진 문구만 내보내고 다음 질문은 절대 생성하지 않는다.
    _is_aborted = (instruction_used == "SESSION_ABORT_3STRIKE")
    if _is_aborted:
        system_override_text = (
            "저는 현재 리더님께서 진단을 진행하실 준비가 필요하다고 생각됩니다. "
            "진단 준비가 되셨을 때 다시 접속해 주시기 바랍니다. "
            "그럼 진단은 여기서 종료하겠습니다."
        )

    # ⚠️ 최후 의향 확인(Warning) — 종료 직전 1회. 세션은 아직 종료하지 않는다.
    #   (경고 후에도 유효 답변 없이 억지 → 다음 턴에 SESSION_ABORT_3STRIKE)
    _is_warning = (not _is_aborted
                   and instruction_used == "SESSION_ABORT_WARNING")
    if _is_warning:
        # 재촉·시간불평("빨리 합시다")으로 촉발된 경고면 과제6 지정 문구로,
        # 그 외(남탓·비아냥)는 기본 경고 문구로 분기.
        if detect_rush(request.content):
            system_override_text = (
                "빠른 진행을 위해서는 구체적인 경험 말씀이 반드시 필요합니다. "
                "계속 회피하시면 진단을 강제 종료할 수밖에 없습니다."
            )
        else:
            system_override_text = (
                "리더님, 현재 진단에 온전히 집중하시기 어려운 상황인 것 "
                "같습니다. 계속 진행을 원하신다면 앞서 드린 질문에 대한 "
                "구체적인 경험을 나누어 주시고, 그렇지 않다면 오늘은 여기서 "
                "마무리하는 것이 좋겠습니다."
            )

    # 🙋 이름 재확인(Fallback) — 명확한 성함을 못 뽑았을 때 1회. 억지 호칭 금지.
    _is_name_reconfirm = (not _is_aborted and not _is_warning
                          and instruction_used == "NAME_RECONFIRM")
    if _is_name_reconfirm:
        system_override_text = (
            "제가 성함을 정확히 파악하지 못했습니다. 본격적으로 시작하기 전에, "
            "편하게 부를 호칭을 다시 한번 알려주시겠어요?"
        )

    # 🚦 A-3: 참여 이탈 중단 '확인' — 곧바로 끊지 않고 선택권을 준다.
    #   평가·판단 표현 절대 금지("사례를 못 하셨다"/"참여도" 등) — 대상자가
    #   자신이 부족해 끊긴 것으로 느끼면 재개율이 떨어진다. 고정 문구.
    _is_abort_confirm = (not _is_aborted and not _is_warning
                         and not _is_name_reconfirm
                         and instruction_used == "ABORT_CONFIRM")
    if _is_abort_confirm:
        system_override_text = (
            "오늘은 시간을 내기 어려우신 것 같네요. 여기서 저장해두고 편하실 때 "
            "이어서 진행하실까요? 아니면 조금 더 해보시겠어요? 편하신 쪽으로 "
            "말씀해 주세요."
        )
        _store_ac = dict(session.self_assessment_data or {})
        _store_ac["awaiting_abort_decision"] = True
        session.self_assessment_data = _store_ac
        from sqlalchemy.orm.attributes import flag_modified as _fm_ac
        _fm_ac(session, "self_assessment_data")
        await db.commit()

    # 🚦 A-4: 참여 이탈 중단 '확정' — 리포트 파이프라인을 아예 호출하지 않는다.
    #   원장(asked/evidence/measured/current_target/turns)은 전부 보존(일시정지).
    _is_abort_disengaged = (not _is_aborted and not _is_warning
                            and not _is_name_reconfirm and not _is_abort_confirm
                            and instruction_used == "ABORT_DISENGAGED")
    if _is_abort_disengaged:
        system_override_text = (
            "네, 오늘은 여기까지 하고 편하실 때 이어서 진행하겠습니다. 지금까지 "
            "나눠주신 내용은 안전하게 저장해두었으니 다음에 이어서 계속하실 수 "
            "있습니다. 시간 내주셔서 감사합니다."
        )
        session.status = "aborted_disengaged"
        _store_ad = dict(session.self_assessment_data or {})
        _store_ad["pending_abort"] = False
        _store_ad["awaiting_abort_decision"] = False
        session.self_assessment_data = _store_ad
        from sqlalchemy.orm.attributes import flag_modified as _fm_ad
        _fm_ad(session, "self_assessment_data")
        await db.commit()

    if (not _is_aborted and not _is_warning and not _is_name_reconfirm
            and instruction_used == "RAPPORT_BUILDING"
            and state.get("rapport_turn_count", 0) == 0):
        # 라포 1턴 (이름 받은 직후) — Step1 이름수용 + Step2 아이스브레이킹.
        # 자기소개 반복 절대 금지 (인사말에서 이미 함). 템플릿으로 고정.
        # 사용자의 이번 답변에 비아냥·불만·거부가 있으면 차분한 톤으로 분기.
        _hostile = detect_deflection(request.content)
        system_override_text = build_rapport_first_turn_response(
            user_name=user_name,
            current_ampm_phrase=state.get("current_ampm_phrase", "오늘"),
            is_hostile=_hostile,
        )
    elif (not _is_aborted and not _is_warning and not _is_name_reconfirm
            and instruction_used == "RAPPORT_BUILDING"
            and state.get("rapport_turn_count", 0) == 1):
        # 6(2026-09-17) 라포 2턴 — 담당 업무 질문(템플릿). 답변은 다음 턴에 participant_context 로 저장.
        _ack = "그러시군요. " if not detect_deflection(request.content) else "네, 리더님. "
        system_override_text = (
            f"{_ack}어떤 일을 맡고 계신지도 간단히 알려주시겠어요? "
            "팀 규모나 주로 하시는 업무 정도면 됩니다."
        )
    elif instruction_used == "CHAPTER_OPENING":
        # 챕터 도입 — 첫 BEI 앵커 질문. item4: LLM 대신 백엔드 '템플릿 풀'로
        #   문장 틀을 챕터마다 다르게 골라(무반복·결정론) '시점+인물+행동·은유금지'
        #   앵커 품질을 구조적으로 보장한다. 앵커 내용(타겟 하위역량)은 주입,
        #   틀만 변주 → 제어 역전 유지. 브릿지(직전 사건 요약)로 대화 연결.
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
        _l0 = _time.perf_counter()
        llm_output = await llm.generate_phase3a_interaction(
            system_prompt=system_prompt,
            chapter_context=chapter_context,
            turn_state_text=turn_state_text,
            compressed_history=compressed_history,
            user_message=request.content,
            light_mode=(instruction_used in _LIGHT_MODE_INSTRUCTIONS),
            tail_block=_style_tail,
        )
        _tm["llm"] = _time.perf_counter() - _l0
        reply = llm_output["reply"]
        llm_state = {}          # (2026-09-22) 자기보고 JSON 폐기 — 항상 빈 dict
        event_metadata = None
        # H5: LLM 호출 실패 → 사과 폴백만 나가고 앵커는 발화되지 않았다. 이 턴의
        #   asked 원장 전진(apply_probe_turn)을 스냅샷으로 되돌려 '기록=발화'
        #   결합을 유지한다(넓이 게이트 허수 방지). 참여이탈 카운터 등 다른 키는
        #   그대로. 시스템 사실(호출 실패)에만 반응 — 텍스트 검증 방식 아님.
        if llm_output.get("error"):
            _llm_error = True
            if _ledger_snapshot is not None:
                from diag_project.services.traversal import restore_ledger
                from sqlalchemy.orm.attributes import flag_modified as _fm_rb
                session.self_assessment_data = restore_ledger(
                    session.self_assessment_data, _ledger_snapshot
                )
                _fm_rb(session, "self_assessment_data")
                logger.warning(
                    "↩️ H5 LLM 실패 → asked 원장 롤백: [%s] target=%s instr=%s",
                    chapter, current_target_sub, instruction_used,
                )
            user_msg.instruction_used = "LLM_ERROR"
            db.add(user_msg)
            await db.commit()

    # 8. 제어 태그 처리 (감사 위험 #4 해결)
    is_chapter_completed = "[CHAPTER_COMPLETE]" in reply
    is_session_paused = "[SESSION_PAUSE]" in reply
    # (2026-09-22) READY_FOR_INTRO·START_CHAPTER·SUGGEST_PAUSE 는 LLM 마커가 아니라 백엔드가 결정한다
    #   (코드 리뷰 2-d #8). 마커가 와도 무시하지 않고 OR 로 받되, 프롬프트는 더 이상 마커를 요구하지 않는다.
    is_ready_for_intro = ("[READY_FOR_INTRO]" in reply
                          or (instruction_used == "RAPPORT_BUILDING" and bool(state.get("force_ready_for_intro"))))
    is_chapter_starting = "[START_CHAPTER]" in reply or instruction_used == "DIAGNOSIS_CONFIRM"
    is_diagnosis_complete = "[DIAGNOSIS_COMPLETE]" in reply
    # Core Rule 7/9: 코치가 능동적으로 세션을 중단하는 조기 종료 마커
    # (극심한 스트레스·거부감, 동문서답 3진 아웃). 일시중지로 처리해
    # 사용자가 준비되면 이어서 재개할 수 있게 한다.
    is_session_end_early = "[SESSION_END_EARLY]" in reply
    # Core Rule 7: 조기 종료 '제안' 마커 — 프론트가 '다음에 하기/계속
    # 진행하기' 버튼을 띄우도록 needs_user_decision 플래그로 변환된다.
    # 일시중지 제안: 한 자리 경과 시간·턴 수 기준(event_tracker.should_suggest_pause). LLM 은 제안하지 않는다.
    from diag_project.services.event_tracker import should_suggest_pause as _ssp, sitting_stats as _sst
    _sit_elapsed, _sit_n = _sst([m.created_at for m in history_messages if m.created_at], now=datetime.utcnow())
    _last_sp_idx = max((i for i, m in enumerate(history_messages)
                        if m.probe_type_used == "SUGGEST_PAUSE"), default=None)
    _turns_since_sp = (len(history_messages) - 1 - _last_sp_idx) // 2 if _last_sp_idx is not None else None
    _backend_pause_suggested = (system_override_text is None and not _llm_error and _ssp(
        elapsed_min=_sit_elapsed, sitting_messages=_sit_n,
        suggest_pause_count=state.get("suggest_pause_count", 0),
        turns_since_last_suggest=_turns_since_sp, instruction_used=instruction_used,
    ))
    is_suggest_pause = "[SUGGEST_PAUSE]" in reply or _backend_pause_suggested

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
        # 진단 전 단계에서도 극심한 스트레스 호소는 발생한다 — 실전 검증에서
        # 감정 호소자가 CONFIRM 단계에 갇힌 채 코치의 종료 선언이 8회나
        # 차단됐던 사례의 재발 방지.
        "DIAGNOSIS_INTRO", "DIAGNOSIS_CONFIRM", "COMPETENCY_ALIGN",
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

    # [SUGGEST_PAUSE] 처리 (Core Rule 7 — 제안 vs 강제 분리):
    #   - 제안이 유효하면 needs_user_decision=True → 프론트가
    #     '다음에 하기/계속 진행하기' 버튼을 띄운다. 세션 상태는 그대로.
    #   - 2-Strike: 이미 2회 제안했다면 3번째 '제안'은 백엔드가 강제 종료로
    #     '승격'한다 — 프롬프트가 한도를 어겨도 시스템이 결정론적으로 보장.
    needs_user_decision = False
    _escalated_forced_end = False
    if is_suggest_pause:
        if is_session_end_early:
            # 두 마커가 함께 오면 강제 종료가 우선
            is_suggest_pause = False
        elif instruction_used not in _EARLY_END_ALLOWED:
            logger.warning(
                "⛔ 환각 차단: instruction=%s 턴에서 [SUGGEST_PAUSE] "
                "감지 → 무시.", instruction_used,
            )
            is_suggest_pause = False
        elif state.get("suggest_pause_count", 0) >= 2:
            logger.info(
                "🛑 2-Strike 소진(제안 %d회) → 3번째 제안을 강제 종료로 승격.",
                state.get("suggest_pause_count", 0),
            )
            is_suggest_pause = False
            is_session_end_early = True
            is_session_paused = True
            is_chapter_completed = False
            is_chapter_starting = False
            is_diagnosis_complete = False
            _escalated_forced_end = True
        else:
            needs_user_decision = True

    # 시스템 제어 마커 완벽 제거 — 고정 목록 replace 는 [EVENT_COMPLETE] 같은
    # 목록 밖 마커가 새어 나가므로, '[대문자_언더바]' 패턴 전체를 정규식으로
    # 스트립한다. (상태 전진용 파싱은 위에서 원본 reply 로 이미 완료됨)
    clean_reply = _MARKER_RE.sub("", reply).strip()
    # 개행 정규화: 정규식 파서가 못 푼 '\n' 리터럴이 프론트에 노출되는 버그 방지.
    # (json.loads 로 이미 풀린 경우엔 리터럴이 없어 무해)
    clean_reply = (
        clean_reply.replace("\\n", "\n").replace('\\"', '"').replace("\\t", "\t")
    )

    # 2-Strike 승격 턴: LLM 이 '제안'형 문장을 썼지만 시스템이 강제 종료로
    # 승격했으므로, 어색하지 않게 단호한 마무리 선언을 시스템이 덧붙인다.
    if _escalated_forced_end:
        clean_reply = (
            f"{clean_reply}\n\n"
            "리더님, 오늘은 여기서 마무리하는 것이 좋겠습니다. 지금은 진단보다 "
            "마음을 돌보는 시간이 더 필요해 보여요. 세션은 잘 정리해 둘 테니, "
            "마음이 회복되셨을 때 언제든 이어서 진행하실 수 있습니다."
        )

    # 일시중지 확정: USER_REQUESTS_PAUSE 면 LLM 의 [SESSION_PAUSE] 마커 누락과
    # 무관하게 무조건 일시중지 처리 (챕터 전환 차단 + 세션 대기 전환).
    if instruction_used == "USER_REQUESTS_PAUSE":
        is_session_paused = True

    # 🛡️ 문맥 붕괴 방지: 코치가 감정 대응/휴식 제안/조기 종료를 하는 턴에는
    #   진단 안내·역량 정의·억지 동의 같은 '기계적 하이브리드 텍스트'를 절대
    #   붙이지 않는다. (예: 휴식 제안 직후 "저희 진단에서는 조직관리를 …라고
    #   정의합니다. 자연스럽게 녹아들죠?" 가 이어붙던 문맥 붕괴 차단.)
    #   → 감정 대응/종료 제안 멘트가 온전히 응답이 되도록 LLM 원문만 남긴다.
    _suppress_mechanical_text = (
        is_session_end_early or needs_user_decision or is_session_paused
    )

    # 8-a. DIAGNOSIS_INTRO 하이브리드: LLM 호응 + 시스템 진단 안내 본문 합치기
    if instruction_used == "DIAGNOSIS_INTRO" and not _suppress_mechanical_text:
        llm_acknowledgment = clean_reply
        # 후처리 #1: 빈 응답일 때만 폴백. 과거의 '"죄송합니다" 포함' 조건은
        #   사과가 들어간 정상 응답(META 가이드가 권장)까지 통째로 날렸다.
        if not llm_acknowledgment.strip():
            llm_acknowledgment = "말씀 감사합니다."
        anchor_section = build_intro_anchor_section()
        clean_reply = f"{llm_acknowledgment}\n\n{anchor_section}"

    # 8-b. COMPETENCY_ALIGN — 과제2: 하드코딩 'framework 목록' 강제 병합 폐지.
    #   정의·하위역량을 프롬프트 변수로 주입(layer3)하고 LLM 이 대화체로
    #   전체 응답을 생성하므로, 시스템이 목록을 뒤에 붙이지 않는다.
    #   (LLM 이 빈 응답/사과만 낸 극단적 경우에만 최소 폴백.)
    if instruction_used == "COMPETENCY_ALIGN" and not _suppress_mechanical_text:
        # 후처리 #2: 빈 응답일 때만 폴백('"죄송합니다" 포함' 조건 제거 — 사과가
        #   들어간 정상 응답은 그대로 통과).
        if not clean_reply.strip():
            _fw = COMPETENCY_FRAMEWORK.get(chapter, {})
            _nm = _fw.get("name", "이 영역")
            clean_reply = (
                f"네, 리더님 말씀 잘 들었습니다. 그 결을 이어서 '{_nm}' "
                f"경험을 조금 더 구체적으로 들여다볼게요."
            )
        # #2(2026-09-07): 정의 제시 → 빈 줄 → 첫 앵커 질문을 한 메시지로. "들어가
        #   볼까요?" → "네" 확인 턴(정보 없음) 제거. 타겟(asked)은 위 프로브 스텝에서
        #   LLM 호출 이전에 기록됐고, 여기서는 출력만 조립한다. 브릿지 리드 없이
        #   앵커 본문만 붙인다(정의 뒤라 리드가 어색).
        if chapter and current_target_sub:
            # 1(2026-09-16) ALIGN 이중 질문: LLM 이 정의 제시를 자기 질문으로 끝내면 그 문장을
            #   지우고 템플릿 앵커만 질문으로 남긴다(최종 출력의 물음표는 앵커 하나).
            from diag_project.services.output_guard import strip_trailing_question
            clean_reply, _n_tail = strip_trailing_question(clean_reply)
            if _n_tail:
                logger.info("✂️ ALIGN 꼬리 질문 %d문장 제거 후 앵커 결합", _n_tail)
            _anchor = build_chapter_opening_with_user_def(
                chapter=chapter,
                user_definition=request.content or "",
                first_subcompetency_name=current_target_sub,
                bridge_context=None,
            )
            clean_reply = f"{clean_reply.rstrip()}\n\n{_anchor}"
            # 다음 턴 decider 가 CHAPTER_OPENING 을 다시 내지 않도록 원장에 표식.
            _st_om = dict(session.self_assessment_data or {})
            _om = dict(_st_om.get("opening_merged") or {})
            _om[chapter] = True
            _st_om["opening_merged"] = _om
            session.self_assessment_data = _st_om
            from sqlalchemy.orm.attributes import flag_modified as _fm_om
            _fm_om(session, "self_assessment_data")
            await db.commit()

    # 8-c. CHAPTER_OPENING 은 Step 7 에서 시스템이 전체 출력 (하이브리드 폐지).
    # build_chapter_opening_with_user_def 가 정의 + 첫 BEI 질문까지 포함하므로
    # 별도 후처리 불필요.

    _next_ch = _get_next_chapter(chapter)

    # 8-d. CHAPTER_READY_TO_END 하이브리드 (종결 + 강제 전환):
    #   중간 챕터: LLM 이 wrap-up(요약+공감) + '강제 전환 선언 + 다음 역량 첫
    #   질문'을 생성한다. 사용자에게 계속/휴식을 묻지 않고(선택권 이양 금지),
    #   코치가 주도권을 쥐고 즉시 다음 챕터로 전환한다.
    #   → CHAPTER_CONTINUE_CONFIRMED 와 동일하게 완료·시작 마커를 세운다.
    if instruction_used == "CHAPTER_READY_TO_END":
        # 1-b: 내부 종료 사유는 로그에만 남긴다(리더에게 나가는 문구는 중립).
        logger.info(
            "🏁 챕터 종료 [%s] no_yield_forced=%s star70=%s avoid=%s asked=%s "
            "turns_on_target=%s ultimatum=%s turn_count=%s",
            chapter, state.get("no_yield_forced"),
            state.get("events_with_star_70"),
            state.get("avoidance_count_in_chapter"),
            len(state.get("asked_in_chapter") or []),
            state.get("turns_on_current_target"),
            state.get("no_yield_ultimatum_given"), state.get("turn_count"),
        )
        # 5(2026-09-17) 마무리 총평 금지: LLM 문장을 쓰지 않고 고정 문구만.
        wrap_up = (
            f"여기까지 충분히 들었습니다. 이제 '{chapter_to_topic(_next_ch)}'로 이어가 보겠습니다."
            if _next_ch else "여기까지 충분히 들었습니다. 이제 진단을 마무리하겠습니다."
        )
        if _next_ch:
            # 전환 '예고'까지만. 다음 역량의 정의 질문(COMPETENCY_ASK)은 리더님이
            # 팝업으로 확인한 뒤 다음 턴의 첫 발화가 된다. (과거엔 '?' 가 없으면
            # 시스템이 build_chapter_thought_question 을 덧붙여 "'성과관리'을
            # 챙긴다는 건…" 같은 조사 오류 질문이 예고 뒤에 붙었고, 정의 질문이
            # 두 번 나가는 순서 어긋남을 만들었다.)
            clean_reply = wrap_up
            # ✅ 즉시 전환: 완료·시작 마커를 세워 다음 챕터로 견인 (대기 없음).
            is_chapter_completed = True
            is_chapter_starting = True
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
        # 브릿지 한 문장만. 다음 역량의 정의 질문은 다음 턴 COMPETENCY_ASK 가
        # 첫 발화로 던진다(시스템 템플릿 질문 덧붙임 폐지 — 조사 오류·중복 질문).
        is_chapter_completed = True
        is_chapter_starting = True

    # 8-f. 🦜 앵무새 방어: 직전 AI 멘트와 '동일한' 응답이 또 생성되면
    #   (상태 정체 + 사용자 '네' 단답 시 같은 요약을 반복하는 병목),
    #   반복 대신 대화를 앞으로 미는 진행 유도 질문으로 교체한다.
    if system_override_text is None and clean_reply:
        _last_model_q = await db.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session.id)
            .where(ChatMessage.role == MessageRole.MODEL)
            .order_by(ChatMessage.created_at.desc())
            .limit(1)
        )
        _last_model_msg = _last_model_q.scalars().first()
        if (_last_model_msg
                and _last_model_msg.content
                and _last_model_msg.content.strip() == clean_reply.strip()):
            # 후처리 #5(개정): 고정 3문장 교체 폐지 — 그 문장들은 전부 "네,/좋습니다,"
            #   로 시작하고 현재 타겟 앵커·문체 제약을 우회했다. 대신 '직전과 같은
            #   응답 금지 + 현재 타겟 질문' 제약을 붙여 LLM 재생성 1회. 재생성도
            #   동일하면 그때만 폴백(현재 타겟 질문 1개, 없으면 판단 기준 질문).
            logger.warning("🦜 동일 응답 반복 감지 → 제약 추가 후 LLM 재생성 1회")
            from diag_project.data.competencies import (
                find_sub_key_by_name, get_anchor_questions,
            )
            _tq = []
            if chapter and current_target_sub:
                _k = find_sub_key_by_name(chapter, current_target_sub)
                _tq = get_anchor_questions(_k) if _k else []
            _retry_note = (
                "\n\n🚨 [시스템 — 재생성 지시] 방금 만든 응답이 직전 코치 발화와 "
                "완전히 동일합니다. 같은 문장을 다시 쓰지 마세요. 요약 되받기 없이, "
                "'네,'로 시작하지 말고, 바로 새로운 질문 하나로 대화를 앞으로 미세요."
                + (
                    "\n이번 질문 본문(하위역량 이름 언급 금지): "
                    + " / ".join(_tq)
                    if _tq else ""
                )
            )
            _regen: dict = {}
            try:
                _regen = await _timed_regen(
                    system_prompt=system_prompt,
                    chapter_context=chapter_context,
                    turn_state_text=turn_state_text + _retry_note,
                    compressed_history=compressed_history,
                    user_message=request.content,
                    light_mode=True,  # 문장만 필요(state 는 1차 응답 것 유지)
                )
                _regen_reply = _MARKER_RE.sub("", _regen.get("reply") or "").strip()
            except Exception as _e:  # 재생성 실패는 폴백으로
                logger.error("🦜 재생성 실패: %s", _e)
                _regen_reply = ""
            if (_regen_reply and not _regen.get("error")
                    and _regen_reply != clean_reply.strip()):
                clean_reply = _regen_reply
            else:
                logger.warning("🦜 재생성도 동일/실패 → 폴백 질문")
                clean_reply = (
                    _tq[0] if _tq else
                    "그 상황에서 리더님이 내리신 판단의 기준이 궁금한데요 — "
                    "어떤 기준이었어요?"
                )

    # 8-g. 최종 안전망: 하이브리드 조립 이후에도 남아있을 수 있는 시스템
    #   마커를 프론트 전달 직전에 한 번 더 완벽 제거.
    clean_reply = _MARKER_RE.sub("", clean_reply).strip()

    # 8-i. 통합 출력 가드(2026-09-16 도입, 09-18 C 모드, 09-21 질문·연결 절 보존 보강) — LLM 턴만.
    #   위반 감지 → [names·off_target·no_question] 만 재생성 1회 → 남은 위반은 하드 교정(문장 단위).
    #   하드 교정의 두 가지 보장(사람관리 09-21 사고 — 교정이 연결 절·질문을 잘라 턴이 깨졌다):
    #     (1) 질문 보존: 어떤 교정도 질문을 없애지 않는다. 없애게 되면 그 교정을 건너뛰거나(칭찬·이름 구절)
    #         현재 타겟의 템플릿 앵커로 간다(전환 문장이 곧 질문인 경우).
    #     (2) 연결 절 보존: "방금 말씀하신 '인정'과도 이어지는데요" 가 든 문장은 되받기로 안 지운다(trim_lead_sentences).
    #   프로브 턴이 끝까지 질문 없이 남으면 결과 질문 풀이 아니라 현재 타겟 템플릿 앵커(연결 절 포함).
    #   부재 폴백 턴(ABSENCE_PROBE)·템플릿 턴은 가드 대상 아님. 모든 결과는 guard_log 에 남는다.
    #   후처리 단계 전체 표: docs/postprocess_pipeline.md — 프롬프트 규칙을 추가할 때 이 표와 대조한다.
    if system_override_text is None and not _llm_error and clean_reply and instruction_used != "ABSENCE_PROBE":
        from diag_project.services.output_guard import (
            TRANSITION_ALLOWED_INSTRUCTIONS, find_praise, find_sub_names, has_question, has_transition_claim,
            off_target_overlap, split_sentences, strip_praise, strip_sub_name_mentions,
            strip_transition_sentences, template_anchor_bridged, trim_lead_sentences, same_question_as_previous,
        )
        from diag_project.services.output_guard import is_question as is_question_sentence
        # _prev_coach_text / _recent_coach_texts 는 히스토리 로드 직후 계산됨(2026-09-22)

        def _anchor_fallback() -> str:
            """교정 폴백 문장: 현재 타겟 템플릿 앵커(연결 절). 그 앵커가 직전 2턴에 이미 나갔으면(리플레이 F 16·11턴 —
            폴백이 폴백을 반복) 결과 질문 풀에서 안 쓴 문장으로."""
            from diag_project.services.output_guard import norm_sentence as _ns_fb
            nonlocal session
            if _tgt_q and chapter and _ns_fb(_tgt_q) not in _ns_fb(" ".join(_recent_coach_texts)):
                return template_anchor_bridged(_tgt_q, request.content)
            if chapter:
                from diag_project.services.traversal import pick_result_probe as _prp_fb
                _q_fb, _st_fb = _prp_fb(session.self_assessment_data, chapter)
                session.self_assessment_data = _st_fb
                from sqlalchemy.orm.attributes import flag_modified as _fm_fb
                _fm_fb(session, "self_assessment_data")
                return template_anchor_bridged(_q_fb, request.content)
            return template_anchor_bridged(_tgt_q, request.content)
        from diag_project.data.competencies import (
            COMPETENCY_FRAMEWORK as _CF, find_sub_key_by_name as _fsk, get_anchor_questions as _gaq,
        )
        _sc = state.get("style_constraints") or {}
        # ALIGN(정의 제시+목록+앵커)·CHAPTER_OPENING 은 리드가 여러 문장인 것이 정상 — 되받기/리드 검사 제외.
        _is_probe = (instruction_used in _PROBE_INSTR
                     and instruction_used not in ("COMPETENCY_ALIGN", "CHAPTER_OPENING"))
        _is_anchor = instruction_used == "STAR_COMPLETE_NEW_EVENT"
        _all_names = [v.get("name") for c in _CF.values() for v in (c.get("indicators") or {}).values()]
        _asked_qs: list[str] = []
        _tgt_q = ""
        if chapter and current_target_sub:
            _kt = _fsk(chapter, current_target_sub)
            _tgt_q = (_gaq(_kt) or [""])[0] if _kt else ""
            if _is_anchor:
                for _nm2 in (state.get("asked_in_chapter") or []):
                    if _nm2 == current_target_sub:
                        continue
                    _k2 = _fsk(chapter, _nm2)
                    _asked_qs += (_gaq(_k2) if _k2 else [])

        def _violations(txt: str) -> dict:
            v: dict = {}
            pr = find_praise(txt)
            if pr:
                v["praise"] = pr
            if instruction_used not in TRANSITION_ALLOWED_INSTRUCTIONS and has_transition_claim(txt):
                v["transition"] = True
            if _is_anchor:
                nm = find_sub_names(txt, _all_names)
                if nm:
                    v["names"] = nm
                off, oq = off_target_overlap(txt, _asked_qs)
                if off:
                    v["off_target"] = oq
            elif _is_probe:
                nm = find_sub_names(txt, _all_names)
                if nm:
                    v["names_mention"] = nm
            if _is_probe:
                leads = []
                for _s2 in split_sentences(txt):
                    if is_question_sentence(_s2):
                        break
                    leads.append(_s2)
                if _sc.get("forbid_ne_opening") and txt.lstrip().startswith(("네,", "네.", "넵,", "예,")):
                    v["ne_opening"] = True
                # 되받기: 첫 리드가 요약 복창일 때만. 연결 절('말씀하신'+한 어절)은 is_recap_opening 이 걷어내고 판정.
                if _sc.get("forbid_recap") and leads and (
                        is_recap_turn(leads[0], request.content) or starts_with_ne_recap(leads[0])):
                    v["recap"] = True
                if len(leads) > 1:
                    v["lead_stack"] = len(leads)
                if not has_question(txt):
                    v["no_question"] = True
                _sq = same_question_as_previous(txt, _prev_coach_text)
                if _sq:
                    v["same_question"] = _sq[:60]
            return v

        _v = _violations(clean_reply)
        _tm["violations"] = dict(_v)
        # (2026-09-18 A/B 측정) recap·lead_stack·praise·transition·ne_opening 은 재생성해도 대부분 그대로 남는다
        #   (19턴 중 recap 12 → 재생성 후 11 잔존) → 재생성 없이 바로 교정. 재생성은 문장 교체가 어색한
        #   names·off_target 과, 출력 자체에 질문이 없는 no_question 에만. FM_REGEN_ALL=1 이면 전부 재생성(측정용).
        _REGEN_KEYS = {"names", "off_target", "no_question", "same_question"}
        import os as _os_rg
        _need_regen = bool(_v) and (bool(set(_v) & _REGEN_KEYS) or _os_rg.getenv("FM_REGEN_ALL") == "1")
        if _v and not _need_regen:
            logger.info("🛡️ 출력 가드 위반(재생성 생략, 하드 교정): %s (instr=%s)", _v, instruction_used)
        if _need_regen:
            logger.info("🛡️ 출력 가드 위반: %s (instr=%s) → 재생성 1회", _v, instruction_used)
            _notes = ["\n\n🚨 [시스템 — 재생성 지시] 방금 만든 응답에 다음 위반이 있습니다. 내용은 유지하되 고쳐 다시 쓰세요."]
            if "praise" in _v:
                _notes.append(f"- 평가적 칭찬 금지: {', '.join(_v['praise'])} 같은 표현을 빼세요. 인정은 사실 확인('그 결정을 내리셨군요')까지.")
            if "transition" in _v:
                _notes.append("- 이번 턴은 영역을 마치거나 다음 챕터로 넘어가는 턴이 아닙니다. 전환·마무리 선언 문장을 빼고 질문으로 이어가세요.")
            if "names" in _v or "off_target" in _v or "names_mention" in _v:
                _notes.append("- 하위역량 이름을 말하지 말고, 이미 다룬 사건·주제를 다시 묻지 마세요."
                              + (f" 이번 앵커 질문 본문: {_tgt_q}" if (_tgt_q and _is_anchor) else ""))
            if "ne_opening" in _v or "recap" in _v or "lead_stack" in _v:
                _notes.append("- 질문 앞의 리드는 한 문장뿐입니다. '네,'로 시작하지 말고, 요약 되받기가 금지된 턴이면 "
                              "연결 한 절(직전 발화의 단어 하나를 다음 질문의 이유로)로 시작하세요.")
            if "no_question" in _v:
                _notes.append("- 응답에 질문이 없습니다. 반드시 리더님께 묻는 질문 한 문장으로 끝내세요.")
            if "same_question" in _v:
                _notes.append("- 직전 턴과 같은 질문을 되묻고 있습니다. 리더님이 방금 답한 내용에서 한 걸음 더 들어가는 다른 질문을 하세요.")
            try:
                _g_regen = await _timed_regen(
                    system_prompt=system_prompt,
                    chapter_context=chapter_context,
                    turn_state_text=turn_state_text + "\n".join(_notes),
                    compressed_history=compressed_history,
                    user_message=request.content,
                    light_mode=True,
                )
                _g_reply = _MARKER_RE.sub("", _g_regen.get("reply") or "").strip()
            except Exception as _e:
                logger.error("🛡️ 출력 가드 재생성 실패: %s", _e)
                _g_reply = ""
            if _g_reply and not _g_regen.get("error"):
                _v2 = _violations(_g_reply)
                if len(_v2) < len(_v) or not _v2:
                    clean_reply = _g_reply
                    _v = _v2
        # 하드 교정(남은 위반) — 각 단계는 질문을 없애지 않는다.
        if _v:
            _tm["hard"] = True
            logger.info("🛡️ 출력 가드 하드 교정: %s", _v)
            if ("names" in _v or "off_target" in _v) and _tgt_q:
                clean_reply = _anchor_fallback()
                _v = {}
            if "same_question" in _v and chapter:
                # 재생성 후에도 직전 턴과 같은 질문 → 타겟 앵커(직전 2턴에 없을 때) 또는 결과 질문(풀)으로 한 걸음 전진.
                clean_reply = _anchor_fallback()
                logger.info("🛡️ 직전 턴과 같은 질문 → 교체: %s", clean_reply[:60])
            if "names_mention" in _v:
                _c2, _n = strip_sub_name_mentions(clean_reply, _all_names)
                if has_question(_c2) or not has_question(clean_reply):
                    clean_reply = _c2
            if "praise" in _v:
                _c2, _n = strip_praise(clean_reply)   # 마지막 질문 문장은 보존하는 함수
                if has_question(_c2) or not has_question(clean_reply):
                    clean_reply = _c2
            if "transition" in _v:
                _c2, _n = strip_transition_sentences(clean_reply)
                if has_question(_c2) or not has_question(clean_reply) or not _is_probe:
                    clean_reply = _c2
                elif _tgt_q:
                    # 전환 선언이 곧 질문("다음으로 넘어가도 될까요?")인 프로브 턴 → 현재 타겟 앵커
                    clean_reply = _anchor_fallback()
            if _is_probe and ("recap" in _v or "ne_opening" in _v or "lead_stack" in _v):
                # 첫 질문 이후는 건드리지 않고, 연결 절 리드는 지우지 않는다. 리드가 다 지워지면 연결 절 템플릿을 앞에 붙인다.
                clean_reply, _n = trim_lead_sentences(
                    clean_reply, bool(_sc.get("forbid_recap")), request.content,
                    forbid_ne=bool(_sc.get("forbid_ne_opening")),
                )
            # 최종 보장: 프로브 턴에 질문이 없으면 현재 타겟 템플릿 앵커(결과 질문 풀 대체는 폐기 — 같은 문장 반복 사고).
            if _is_probe and not has_question(clean_reply.strip()) and _tgt_q:
                clean_reply = _anchor_fallback()
                logger.info("🛡️ 질문 없는 출력 → 현재 타겟 템플릿 앵커(직전 2턴에 있으면 결과 질문)")

        # 3(2026-09-17) Result 탐침 문장 변주: 상투형('그렇게 하니 어떻게 됐습니까') 또는 이 챕터에서 이미 쓴
        #   결과 질문과 같은 문장이면 풀에서 안 쓴 문장으로 교체(직전 2턴 제외).
        if chapter and _is_probe:
            from diag_project.services.output_guard import find_repeated_result_probe
            from diag_project.services.traversal import pick_result_probe, used_result_probes
            _dup = find_repeated_result_probe(clean_reply, used_result_probes(session.self_assessment_data, chapter))
            if _dup:
                _new_q, _st_rp = pick_result_probe(session.self_assessment_data, chapter)
                clean_reply = clean_reply.replace(_dup, _new_q, 1)
                session.self_assessment_data = _st_rp
                from sqlalchemy.orm.attributes import flag_modified as _fm_rp
                _fm_rp(session, "self_assessment_data")
                logger.info("🔁 결과 질문 반복 교체: '%s' → '%s'", _dup[:40], _new_q)

    # 5(2026-09-21) 문법: '있으시겠습니까' 는 미래·청유형 오용 → '있으셨습니까'
    if clean_reply:
        clean_reply = clean_reply.replace("있으시겠습니까", "있으셨습니까").replace("있으시겠어요", "있으셨어요")

    # 8-h. 느낌표 상한(2026-09-15): 페르소나별 상한(Michael 1·안내턴 0, 나머지 0)을 백엔드가 센다.
    #   초과 → 재생성 1회(같은 프롬프트 + 상한 지시) → 그래도 초과면 초과분을 마침표로 치환.
    #   시스템 템플릿 턴(system_override_text)은 재생성 없이 치환만(공용 템플릿의 '!' 가
    #   상한 0 인 코치에게 나가지 않게).
    if not _llm_error:
        from diag_project.services.style_tracker import (
            count_exclamations, enforce_exclamation_cap, exclamation_cap,
        )
        _ex_cap = exclamation_cap(
            (state.get("coach_persona") or {}).get("name"), instruction_used
        )
        _ex_n = count_exclamations(clean_reply)
        if _ex_n > _ex_cap and system_override_text is not None:
            clean_reply, _ = enforce_exclamation_cap(clean_reply, _ex_cap)
            logger.info("❗ 템플릿 턴 느낌표 치환: %d → %d (instr=%s)",
                        _ex_n, count_exclamations(clean_reply), instruction_used)
        elif _ex_n > _ex_cap:
            logger.info("❗ 느낌표 초과: %d > 상한 %d (instr=%s) → 재생성 1회",
                        _ex_n, _ex_cap, instruction_used)
            _ex_note = (
                f"\n\n🚨 [시스템 — 재생성 지시] 방금 만든 응답에 느낌표(!)가 {_ex_n}개였습니다. "
                f"이번 응답은 느낌표 **최대 {_ex_cap}개**로, 내용·질문은 그대로 두고 문장 종결만 "
                "마침표로 바꿔 다시 쓰세요. 에너지는 단어로 냅니다."
            )
            try:
                _ex_regen = await _timed_regen(
                    system_prompt=system_prompt,
                    chapter_context=chapter_context,
                    turn_state_text=turn_state_text + _ex_note,
                    compressed_history=compressed_history,
                    user_message=request.content,
                    light_mode=True,
                )
                _ex_reply = _MARKER_RE.sub("", _ex_regen.get("reply") or "").strip()
            except Exception as _e:
                logger.error("❗ 느낌표 재생성 실패: %s", _e)
                _ex_reply = ""
            if _ex_reply and count_exclamations(_ex_reply) <= _ex_cap:
                clean_reply = _ex_reply
            else:
                _src = _ex_reply if (_ex_reply and count_exclamations(_ex_reply) < _ex_n) else clean_reply
                clean_reply, _before = enforce_exclamation_cap(_src, _ex_cap)
                logger.info("❗ 느낌표 치환: %d → %d", _before, count_exclamations(clean_reply))

    if needs_user_decision and _backend_pause_suggested and clean_reply:
        clean_reply = (
            f"{clean_reply.rstrip()}\n\n"
            f"리더님, 한 자리에서 {int(_sit_elapsed)}분째 이어오고 있습니다. 오늘은 여기서 잠시 쉬어가셔도 괜찮습니다. "
            "이어가실지, 다음에 하실지 골라 주세요."
        )

    # 9. 사건 생명주기 처리 + AI 메시지 저장
    #   (2026-09-22) 탐침 종류는 LLM 자기보고가 아니라 instruction·문장 표지로(event_tracker.probe_type_for).
    from diag_project.services.event_tracker import probe_type_for as _ptf
    probe_type_used = None if system_override_text is not None else _ptf(instruction_used, clean_reply)

    # 사용자가 '계속' 동의(CHAPTER_CONTINUE_CONFIRMED)했을 때만 다음 챕터를
    # '시작됨'으로 표시해, 중간 CONFIRM 턴 없이 바로 다음 영역 합의(ALIGN)로
    # 이어지게 한다. (CHAPTER_READY_TO_END 는 이제 전환하지 않고 대기만 한다.)
    _seamless_next_chapter = None
    if (instruction_used in ("CHAPTER_CONTINUE_CONFIRMED", "CHAPTER_READY_TO_END")
            and is_chapter_completed and is_chapter_starting):
        # CHAPTER_READY_TO_END(중간 챕터)도 이제 대기 없이 강제 전환하므로
        # CONTINUE_CONFIRMED 와 동일하게 다음 챕터를 seamless 로 이어붙인다.
        _seamless_next_chapter = _get_next_chapter(chapter)

    # 마커 → probe_type_used 에 저장 (우선순위: READY_FOR_INTRO > START_CHAPTER)
    if instruction_used == "RAPPORT_BUILDING" and is_ready_for_intro:
        probe_type_used = "READY_FOR_INTRO"
    elif instruction_used == "DIAGNOSIS_CONFIRM" and is_chapter_starting:
        probe_type_used = "START_CHAPTER"
    elif _seamless_next_chapter:
        probe_type_used = "START_CHAPTER"
    elif needs_user_decision:
        # 조기 종료 '제안' 턴 — 2-Strike 카운팅과 /state 복원의 근거 마커.
        probe_type_used = "SUGGEST_PAUSE"
    elif instruction_used == "CHAPTER_NO_YIELD_ULTIMATUM":
        # 무수확 최후통첩 턴 — 다음 턴에 '이미 통첩함'을 판별하는 근거 마커.
        probe_type_used = "NO_YIELD_ULTIMATUM"
    elif _is_warning:
        # 최후 의향 확인(Warning) 턴 — 다음 턴에 '이미 경고함'을 판별해
        # 재경고 루프를 막고 곧바로 종료로 승격시키는 근거 마커.
        probe_type_used = "ABORT_WARNING"
    elif _is_name_reconfirm:
        # 이름 재확인 턴 — 다음 턴에 '이미 되물음'을 판별해 재질문을 막는 마커.
        probe_type_used = "NAME_RECONFIRM"
    elif (instruction_used == "RAPPORT_BUILDING" and system_override_text is not None
            and state.get("rapport_turn_count", 0) == 1):
        # 6(2026-09-17) 담당 업무 질문 턴 — 다음 턴에 답변을 participant_context 로 저장하는 근거 마커.
        probe_type_used = "ROLE_ASK"

    # 진단 전 단계는 사건 생명주기 스킵
    is_pre_diagnosis = (instruction_used in PRE_DIAGNOSIS_INSTRUCTIONS)
    if is_pre_diagnosis:
        real_event_id = None
    else:
        real_event_id = await _handle_event_lifecycle(
            db=db,
            session_id=session.id,
            chapter=chapter,
            user_message_text=request.content,
            instruction_used=instruction_used,
            prev_instruction=state.get("last_instruction"),
            prev_coach_text=_prev_coach_text,
            target_changed=bool(_cur_before is not None and current_target_sub
                                and advanced_to_new_target(_cur_before, current_target_sub)),
            mapped_target=(_cur_before or current_target_sub),
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

    # 🎯 R 탐침 기록(2026-09-14): 이 코치 턴이 결과를 물었으면(LLM 자기보고 MEASUREMENT
    #   또는 문장 표지) 현재 타겟의 result_probed=True. 앵커(전진) 턴·LLM 실패 턴은 제외
    #   (앵커 문장의 '결과' 표현이 새 타겟의 R 로 오기록되지 않게). 커밋은 아래 ai_msg 와 함께.
    if (chapter and not _llm_error and current_target_sub
            and instruction_used in _PROBE_INSTR
            and not (_cur_before is None
                     or advanced_to_new_target(_cur_before, current_target_sub))
            and (probe_type_used == "MEASUREMENT" or is_result_probe_text(clean_reply))):
        from diag_project.services.traversal import mark_result_probed
        from sqlalchemy.orm.attributes import flag_modified as _flag_mod_r
        session.self_assessment_data = mark_result_probed(
            session.self_assessment_data, chapter
        )
        _flag_mod_r(session, "self_assessment_data")
        logger.info("🎯 R 탐침 기록: [%s] target=%s probe_type=%s",
                    chapter, current_target_sub, probe_type_used)

    ai_msg = ChatMessage(
        session_id=session.id,
        role="model",
        content=clean_reply,
        chapter=ai_msg_chapter,
        event_id=None if is_pre_diagnosis else real_event_id,
        probe_type_used=probe_type_used,
        # H5: LLM 실패 턴은 LLM_ERROR 로 태깅 — 다음 턴의 참여이탈 카운팅
        #   (_BEI_PROBE_INSTR 기준)과 학습 라벨에서 '앵커 턴'으로 오인되지 않게.
        instruction_used=("LLM_ERROR" if _llm_error else instruction_used),
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

    # 11-c. 🚨 3-Strike 강제 종료: 세션 상태를 'aborted' 로 확정한다.
    #   재개 불가 — 완료도 일시중지도 아닌 '중단' 상태로 명확히 분리한다.
    if _is_aborted:
        session.status = "aborted"
        session.current_topic = "Aborted"
        db.add(session)
        await db.commit()
        logger.warning(
            "🛑 3-Strike Session Abort: session=%s (비생산 응답 %d회 누적)",
            session.id, state.get("session_deflection_count", 0),
        )

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
    # 2(2026-09-16): 전환 팝업 대기 안내 턴 — 프론트가 '다음 챕터로 이동' 배너를 다시 띄우도록
    #   is_topic_completed 를 True 로(챕터·원장은 그대로, completed_topics 도 그대로).
    if instruction_used == "AWAIT_NEXT_CHAPTER_CHOICE":
        is_chapter_completed = True
    _total = _time.perf_counter() - _tm["t0"]
    # (2026-09-18) 턴별 가드 결과를 세션 store 에 남긴다(Render 로그는 실세션 후 조회 불가). 최근 200턴만 유지.
    try:
        _gl_store = dict(session.self_assessment_data or {})
        _gl = list(_gl_store.get("guard_log") or [])[-199:]
        _gl.append({
            "t": _turn_index, "ch": chapter, "instr": instruction_used,
            "v": sorted((_tm.get("violations") or {}).keys()), "regen": _tm["regen_n"],
            "route": state.get("route_reason"),
            "hard": bool(_tm.get("hard")), "llm": round(_tm["llm"], 1), "total": round(_total, 1),
        })
        _gl_store["guard_log"] = _gl
        session.self_assessment_data = _gl_store
        from sqlalchemy.orm.attributes import flag_modified as _fm_gl
        _fm_gl(session, "self_assessment_data")
        await db.commit()
    except Exception as _e:
        logger.warning("guard_log 기록 실패: %s", _e)
    logger.info("⏱ turn timing session=%s instr=%s decider=%.2fs llm=%.2fs regen=%d(%.2fs) post+db=%.2fs total=%.2fs style_tail=%s",
                str(session.id)[:8], instruction_used, _tm["decider"], _tm["llm"], _tm["regen_n"], _tm["regen_s"],
                max(0.0, _total - _tm["decider"] - _tm["llm"] - _tm["regen_s"]), _total, state.get("style_at_tail"))
    return {
        "coach_response_message": clean_reply,
        "is_topic_completed": is_chapter_completed,
        "is_session_starting": False,
        "is_session_completed": is_session_completed,
        "is_session_paused": is_session_paused,
        # 🚨 3-Strike 강제 종료 — 프론트가 입력창을 영구 잠금해야 하는 신호.
        "is_terminated": _is_aborted,
        # 🚦 A: 참여 이탈 중단(재개 가능) — 리포트 미발행, 이어하기 안내.
        "is_aborted_disengaged": _is_abort_disengaged,
        "is_awaiting_abort_decision": _is_abort_confirm,
        "session_status": session.status,
        # 코치가 조기 종료를 '제안'함 — 프론트가 '다음에 하기/계속 진행하기'
        # 버튼을 노출해야 함 (Core Rule 7, 최대 2회)
        "needs_user_decision": needs_user_decision,
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
    user_message_text: str,
    instruction_used: str | None,
    prev_instruction: str | None,
    prev_coach_text: str | None,
    target_changed: bool,
    mapped_target: str | None,
) -> UUID | None:
    """사건 생명주기 — 백엔드 결정론 (2026-09-22, LLM 자기보고 폐기; 코드 리뷰 2-d 🟥 #1·#2·#5).

    직전 코치 턴의 instruction·문장과 사용자 발화만으로: 새 사건 생성(앵커·부재 폴백·정의 합의 뒤 첫 서술),
    STAR 슬롯 채움(직전 질문이 결과 질문이면 R, 아니면 A→R→T 순), 완결(타겟 전진 또는 새 사건 시작).
    mapped_subcompetency 는 원장 타겟(LLM 추정 아님). 단답·부재·회피·메타 턴은 슬롯을 채우지 않는다.

    Returns: 이 턴이 속한 사건 UUID (없으면 None)
    """
    from diag_project.services.event_tracker import plan_event_update

    active_event = await get_active_event(db, session_id, chapter)
    active_flags = None
    if active_event:
        active_flags = {
            "situation": bool(active_event.situation), "task": bool(active_event.task),
            "action": bool(active_event.action), "result": bool(active_event.result),
        }
    plan = plan_event_update(
        user_text=user_message_text, instruction_used=instruction_used, prev_instruction=prev_instruction,
        prev_coach_text=prev_coach_text, active=active_flags, target_changed=target_changed,
    )
    text = (user_message_text or "").strip()[:500]

    async def _complete(ev) -> None:
        await complete_event(db=db, event_id=ev.id, metadata={
            "summary": (ev.situation or text)[:60],
            "mapped_subcompetency": ev.mapped_subcompetency or mapped_target,
        })

    if plan.op == "new":
        if active_event and plan.complete_active:
            await _complete(active_event)
        existing = await get_chapter_events(db, session_id, chapter)
        new_event = await create_event(db=db, session_id=session_id, chapter=chapter, sequence_num=len(existing) + 1)
        new_event.mapped_subcompetency = mapped_target
        await update_event_star(db=db, event_id=new_event.id, situation=text)
        await increment_probe_count(db, new_event.id)
        return new_event.id

    if active_event is None:
        return None
    if plan.op == "fill" and plan.slot:
        await update_event_star(db=db, event_id=active_event.id, **{plan.slot: text})
    await increment_probe_count(db, active_event.id)
    if plan.complete_after:
        await _complete(active_event)
    return active_event.id


# ------------------------------------------------------------------
# [3] (제거됨) POST /reset — 무인증 파괴 엔드포인트(C1 검토 C3).
#   participant_id 만 알면 타인의 세션 전량을 지울 수 있었고, events/reports 를
#   지우지 않아 FK 위반(500)으로 부분 삭제 상태를 남겼다. 데이터 삭제는
#   어드민 전용 일괄 삭제(/admin/participants/bulk-delete)만 사용한다.
# ------------------------------------------------------------------

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

    # (2026-09-17) 경계 '계속/휴식' 대기 마커 경로 삭제 — 어디서도 세워지지 않던 죽은 코드.
    _last_model_msg = next(
        (m for m in reversed(messages) if m.role == "model"), None
    )
    # 조기 종료 '제안' 대기 여부 — 새로고침 후에도 선택 버튼 복원
    _needs_user_decision = (
        _last_model_msg is not None
        and _last_model_msg.probe_type_used == "SUGGEST_PAUSE"
        and not _is_completed
        and session.status != "paused"
    )

    return {
        "session_id": session.id,
        "current_topic": session.current_topic,
        "completed_topics": completed_topics,
        "status": session.status,
        "is_paused": session.status == "paused",
        "is_completed": _is_completed,
        "needs_user_decision": _needs_user_decision,
        "has_next_chapter": _next_chapter is not None,
        "next_topic": _next_topic,
        "messages": formatted_messages
    }