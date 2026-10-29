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
from diag_project import llm_provider as _llm_provider
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
from diag_project.prompts.phase3a.layer3_state import expectation_usable as _expectation_usable
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
        # (2026-10-23 파일럿 전 1) 재개 세션이 없으면 '가장 최근 completed 세션'을 함께 돌려준다.
        #   프론트는 이 값이 있으면 새 세션을 만들지 않고 리포트 화면(/report?session_id=)으로 보낸다.
        #   리포트 미생성(degraded/failed)이면 같은 화면이 안내를 보여 준다. 새 진단은 리포트 화면의 버튼으로만.
        return {"has_active": False, "completed": await latest_completed_summary(db, participant_id)}
    key = _coach_key_from_id(s.coach_id)
    return {
        "has_active": True,
        "session_id": str(s.id),
        "coach_id": str(s.coach_id),
        "coach_name": COACHES_PERSONA[key]["name"],
    }


def analysis_status_of(session) -> Optional[str]:
    """세션 JSONB 의 last_analysis.status ("degraded" | "failed" | "ok" | "reset" | None)."""
    sd = getattr(session, "self_assessment_data", None) or {}
    la = sd.get("last_analysis") or {}
    return la.get("status") or None


def completed_summary(session, has_report: bool) -> dict:
    """completed 세션 한 건의 요약(프론트 분기용). 순수 함수 — 테스트에서 직접 검증."""
    try:
        cname = COACHES_PERSONA[_coach_key_from_id(session.coach_id)]["name"]
    except Exception:  # noqa: BLE001 — 코치 매핑이 없어도 요약은 돌려준다
        cname = None
    return {
        "session_id": str(session.id),
        "coach_id": str(session.coach_id),
        "coach_name": cname,
        "has_report": bool(has_report),
        "analysis_status": analysis_status_of(session),
        "completed_at": (session.updated_at or session.created_at).isoformat()
        if (session.updated_at or session.created_at) else None,
    }


async def latest_completed_summary(db: AsyncSession, participant_id: uuid.UUID) -> Optional[dict]:
    """참가자의 가장 최근 completed 세션 + 리포트 존재 여부. 없으면 None."""
    from diag_project.models.diagnosis_report import DiagnosisReport
    q = select(DiagnosisSession).where(
        DiagnosisSession.user_id == participant_id,
        DiagnosisSession.status == "completed",
    ).order_by(desc(DiagnosisSession.updated_at), desc(DiagnosisSession.created_at))
    s = (await db.execute(q)).scalars().first()
    if not s:
        return None
    rep = (await db.execute(
        select(DiagnosisReport.id).where(DiagnosisReport.session_id == s.id).limit(1)
    )).first()
    return completed_summary(s, rep is not None)


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
    # (2026-10-29 P1-4) 1인 재사용 대비 — 앵커 문안·프레임 회전(n mod 2), 이전 세션에서 쓴 사다리 단계는 피한다(미사용 우선).
    _anchor_variant = int(past_session_count) % 2
    _ladder_avoid: dict = {}
    if past_session_count:
        _past_rows = (await db.execute(
            select(DiagnosisSession.self_assessment_data).where(DiagnosisSession.user_id == request.participant_id))).scalars().all()
        for _ps in _past_rows:
            for _k, _steps in (((_ps or {}).get("ladder_used") or {}) if isinstance(_ps, dict) else {}).items():
                _ladder_avoid[_k] = sorted(set((_ladder_avoid.get(_k) or []) + list(_steps or [])))

    # 코치 페르소나 조회 (알 수 없는 coach_id면 400 반환)
    persona, opening = _resolve_persona(request.coach_id, user_name, visit_count)

    # (2026-10-15) 세션 LLM provider 고정: 참가자 소속 고객사(companies.llm_provider)에서 결정,
    #   null 이면 환경 기본값(LLM_PROVIDER). 이후 환경·고객사 설정이 바뀌어도 이 세션은 바뀌지 않는다.
    _company_provider = None
    if user and user.company_id:
        from diag_project.models.company import Company as _Company
        _company = await db.get(_Company, user.company_id)
        _company_provider = _company.llm_provider if _company else None
    _session_provider = _llm_provider.resolve_for_company(_company_provider)

    # DB 저장
    new_session = DiagnosisSession(
        id=uuid.uuid4(),
        user_id=request.participant_id,
        coach_id=request.coach_id,
        diagnosis_template_id=request.template_id,
        status="in_progress",
        current_topic="General",
        llm_provider=_session_provider,
        self_assessment_data={"anchor_variant": _anchor_variant, "ladder_avoid": _ladder_avoid},
        created_at=datetime.now(),
        updated_at=datetime.now()
    )
    llm.bind_provider(_session_provider)
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


# (2026-09-22) 코치 턴 LLM 실패 처리 — 시스템 안내 문구·연속 상한
LLM_ERROR_PAUSE_AFTER = 3
LLM_ERROR_RETRY_MESSAGE = "일시적인 문제로 답변을 준비하지 못했습니다. 잠시 후 다시 시도해 주세요."
LLM_ERROR_PAUSED_MESSAGE = ("일시적인 문제가 계속되고 있습니다. 대화는 여기까지 안전하게 저장해 두었으니, "
                            "잠시 후 '진단 계속하기'로 이어서 진행해 주세요.")


async def _submit_message_phase3a(
    request: ChatMessageRequest,
    db: AsyncSession,
    llm: GeminiService,
):
    """Phase 3-A 흐름. USE_PHASE3A=true 시 활성."""
    import time as _time
    # ⏱ (2026-09-18) 턴 계측: decider / LLM 1차 / 재생성 횟수·시간 / 후처리+DB. 로그 한 줄로 남긴다.
    _tm = {"t0": _time.perf_counter(), "decider": 0.0, "llm": 0.0, "regen_n": 0, "regen_s": 0.0}
    from diag_project.database import sql_count as _sqlc
    _sqlc.set(0)   # 이 턴의 SQL 문 수(FM_SQL_COUNT=1 일 때만 집계)
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
    # (2026-10-15) 이 턴의 LLM provider = 세션 고정값(구 세션 null → 환경 기본값)
    llm.bind_provider(session.llm_provider)

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
        await db.flush()   # (2026-09-22) 턴 끝 1회 커밋 — 중간 커밋 폐지

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
    await db.flush()   # (2026-09-22) 턴 끝 1회 커밋 — 중간 커밋 폐지

    # (2026-09-22) 전체 히스토리 1회 로드 — 직전 코치 문장(사건 슬롯·앵커 반복 방지)·한 자리 경과(일시중지 제안)에 쓴다.
    history_messages = (await db.execute(
        select(ChatMessage).where(ChatMessage.session_id == session.id).order_by(ChatMessage.created_at.asc())
    )).scalars().all()
    _recent_coach_texts: list[str] = [
        (m.content or "") for m in history_messages if (m.role == MessageRole.MODEL or m.role == "model")
    ][-2:][::-1]
    _prev_coach_text = _recent_coach_texts[0] if _recent_coach_texts else ""
    _prev_user_texts = [(m.content or "") for m in history_messages if (m.role == MessageRole.USER or m.role == "user")]
    _prev_user_text = _prev_user_texts[-2] if len(_prev_user_texts) >= 2 else ""   # [-1] 은 이번 발화
    from diag_project.models.event import Event as _EventM
    all_events = list((await db.execute(
        select(_EventM).where(_EventM.session_id == session.id).order_by(_EventM.sequence_num)
    )).scalars().all())

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
        # (2026-09-22) 스냅샷에서: 직전 코치 턴의 instruction (SQL 없음)
        _last_model_snap = next((m for m in reversed(history_messages)
                                 if (m.role == MessageRole.MODEL or m.role == "model")), None)
        _last_probe = _last_model_snap.instruction_used if _last_model_snap else None
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
        await db.flush()   # (2026-09-22) 턴 끝 1회 커밋 — 중간 커밋 폐지
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
    state = await build_turn_state(db, session.id, chapter, messages=history_messages, events_all=all_events)
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
            await db.flush()   # (2026-09-22) 턴 끝 1회 커밋 — 중간 커밋 폐지
            state["participant_context"] = _pc_store["participant_context"]
            logger.info("🧩 participant_context 저장: team_size=%s role='%s'", _m.group(1) if _m else None, _rt[:40])
    # (2026-10-28 P0-3) 사전 질문(앵커 폴백·챕터 오프닝·고정 질문)은 전부 이 헬퍼로 페르소나 어미를 입힌다.
    #   10/26~28 운영: _anchor_fallback(template_anchor)·CHAPTER_OPENING 시스템 출력이 voice_question 을 거치지 않아
    #   6명이 같은 앵커 문장을 냈다(ALIGN 앵커만 _render_anchor_for 에서 변환됐다).
    def _voiced_q(q: str) -> str:
        from diag_project.services.persona_voice import voice_question as _vq0
        _tm["voiced"] = 1
        return _vq0((state.get("coach_persona") or {}).get("name"), q,
                    variant=int(((session.self_assessment_data or {}).get("voice_variant_count") or {}).get(chapter, 0) or 0))

    # (2026-10-28 P0-4·P0-7) 사용자 입력 이상 — LLM 호출·원장 전진 없이 시스템 고정 응답으로 직전 질문을 다시 낸다.
    #   종류: 직전 입력 반복 / 세션 앞 답변·기존 사건과 중복 / 코치 질문 되돌아옴 / 일시정지 문구 오입력 /
    #   안내 뒤 비실질 입력 / 정의 답 10자 미만 / 질문 뒤 '네·sp·??'. 판정은 services/input_anomaly.detect(순수 함수).
    _anomaly_override_text = None
    _align_ctx = None   # (2026-10-28 P0-1) ALIGN 조립 재료 — 후처리 끝에 render_align 으로 조립
    try:
        from diag_project.services import input_anomaly as _ia
        from diag_project.services.intro_messages import persona_line as _pl_an
        _prev_model_msgs_a = [m for m in history_messages if (m.role == MessageRole.MODEL or m.role == "model")]
        _prev_instr_a = _prev_model_msgs_a[-1].instruction_used if _prev_model_msgs_a else None
        _prev_probe_a = _prev_model_msgs_a[-1].probe_type_used if _prev_model_msgs_a else None
        _store_a = dict(session.self_assessment_data or {})
        _anomaly = _ia.detect(
            user_text=request.content, prev_user_text=_prev_user_text,
            earlier_user_texts=_prev_user_texts[:-2] if len(_prev_user_texts) >= 2 else [],
            prev_coach_text=_prev_coach_text, prev_instruction=_prev_instr_a,
            event_texts=[" ".join(x for x in (e.situation, e.task, e.action, e.result) if x) for e in all_events],
            pause_pending=bool(state.get("resume_pending")) or _prev_instr_a == "USER_REQUESTS_PAUSE" or _prev_probe_a == "SUGGEST_PAUSE",
            awaiting_choice=bool(state.get("awaiting_next_chapter_choice")) or session.status != "in_progress",
            definition_reasked=bool((_store_a.get("definition_reasked") or {}).get(chapter)) if chapter else False,
        ) if (request.content or "").strip() else None
        if _anomaly is not None:
            _pn_a = (state.get("coach_persona") or {}).get("name")
            _q_a = _anomaly.question
            # (2026-10-29 P1) 같은 타겟에서 같은 종류의 이상이 반복되면 단계적으로: ANCHOR_REASK 2회째 변형 문장, 3회째·INPUT_DUPLICATE 3회째는
            #   '이 항목은 여기까지 듣고 넘어간다' — 미확인(unconfirmed) 기록 + 타겟 전진(turns 상한). 전진 턴의 본문은 8-j 가 skip_bridge 로 쓴다.
            _tgt_an = ((_store_a.get("current_target") or {}).get(chapter) or "-") if chapter else "-"
            _ac_all = dict(_store_a.get("anomaly_counts") or {}); _ac_key = f"{chapter}|{_tgt_an}|{_anomaly.kind}"
            _ac_n = int(_ac_all.get(_ac_key, 0) or 0) + 1
            if _anomaly.kind in ("repeat_any", "ack_reask"):
                _ac_all[_ac_key] = _ac_n; _store_a["anomaly_counts"] = _ac_all
                session.self_assessment_data = _store_a
                from sqlalchemy.orm.attributes import flag_modified as _fm_ac
                _fm_ac(session, "self_assessment_data")
            _skip_an = _anomaly.kind in ("repeat_any", "ack_reask") and _ac_n >= 3 and chapter and _tgt_an != "-"
            if _skip_an:
                from diag_project.services.traversal import MAX_TURNS_PER_SUB as _MAXT_an, mark_result_probed as _mrp_an
                _unc = dict(_store_a.get("unconfirmed") or {}); _unc[chapter] = sorted(set((_unc.get(chapter) or []) + [_tgt_an]))
                _store_a["unconfirmed"] = _unc
                _store_a.setdefault("turns_on_target", {})[chapter] = _MAXT_an
                _store_a = _mrp_an(_store_a, chapter)
                session.self_assessment_data = _store_a
                from sqlalchemy.orm.attributes import flag_modified as _fm_sk
                _fm_sk(session, "self_assessment_data")
                state["skip_bridge"] = _pl_an(_pn_a, "skip_item")
                _tm["anomaly"] = f"{_anomaly.kind}#3→skip"
                _tm["unconfirmed"] = _tgt_an
                logger.info("🧷 입력 이상 3회째(%s) → [%s] %s 미확인 기록·전진", _anomaly.kind, chapter, _tgt_an)
            if _skip_an:
                pass   # 고정 응답 없이 이번 턴을 정상 진행 — T2 가 다음 타겟으로 전진(STAR_COMPLETE_NEW_EVENT)
            elif _anomaly.kind == "repeat_prev":
                _anomaly_override_text = f"{_pl_an(_pn_a, 'same_input')} {_q_a}"; instruction_used = "INPUT_REPEATED"
            elif _anomaly.kind == "repeat_any":
                _anomaly_override_text = f"{_pl_an(_pn_a, 'repeat_event')} {_q_a}"; instruction_used = "INPUT_DUPLICATE"
            elif _anomaly.kind == "returned_q":
                _anomaly_override_text = f"{_pl_an(_pn_a, 'question_returned')} {_q_a}"; instruction_used = "QUESTION_RETURNED"
            elif _anomaly.kind == "pause_phrase":
                _anomaly_override_text = f"{_pl_an(_pn_a, 'continue_ack')} {_q_a}"; instruction_used = "QUESTION_REASK"
            elif _anomaly.kind == "confirm_reask":
                _anomaly_override_text = _pl_an(_pn_a, "confirm_reask"); instruction_used = "CONFIRM_REASK"
            elif _anomaly.kind == "def_reask":
                from diag_project.services.korean import with_josa as _wj_an
                _cn_an = COMPETENCY_FRAMEWORK.get(chapter, {}).get("name", "이 역량") if chapter else "이 역량"
                _anomaly_override_text = _pl_an(_pn_a, "definition_reask", cn_eul=_wj_an(_cn_an, "을/를"))
                instruction_used = "DEFINITION_REASK"
                if chapter:
                    _dr = dict(_store_a.get("definition_reasked") or {}); _dr[chapter] = True
                    _store_a["definition_reasked"] = _dr
                    session.self_assessment_data = _store_a
                    from sqlalchemy.orm.attributes import flag_modified as _fm_dr
                    _fm_dr(session, "self_assessment_data")
            else:   # ack_reask — 2회째는 '비슷한 다른 장면이라도 괜찮아요' 변형
                _anomaly_override_text = f"{_pl_an(_pn_a, 'reask_anchor_2' if _ac_n == 2 else 'reask_anchor')} {_q_a}"; instruction_used = "ANCHOR_REASK"
            if not _skip_an:
                state["instruction_for_this_turn"] = instruction_used
                _tm["anomaly"] = _anomaly.kind if _ac_n < 2 else f"{_anomaly.kind}#{_ac_n}"
                logger.info("🧷 입력 이상(%s×%d): %s → %s", _anomaly.kind, _ac_n, _anomaly.detail, instruction_used)
    except Exception as _ae:
        logger.warning("입력 이상 판정 실패(무시): %s", _ae)

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
        # 🌱 태도 진술(2026-09-29): 30자 미만·시점/인물/행동 없음. 2회 연속이면 R 강제 해제 + 계기 질문 1회,
        #   그 뒤에도 태도·부재·단답이면 이번 턴에 다음 하위역량으로 전진(3턴 상한은 최대치이지 목표가 아니다).
        from diag_project.services.event_tracker import is_attitude_statement as _is_att
        _att_now = _is_att(request.content)
        _att_map = dict(_store.get("attitude_streak") or {})
        _att_trig = dict(_store.get("attitude_trigger") or {})
        _tgt_now = (_store.get("current_target") or {}).get(chapter)
        if _att_trig.get(chapter) and _att_trig.get(chapter) == _tgt_now and (
                _att_now or _abs(request.content) or len((request.content or "").replace(" ", "")) < 12):
            from diag_project.services.traversal import MAX_TURNS_PER_SUB as _MAXT2
            _store.setdefault("turns_on_target", {})[chapter] = _MAXT2
            logger.info("🌱 계기 질문 뒤에도 태도·부재 → [%s] 타겟 전진", chapter)
        _att_map[chapter] = (int(_att_map.get(chapter, 0) or 0) + 1) if _att_now else 0
        _store["attitude_streak"] = _att_map
        _event_done = instruction_used == "STAR_COMPLETE_NEW_EVENT"
        # 🔑 타겟 전진 감지용: 스텝 '이전'의 현재 타겟(없으면 None=챕터 첫 앵커).
        _cur_before = (_store.get("current_target") or {}).get(chapter)
        # (2026-10-22 P2-0) 자발적 사례: 리더가 앵커 질문 없이 '아직 안 다룬' 하위역량의 사례를 분명히 말했으면(flash 판정)
        #   asked 원장에 기록해 같은 앵커를 다시 묻지 않는다. 현재 타겟과 같으면 기록하지 않는다(그건 정상 답변).
        if len((request.content or "").replace(" ", "")) >= 60:
            from diag_project.data.competencies import SUBCOMPETENCY_ANCHORS as _SA, find_sub_key_by_name as _fsk_v
            from diag_project.services.llm_judge import volunteered_subcompetency as _vol
            _asked_now = set(asked_for_chapter(_store, chapter))
            _cands = {}
            for _nm in _all_subs:
                if _nm in _asked_now or _nm == _cur_before:
                    continue
                _k = _fsk_v(chapter, _nm)
                _cands[_nm] = " / ".join(_SA.get(_k) or []) if _k else ""
            if _cands:
                _vsub = await _vol(llm, request.content, _cands)
                if _vsub:
                    from diag_project.services.traversal import record_asked as _rec_v
                    _store = _rec_v(_store, chapter, _vsub)
                    _tm["volunteered"] = _vsub
                    logger.info("🗂️ 자발적 사례 → asked 기록: [%s] %s (앵커 재질문 금지)", chapter, _vsub)
        _store, current_target_sub = apply_probe_turn(
            _store, chapter, _all_subs, _event_done, priority=[]
        )
        # (2026-10-22 P2-2) 리더 답변이 S-A-R 을 이미 다 담았으면(과거형 행동 2+ · 결과 표지 · 80자+) 이번 턴 탐침 1회로 줄이고
        #   다음 턴에 전진 — 현재 타겟 turns 를 상한으로 올리고 result_probed 를 True 로(답에 결과가 있으므로 R 강제 불필요).
        #   되받기(다음 전환 턴의 8-j 본문)가 들은 것을 요약하고 넘어간다.
        # (2026-10-29 P1) 사다리 중복 방지 — 사다리 문장을 내기 전에 직전 리더 답에 그 행동이 이미 있는지 Haiku 1콜로 판정.
        #   있으면 2단계 중 미사용 단계로 교체, 둘 다 이미 있으면 건너뛰고 ladder_probed 표시('답에 있었음'으로 기록, 미발동 아님).
        async def _choose_ladder(sub_key: str, lvl, answer: str):
            from diag_project.data.ladder_questions import LADDER_QUESTIONS as _LQS, ladder_question as _lq_c
            from diag_project.services.llm_judge import ladder_already_answered as _laa
            _avoid = ((_store.get("ladder_avoid") or {}).get(sub_key) or [])
            q, step = _lq_c(sub_key, lvl if lvl is not None else 2, avoid=_avoid)
            if not q:
                return None, None, None
            if await _laa(llm, answer, q) is not True:
                return q, step, None
            other = "3_4" if step == "2_3" else "2_3"
            q2 = (_LQS.get(sub_key) or {}).get(other)
            if q2 and await _laa(llm, answer, q2) is not True:
                _tm["ladder_swap"] = 1
                return q2, other, "swapped"
            _tm["ladder_skip"] = "answered"
            return None, None, "answered"

        def _mark_ladder_answered(store: dict, sub: str) -> dict:
            from diag_project.services.traversal import mark_ladder_probed as _mlp_a
            store = _mlp_a(store, chapter, sub)
            _ls = dict(store.get("ladder_skipped") or {}); _lsc = dict(_ls.get(chapter) or {}); _lsc[sub] = "answered"
            _ls[chapter] = _lsc; store["ladder_skipped"] = _ls
            logger.info("🪜 사다리 건너뜀(답에 이미 있음): [%s] %s", chapter, sub)
            return store

        from diag_project.services.avoidance_detector import has_full_star as _hfs
        from diag_project.services.traversal import MAX_TURNS_PER_SUB as _MAXT_sar, advanced_to_new_target as _adv_sar
        if (current_target_sub and not _adv_sar(_cur_before, current_target_sub) and _hfs(request.content)
                and int((_store.get("turns_on_target") or {}).get(chapter, 0) or 0) < _MAXT_sar):
            _store.setdefault("turns_on_target", {})[chapter] = _MAXT_sar
            _store.setdefault("result_probed", {})[chapter] = True
            state["sar_complete_answer"] = True
            _tm["sar_full"] = 1
            logger.info("🧭 S-A-R 완비 답변 → [%s] %s 탐침 1회 후 전진", chapter, current_target_sub)
            # (2026-10-23 P3) 레벨 사다리 탐침 — 추가가 아니라 교체: 이 '탐침 1회'를 현재 레벨 +1 의 루브릭 차별 행동 질문으로.
            #   현재 레벨은 flash 판정(실패면 Lv.2 기준). Lv.4 면 사다리 없음. 타겟당 1회. 답이 일반화든 아니든 다음 턴에 전진.
            from diag_project.data.competencies import find_sub_key_by_name as _fsk_l
            from diag_project.data.ladder_questions import ladder_question as _lq
            from diag_project.services.llm_judge import judge_rubric_level as _jrl
            from diag_project.services.traversal import ladder_probed as _lpd
            _sub_key_l = _fsk_l(chapter, current_target_sub)
            if _sub_key_l and not _lpd(_store, chapter, current_target_sub):
                _lvl = await _jrl(llm, chapter, current_target_sub, request.content)
                _lq_text, _lq_step, _lq_why = await _choose_ladder(_sub_key_l, _lvl, request.content)
                if _lq_text:
                    state["force_ladder_probe"] = {"q": _lq_text, "step": _lq_step, "level": _lvl, "sub": current_target_sub}
                    logger.info("🪜 사다리 탐침: [%s] %s 판정 Lv.%s → %s%s", chapter, current_target_sub, _lvl, _lq_step, " (미사용 단계로 교체)" if _lq_why == "swapped" else "")
                elif _lq_why == "answered":
                    _store = _mark_ladder_answered(_store, current_target_sub)
        # (2026-10-29 P1-1) 사다리 발동 조건 확장 — S-A-R 완비 판정과 무관하게, 이 타겟에 탐침을 2턴 이상 썼고(이번이 3번째 턴)
        #   사다리를 아직 안 썼으면 이번 탐침은 사다리. s31 25세션: Michael 세션당 1.2회·Jessica 조직관리 0회 — 완비 판정이 실세션에
        #   안 맞았다. 목표 챕터당 2회 이상(린트 집계). 사다리 턴은 R·A·일반화 강제보다 우선한다(아래 force 블록).
        _ans_l = (request.content or "").strip()
        if (chapter and current_target_sub and not state.get("force_ladder_probe") and not _adv_sar(_cur_before, current_target_sub)
                and instruction_used in ("CONTINUE_NORMAL", "CONTRARY_NEEDED", "STAR_INCOMPLETE")
                and int((_store.get("turns_on_target") or {}).get(chapter, 0) or 0) >= 3
                and len(_ans_l.replace(" ", "")) >= 30 and not _ans_l.endswith("?")):   # (p11) '무슨 말씀이시죠?' 뒤에도 사다리가 나갔다
            from diag_project.data.competencies import find_sub_key_by_name as _fsk_l2
            from diag_project.data.ladder_questions import ladder_question as _lq2
            from diag_project.services.llm_judge import judge_rubric_level as _jrl2
            from diag_project.services.traversal import ladder_probed as _lpd2
            _sub_key_l2 = _fsk_l2(chapter, current_target_sub)
            if _sub_key_l2 and not _lpd2(_store, chapter, current_target_sub):
                _lvl2 = await _jrl2(llm, chapter, current_target_sub, request.content)
                _lq_text2, _lq_step2, _lq_why2 = await _choose_ladder(_sub_key_l2, _lvl2, request.content)
                if _lq_text2:
                    state["force_ladder_probe"] = {"q": _lq_text2, "step": _lq_step2, "level": _lvl2, "sub": current_target_sub}
                    _tm["ladder_trigger"] = "turns"
                    logger.info("🪜 사다리 탐침(턴 조건): [%s] %s 판정 Lv.%s → %s%s", chapter, current_target_sub, _lvl2, _lq_step2, " (미사용 단계로 교체)" if _lq_why2 == "swapped" else "")
                elif _lq_why2 == "answered":
                    _store = _mark_ladder_answered(_store, current_target_sub)
        session.self_assessment_data = _store
        from sqlalchemy.orm.attributes import flag_modified as _flag_mod
        _flag_mod(session, "self_assessment_data")
        await db.flush()   # (2026-09-22) 턴 끝 1회 커밋 — 중간 커밋 폐지
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
        # 🌱 태도 진술 2회 연속 → 계기 질문 1회(R 강제 해제). 새 타겟으로 넘어갔으면 카운터·트리거 리셋.
        _st_att = dict(session.self_assessment_data or {})
        _am = dict(_st_att.get("attitude_streak") or {}); _tm_att = dict(_st_att.get("attitude_trigger") or {})
        if _target_advanced_now:
            _am[chapter] = 0; _tm_att.pop(chapter, None)
        elif int(_am.get(chapter, 0) or 0) >= 2 and _tm_att.get(chapter) != current_target_sub \
                and instruction_used in ("CONTINUE_NORMAL", "CONTRARY_NEEDED", "STAR_INCOMPLETE"):
            _tm_att[chapter] = current_target_sub
            state["attitude_trigger"] = True
            _force_r = False
            from diag_project.services.traversal import mark_result_probed as _mrp_att
            _st_att = _mrp_att(_st_att, chapter)
            logger.info("🌱 태도 진술 2회 연속 → [%s] %s 계기 질문(R 강제 해제)", chapter, current_target_sub)
        _st_att["attitude_streak"] = _am; _st_att["attitude_trigger"] = _tm_att
        session.self_assessment_data = _st_att
        from sqlalchemy.orm.attributes import flag_modified as _fm_att
        _fm_att(session, "self_assessment_data")
        state["force_result_probe"] = _force_r
        # (2026-10-22 P2-2) S-A-R 중 빈 요소 먼저: 상황(S)은 들었는데 리더가 직접 한 행동(A)이 비어 있고 아직 A 를 묻지 않았으면
        #   이번 탐침은 행동 질문(R 강제가 아닐 때). 원장 action_probed 는 코치 질문이 행동 표지일 때 턴 끝에 기록.
        from diag_project.services.traversal import action_probed as _ap
        _cov_sar = state.get("current_event_star_coverage") or {}
        _force_a = (not _target_advanced_now and not _force_r and not state.get("sar_complete_answer")
                    and instruction_used in ("CONTINUE_NORMAL", "CONTRARY_NEEDED", "STAR_INCOMPLETE")
                    and bool(_cov_sar) and bool(_cov_sar.get("S")) and not _cov_sar.get("A")
                    and not _ap(session.self_assessment_data, chapter))
        state["force_action_probe"] = _force_a
        if _force_a:
            logger.info("🎯 A 탐침 강제: [%s] target=%s (S 있음·A 비어 있음)", chapter, current_target_sub)
        # (2026-10-23, 4-1) 일반화 답변 → 구체 사례 탐침 1회. 앵커 답변(이 타겟 2번째 코치 턴)에 시점이 없고 습관 표지가
        #   있으면 이번 질문은 "그중 가장 최근 일 하나만요"(페르소나별). 타겟당 1회, 그래도 일반화면 그대로 전진.
        from diag_project.services.avoidance_detector import is_generalized_answer as _iga
        from diag_project.services.traversal import generalize_probed as _gpd
        # (2026-10-29 P1-3) 직전 턴이 일반화 탐침이었는데 이번 답도 시점이 없으면 → generalized 원장(챕터별 하위역량 목록)
        _gp_store = dict(session.self_assessment_data or {})
        _gp_pending = (_gp_store.get("generalize_pending") or {}).get(chapter) if chapter else None
        if _gp_pending:
            _gpd_map = dict(_gp_store.get("generalize_pending") or {}); _gpd_map.pop(chapter, None); _gp_store["generalize_pending"] = _gpd_map
            if _iga((state.get("resume_pending") or {}).get("user_text") or request.content):
                _gz = dict(_gp_store.get("generalized") or {}); _gz[chapter] = sorted(set((_gz.get(chapter) or []) + [_gp_pending]))
                _gp_store["generalized"] = _gz
                _tm["generalized"] = _gp_pending
                logger.info("🧭 일반화 탐침 뒤에도 시점 없음 → generalized 기록: [%s] %s", chapter, _gp_pending)
            session.self_assessment_data = _gp_store
            from sqlalchemy.orm.attributes import flag_modified as _fm_gp
            _fm_gp(session, "self_assessment_data")
        _tot_g = int((session.self_assessment_data.get("turns_on_target") or {}).get(chapter, 0) or 0)
        _force_g = bool(chapter and current_target_sub and not _target_advanced_now and _tot_g == 2
                        and instruction_used in ("CONTINUE_NORMAL", "CONTRARY_NEEDED", "STAR_INCOMPLETE")
                        and not state.get("sar_complete_answer")
                        and _iga((state.get("resume_pending") or {}).get("user_text") or request.content)
                        and not _gpd(session.self_assessment_data, chapter, current_target_sub))
        state["force_generalize_probe"] = _force_g
        state["contrast_used"] = int(((session.self_assessment_data or {}).get("contrast_q_count") or {}).get(chapter, 0) or 0) >= 1
        if _force_g:
            _force_a = False
            _force_r = False
            state["force_action_probe"] = False
            state["force_result_probe"] = False
            logger.info("🧭 일반화 탐침: [%s] target=%s (시점 없음·습관 표지)", chapter, current_target_sub)
        if state.get("force_ladder_probe"):
            # (2026-10-29 P1-1) 사다리 턴에는 R·A·일반화 강제를 걸지 않는다 — 사다리 질문 하나만 나간다.
            if _force_r or _force_a or _force_g:
                logger.info("🪜 사다리 턴 → R/A/일반화 강제 해제 (R=%s A=%s G=%s)", _force_r, _force_a, _force_g)
            _force_r = False; _force_a = False; _force_g = False
            state["force_result_probe"] = False; state["force_action_probe"] = False; state["force_generalize_probe"] = False
        if _force_r:
            from diag_project.services.output_guard import needs_quantify_probe as _nqp
            state["result_quantify"] = _nqp((state.get("resume_pending") or {}).get("user_text") or request.content)
        if _force_r and chapter:
            # (2026-09-29) 풀 문장을 넣지 않는다 — 직전 발화의 명사구를 주고 LLM 이 결과 질문을 만든다.
            from diag_project.services.output_guard import key_noun_phrase as _knp
            state["result_focus"] = _knp((state.get("resume_pending") or {}).get("user_text") or request.content)
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
            await db.flush()   # (2026-09-22) 턴 끝 1회 커밋 — 중간 커밋 폐지
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
    await db.flush()   # (2026-09-22) 턴 끝 1회 커밋 — 중간 커밋 폐지

    # 5. 대화 이력 압축
    compressed_history = await compress_conversation_history(db, session.id, chapter, messages=history_messages, events_all=all_events)

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
    # (2026-10-22 P1-1) 일시정지 제안 뒤 '계속' 재개 턴: 리더의 이번 메시지는 재개 의사일 뿐이다. 제안 직전 답변을
    #   이어받아 pending 탐침을 그대로 던지게 하고, 새 주제·새 앵커를 금지한다.
    _resume_pend = state.get("resume_pending")
    _llm_user_text = request.content
    if _resume_pend:
        _tm["resume"] = 1   # guard_log 에 재개 턴 표식
        _prev_answer = (_resume_pend.get("user_text") or "").strip()
        if _prev_answer:
            _llm_user_text = _prev_answer
        turn_state_text += (
            "\n\n🔁 [시스템 — 재개] 직전 턴에 잠시 쉬어갈지 안내했고 리더님이 '계속'을 골랐습니다. 이번 메시지는 재개 의사일 뿐이니 "
            "되받지 마세요. 아래 [Latest User Message]는 그 전에 리더님이 하신 답변입니다 — 그 답변에 이어 이번 지시의 탐침을 "
            "그대로 던지세요. 새 주제·새 앵커·'다시 시작' 류 인사 금지.")
    if state["style_at_tail"]:
        from diag_project.prompts.phase3a.layer3_state import build_style_tail
        _style_tail = build_style_tail(state)
    user_name = state.get("user_name", "리더")
    # (2026-09-22) light 턴(라포·INTRO·CONFIRM·ALIGN·META 등)은 BEI 절을 뺀 Layer1 — 매핑표 docs/prompt_reduction_2026-09-22.md
    _LIGHT_LAYER1_INSTRUCTIONS = {
        "RAPPORT_BUILDING", "DIAGNOSIS_INTRO", "DIAGNOSIS_CONFIRM", "COMPETENCY_ASK", "COMPETENCY_ALIGN",
        "META_QUESTION_FROM_USER", "USER_REQUESTS_PAUSE", "INVALID_INPUT", "PROMPT_INJECTION_DETECTED",
        "CHAPTER_CONTINUE_CONFIRMED", "NAME_RECONFIRM", "CHAPTER_ONE_MORE_ASK",
    }
    system_prompt = build_layer1_with_persona(
        coach_id=coach_key,
        user_name=user_name,
        visit_count=1,
        mode=("light" if instruction_used in _LIGHT_LAYER1_INSTRUCTIONS else "heavy"),
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
        await db.flush()   # (2026-09-22) 턴 끝 1회 커밋 — 중간 커밋 폐지

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
        await db.flush()   # (2026-09-22) 턴 끝 1회 커밋 — 중간 커밋 폐지

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
    # (2026-10-16) 라포 2턴(담당 업무 질문)은 더 이상 템플릿이 아니다 — light LLM 호출(카테고리 '담당업무' 가이드).
    #   템플릿 "그러시군요. 어떤 일을 맡고 계신지도…" 는 직전 답변("금요일이라 일이 잘 안되네요")의 감정·판단을
    #   받을 수 없었다. 이름 턴(라포 1턴)만 템플릿으로 남긴다. ROLE_ASK 마커는 아래에서 카테고리 기준으로 붙는다.
    #   (2026-10-19) 2·3턴 LLM 출력은 되받기 한 문장만, 질문은 8-0 에서 백엔드 고정 문장을 붙인다.
    elif (instruction_used == "DIAGNOSIS_INTRO"
            and not _expectation_usable(state.get("expectation_answer"))):
        # (2026-10-19) 기대 답변이 없거나('없어요'·'모르겠어요'·동의만) 기대라 할 내용이 없으면 받는 문장 없이
        #   바로 안내 — LLM 미호출. '괜찮습니다, 뚜렷하지 않으셔도' 류 위로 문장은 INTRO 에서 제거.
        from diag_project.services.intro_messages import persona_line as _pl_i
        system_override_text = f"{_pl_i((state.get('coach_persona') or {}).get('name'), 'intro_bridge')}\n\n{build_intro_anchor_section()}"
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
        system_override_text = _voiced_q(build_chapter_opening_with_user_def(
            chapter=chapter,
            user_definition=state.get("last_user_response", "") or "",
            first_subcompetency_name=state.get("first_subcompetency_name", ""),
            bridge_context=_bridge_ctx,
            variant=int((session.self_assessment_data or {}).get("anchor_variant") or 0),
        ))

    # (2026-10-28 P0-4) 입력 이상 턴은 위 어떤 분기보다 우선 — 고정 응답, LLM 미호출
    if _anomaly_override_text is not None:
        system_override_text = _anomaly_override_text

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
            "CHAPTER_ONE_MORE_ASK",   # (2026-10-22 P2-0) 되받기 한 문장만
        }
        _l0 = _time.perf_counter()
        llm_output = await llm.generate_phase3a_interaction(
            system_prompt=system_prompt,
            chapter_context=chapter_context,
            turn_state_text=turn_state_text,
            compressed_history=compressed_history,
            user_message=_llm_user_text,   # (2026-10-22 P1-1) 재개 턴은 제안 직전 답변
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
            # (2026-09-22, 파일럿 전 필수) 코치 턴 LLM 실패(402·429·타임아웃): 이 턴을 통째로 되돌린다 — 사용자 메시지·원장·
            #   사건 어떤 것도 저장하지 않는다(상태 전진 없음). 사용자에게는 코치 말풍선이 아니라 시스템 안내 + [다시 시도].
            #   같은 세션에서 3회 연속이면 세션을 paused 로 두고 "저장 후 나중에 이어서" 안내. 연속 카운터만 저장한다.
            _kind = llm_output.get("error_kind") or "llm"
            logger.error("💥 코치 턴 LLM 실패(kind=%s) session=%s instr=%s → 턴 롤백", _kind, str(session.id)[:8], instruction_used)
            await db.rollback()
            await db.refresh(session)
            from sqlalchemy.orm.attributes import flag_modified as _fm_le
            _sad_le = dict(session.self_assessment_data or {})
            _streak = int(_sad_le.get("llm_error_streak", 0) or 0) + 1
            _paused_now = _streak >= LLM_ERROR_PAUSE_AFTER
            _sad_le["llm_error_streak"] = 0 if _paused_now else _streak
            session.self_assessment_data = _sad_le
            _fm_le(session, "self_assessment_data")
            if _paused_now and session.status not in ("completed", "aborted", ABANDONED):
                session.status = "paused"
            db.add(session)
            await db.commit()
            _order_le = _get_topic_order()
            _done_le = (_order_le[:] if session.current_topic == "Completed"
                        else _order_le[: _order_le.index(session.current_topic)] if session.current_topic in _order_le else [])
            _next_le = _get_next_chapter(chapter) if chapter else None
            return {
                "coach_response_message": (LLM_ERROR_PAUSED_MESSAGE if _paused_now else LLM_ERROR_RETRY_MESSAGE),
                "llm_error": True,
                "llm_error_kind": _kind,
                "llm_error_streak": _streak,
                "is_topic_completed": False,
                "is_session_starting": False,
                "is_session_completed": False,
                "is_session_paused": _paused_now or session.status == "paused",
                "session_status": session.status,
                "has_next_chapter": _next_le is not None,
                "next_topic": chapter_to_topic(_next_le) if _next_le else None,
                "needs_user_decision": False,
                "reward": None,
                "completed_topics": _done_le,
                "_phase3a_metadata": {"guard": "LLM_ERROR", "streak": _streak},
            }

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
    _backend_pause_suggested = (system_override_text is None and not _llm_error and not state.get("resume_pending") and _ssp(
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

    # (2026-10-21) 앵커 렌더링(ANCHOR_RENDER=dict|llm) — ALIGN 앵커·전환 턴 앵커 공통. 결과 모드는 guard_log 에 남긴다.
    async def _render_anchor_for(sub_name: str | None) -> tuple[str, str]:
        from diag_project.data.competencies import find_sub_key_by_name as _fsk_ar
        from diag_project.services.anchor_render import render_anchor
        _k = _fsk_ar(chapter, sub_name) if (chapter and sub_name) else None
        _q, _mode = await render_anchor(
            llm, _k, recent_turns=[_prev_coach_text, request.content or ""],
            role_summary=(state.get("participant_context") or {}).get("role_summary"),
            pos=int((session.self_assessment_data or {}).get("anchor_variant") or 0),   # (2026-10-29 P1-4) 재세션 회전
        )
        # (2026-10-23 P4) 사전 문장(dict/fallback)은 페르소나 어미 변환 계층을 거친다. llm 렌더링 문장은 그대로.
        if _mode in ("dict", "fallback"):
            from diag_project.services.persona_voice import voice_question as _vq
            _q = _vq((state.get("coach_persona") or {}).get("name"), _q,
                     variant=int(((session.self_assessment_data or {}).get("voice_variant_count") or {}).get(chapter, 0) or 0))
            _tm["voiced"] = 1
        return _q, _mode

    # 8-0. 라포 2·3·4턴 — LLM 은 되받기만, 질문은 백엔드 고정 문장(기록=발화 결합과 같은 방식). (2026-10-19 → 10-21 개편)
    #   count 1 스몰톡: 되받기 1~2문장 + 리더 발화에서 나온 되물음 1개 허용(고정 질문 없음)
    #   count 2 담당업무: 되받기 1문장 + RAPPORT_ROLE_QUESTION
    #   count 3 기대: 역할 반응 1문장 + RAPPORT_EXPECTATION_QUESTION (READY_FOR_INTRO 는 백엔드 확정)
    #   되받기 반복 가드(연속 4자): 1회 재생성, 그래도 겹치면 "그러셨군요.". guard_log echo 1/2.
    if (instruction_used == "RAPPORT_BUILDING" and system_override_text is None and not _llm_error
            and not _suppress_mechanical_text and state.get("rapport_turn_count", 0) >= 1):
        from diag_project.services.intro_messages import RAPPORT_EXPECTATION_QUESTION, RAPPORT_ROLE_QUESTION
        from diag_project.services.output_guard import echoes_user as _echoes
        from diag_project.services.output_guard import receive_sentence as _recv_sent, receive_sentences as _recv_multi
        from diag_project.services.output_guard import is_question as is_question_g, replace_statements as _repl_stmts
        from diag_project.services.output_guard import split_sentences as split_sentences_g
        _rc = state.get("rapport_turn_count", 0)
        _smalltalk = _rc == 1

        from diag_project.services.intro_messages import persona_line as _persona_line_r
        # (2026-10-23 핫픽스) 9fad8ae 에서 persona_line 을 별칭만 바꿔 한 인자로 불렀다 → 라포 3턴마다 TypeError 500(운영 전 세션).
        #   페르소나 이름을 묶은 호출자로 고정한다.
        _persona_name_r = (state.get("coach_persona") or {}).get("name")
        def _pl_r(key: str, **fmt) -> str:
            return _persona_line_r(_persona_name_r, key, **fmt)
        from diag_project.services.output_guard import persona_lead_cap as _plc
        _pn_r = (state.get("coach_persona") or {}).get("name")
        _cap_p = _plc(_pn_r)   # (2026-10-22 P2-3) 페르소나별 되받기 상한

        def _take(txt: str) -> str:
            return _recv_multi(txt, max_statements=_cap_p, allow_question=True) if _smalltalk else _recv_sent(txt)

        _recv = _take(clean_reply)
        if _recv != clean_reply.strip():
            logger.info("✂️ 라포 되받기 정리(%d자 → %d자)", len(clean_reply), len(_recv))
        if _smalltalk:
            # (2026-10-21) 되물음이 일·업무·역할·팀을 물으면(다음 턴 담당) 되물음을 지우고 되받기 1~2문장으로 끝낸다.
            from diag_project.services.output_guard import smalltalk_followup_ok as _sf_ok
            _q_last = next((x for x in reversed(split_sentences_g(_recv)) if is_question_g(x)), "")
            if _q_last and not _sf_ok(_q_last):
                _tm["work_q"] = 1
                _recv = _recv_multi(_recv, max_statements=2, allow_question=False)
                logger.info("✂️ 스몰톡 되물음이 업무·역할 질문 → 삭제: %r", _q_last[:40])
        if _echoes(_recv, request.content):
            _tm["echo"] = 1
            logger.info("🔁 라포 되받기가 리더 발화를 반복: %r → 재생성 1회", _recv[:40])
            try:
                _e_regen = await _timed_regen(
                    system_prompt=system_prompt, chapter_context=chapter_context,
                    turn_state_text=turn_state_text + (
                        "\n\n🚨 [시스템 — 재생성 지시] 방금 만든 첫 문장이 리더님이 쓴 말을 그대로 반복했습니다. "
                        "리더님 단어를 그대로 가져오지 말고, 뜻만 받아 다른 말로 다시 쓰세요."),
                    compressed_history=compressed_history, user_message=request.content, light_mode=True)
                _e_recv = _take(_MARKER_RE.sub("", _e_regen.get("reply") or ""))
            except Exception as _e:
                logger.error("🔁 되받기 재생성 실패: %s", _e)
                _e_recv = ""
            if _e_recv and not _echoes(_e_recv, request.content):
                _recv = _e_recv
            else:
                _tm["echo"] = 2
                _recv = _repl_stmts(_recv, "그러셨군요.")   # (2026-10-21) 평서문만 대체, 되물음 보존
                logger.info("🔁 재생성 후에도 반복 → 평서문만 '그러셨군요.' 대체")
        # (2026-10-22 P1-3) '네'·'네, 감사해요' 류 동의만 보냈으면 되받기를 생략하고 바로 고정 질문.
        from diag_project.prompts.phase3a.layer3_state import is_consent_only as _consent_only
        _consent_in = _consent_only(request.content)
        if _smalltalk:
            if _consent_in:
                clean_reply = _pl_r("smalltalk_q")
                _tm["no_q_fix"] = "smalltalk_consent"
            elif not any(is_question_g(x) for x in split_sentences_g(_recv)):
                # 10/22 2턴 "그러셨군요." 단독 출력 차단 — 모든 코치 턴은 질문 하나로 끝난다
                clean_reply = f"{_recv} {_pl_r('smalltalk_q')}"
                _tm["no_q_fix"] = "smalltalk"
            else:
                clean_reply = _recv
        else:
            _fixed_q = _pl_r("role_q") if _rc == 2 else _pl_r("expect_q")   # 페르소나별 고정 질문
            clean_reply = _fixed_q if _consent_in else f"{_recv} {_fixed_q}"
            if _consent_in:
                _tm["no_q_fix"] = "consent_skip_receive"

    # 8-a. DIAGNOSIS_INTRO 하이브리드: LLM 되받기 한 문장 + 시스템 진단 안내 본문 합치기
    #   (2026-10-19) 기대 답변이 없으면 위에서 system_override_text(안내만)로 처리되어 여기 오지 않는다.
    if instruction_used == "DIAGNOSIS_INTRO" and not _suppress_mechanical_text and system_override_text is None:
        from diag_project.services.output_guard import receive_sentence as _recv_sent_i
        llm_acknowledgment = _recv_sent_i(clean_reply, fallback="")
        anchor_section = build_intro_anchor_section()
        clean_reply = f"{llm_acknowledgment}\n\n{anchor_section}".strip() if llm_acknowledgment else anchor_section

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
        # (2026-10-21) 인용 가드: '…' 인용구가 리더 정의(이번 발화)에 없으면 따옴표를 떼고 재생성 1회. 역량·하위역량 이름은 예외.
        from diag_project.services.output_guard import foreign_quotes as _fq, strip_quote_marks as _sqm
        _exempt_q = [COMPETENCY_FRAMEWORK.get(chapter, {}).get("name", "")] + list(state.get("all_subcompetencies") or [])
        _bad_q = _fq(clean_reply, request.content, exempt=_exempt_q)
        if _bad_q:
            _tm["quote"] = 1
            logger.info("🔒 ALIGN 인용 가드: 리더 정의에 없는 인용 %s → 따옴표 제거 후 재생성 1회", _bad_q)
            try:
                _q_regen = await _timed_regen(
                    system_prompt=system_prompt, chapter_context=chapter_context,
                    turn_state_text=turn_state_text + (
                        "\n\n🚨 [시스템 — 재생성 지시] 방금 응답이 리더님이 하지 않은 말(" + ", ".join(_bad_q)
                        + ")을 따옴표로 인용했습니다. 리더님 정의에 실제로 있는 어절만 인용하고, 없으면 인용 없이 다시 쓰세요."),
                    compressed_history=compressed_history, user_message=request.content, light_mode=True)
                _q_reply = _MARKER_RE.sub("", _q_regen.get("reply") or "").strip()
            except Exception as _e:
                logger.error("🔒 인용 재생성 실패: %s", _e)
                _q_reply = ""
            _bad_q2 = _fq(_q_reply, request.content, exempt=_exempt_q) if _q_reply else list(_bad_q)
            if _q_reply and not _bad_q2:
                clean_reply = _q_reply
            else:
                _tm["quote"] = 2
                clean_reply = _sqm(_q_reply or clean_reply, _bad_q2 or _bad_q)
                logger.info("🔒 재생성 후에도 외부 인용 → 따옴표 제거")
        # #2(2026-09-07): 정의 제시 → 빈 줄 → 첫 앵커 질문을 한 메시지로. "들어가
        #   볼까요?" → "네" 확인 턴(정보 없음) 제거. 타겟(asked)은 위 프로브 스텝에서
        #   LLM 호출 이전에 기록됐고, 여기서는 출력만 조립한다. 브릿지 리드 없이
        #   앵커 본문만 붙인다(정의 뒤라 리드가 어색).
        # (2026-10-28 P0-2) ALIGN 되받기의 내부 어휘 누설은 조립 '전'에 처리한다 — 조립 뒤 8-i 가 재생성하면 LLM 새 출력이
        #   정의·목록·다리·앵커를 통째로 덮었다(10/28 재생 1라운드: 챕터 2~4 ALIGN 목록 누락의 원인). 8-i 는 ALIGN 을 재생성하지 않는다.
        try:
            from diag_project.services.leak_lexicon import find_leaks as _fl_al, strip_leak_sentences as _sls_al
            _lk_al = _fl_al(clean_reply, _prev_user_texts + [request.content or ""])
        except Exception as _le_al:   # noqa: BLE001
            logger.warning("ALIGN 누설 검사 실패(무시): %s", _le_al)
            _lk_al = []
        if _lk_al:
            _tm["align_leak"] = list(_lk_al)
            logger.info("🛡️ ALIGN 되받기 내부 어휘 누설 %s → 재생성 1회", _lk_al)
            try:
                _al_regen = await _timed_regen(
                    system_prompt=system_prompt, chapter_context=chapter_context,
                    turn_state_text=turn_state_text + (
                        "\n\n🚨 [시스템 — 재생성 지시] 방금 응답에 코치가 리더님께 쓰는 말이 아닌 내부 용어가 있습니다: "
                        + ", ".join(str(x) for x in _lk_al[:6]) + ". 그 문장을 빼거나 리더님께 하는 자연스러운 말로 바꿔, "
                        "리더님 말을 받아 주는 평서문 2~3개만 다시 쓰세요."),
                    compressed_history=compressed_history, user_message=request.content, light_mode=True)
                _al_reply = _MARKER_RE.sub("", _al_regen.get("reply") or "").strip()
            except Exception as _e_al:   # noqa: BLE001
                logger.error("ALIGN 누설 재생성 실패: %s", _e_al)
                _al_reply = ""
            _lk_al2 = _fl_al(_al_reply, _prev_user_texts + [request.content or ""]) if _al_reply else list(_lk_al)
            if _al_reply and not _lk_al2:
                clean_reply = _al_reply
            else:
                clean_reply, _n_al = _sls_al(_al_reply or clean_reply, _lk_al2 or _lk_al)
                _tm["align_leak_stripped"] = _n_al
        if chapter and current_target_sub:
            # (2026-10-28 P0-1) ALIGN 조립은 백엔드 결정론(services/align_render.render_align):
            #   [LLM 공감 되받기 2~3문장] + [고정 정의 1문장] + [목록 · 줄 전부] + [고정 안내] + [고정 다리] + [앵커 1개].
            #   LLM 출력의 질문·목록·다른 챕터 문구·선택 넘기기 문장은 전부 제거. 고정 문장은 페르소나 어미. 챕터 크기와 무관하게 같은 렌더러.
            _anchor = build_chapter_opening_with_user_def(
                chapter=chapter,
                user_definition=request.content or "",
                first_subcompetency_name=current_target_sub,
                bridge_context=None,
                variant=int((session.self_assessment_data or {}).get("anchor_variant") or 0),
            )
            # (2026-10-21) ANCHOR_RENDER=llm 이면 렌더링 질문으로(판정 불합격·실패는 사전 문장 폴백). dict 모드는 그대로(어미 변환 포함).
            _ar_q, _ar_mode = await _render_anchor_for(current_target_sub)
            _tm["anchor_render"] = _ar_mode
            _anchor = _ar_q if _ar_mode in ("llm", "dict", "fallback") else _anchor
            from diag_project.services.output_guard import strip_frame_lead
            from diag_project.data.competencies import find_sub_key_by_name as _fsk_ab
            from diag_project.services.align_render import align_shape_ok as _aso, render_align as _ra
            _anchor = strip_frame_lead(_anchor)
            # 조립은 모든 후처리(8-i 가드·8-n 입버릇·8-h 느낌표 …)가 끝난 뒤 '마지막'에 한다 — 중간 단계의 재생성이
            #   조립 결과를 덮지 못하게(10/28 재생 1~3라운드: 8-i·8-n·8-h 재생성이 각각 ALIGN 목록을 지웠다).
            #   여기서는 재료만 보관하고, clean_reply 는 LLM 되받기 원문 그대로 가드를 통과시킨다.
            _align_ctx = dict(
                sub_names=list(state.get("all_subcompetencies") or []),
                persona_name=(state.get("coach_persona") or {}).get("name"),
                bridge_sub_key=_fsk_ab(chapter, current_target_sub), bridge_sub_name=current_target_sub,
                anchor=_anchor, user_text=request.content or "",
            )
            del _ra, _aso
            # 다음 턴 decider 가 CHAPTER_OPENING 을 다시 내지 않도록 원장에 표식.
            _st_om = dict(session.self_assessment_data or {})
            _om = dict(_st_om.get("opening_merged") or {})
            _om[chapter] = True
            _st_om["opening_merged"] = _om
            session.self_assessment_data = _st_om
            from sqlalchemy.orm.attributes import flag_modified as _fm_om
            _fm_om(session, "self_assessment_data")
            await db.flush()   # (2026-09-22) 턴 끝 1회 커밋 — 중간 커밋 폐지

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
        from diag_project.services.intro_messages import final_closing_message
        if _next_ch:
            # (2026-10-21) '여기까지 충분히 들었습니다' 대신 들은 것 요약 2문장(LLM, 사실만) + 고정 다리.
            #   질문·칭찬·상태 누설 문장은 걷어내고 두 문장으로 자른다. 남는 게 없으면 중립 문장.
            from diag_project.services.intro_messages import chapter_end_bridge
            from diag_project.services.output_guard import drop_question_sentences as _dqs_e, split_sentences as _ss_e
            from diag_project.services.output_guard import strip_praise as _sp_e, strip_state_leak as _ssl_e
            _sum, _ = _dqs_e(clean_reply)
            _sum, _ = _sp_e(_sum)
            _sum, _ = _ssl_e(_sum)
            from diag_project.services.output_guard import strip_transition_sentences as _sts_e
            _sum, _ = _sts_e(_sum)          # (2026-10-22 P1-3) LLM 이 '이어가 보겠습니다' 를 쓰면 고정 다리와 중복 → 제거
            _sum = " ".join([x.strip() for x in _ss_e(_sum) if x.strip()][:2]).strip()
            # (2026-10-29 P1-6) 요약이 남지 않으면 다리 문장만 — 과거 폴백 '여기서 정리하겠습니다'는 상태 보고문이었다.
            wrap_up = f"{_sum} {chapter_end_bridge(chapter_to_topic(_next_ch), (state.get('coach_persona') or {}).get('name'))}".strip()
        else:
            wrap_up = final_closing_message((state.get("coach_persona") or {}).get("name"))
        if not _next_ch:
            # (2026-09-29, A-4) 리포트 예상 시간: 이미 사전분석된(또는 진행 중인) 이전 챕터 수로 계산. 실패하면 문구 없이.
            try:
                from diag_project.routes.reports import load_analysis_inputs
                from diag_project.llm_service import GeminiService as _GS, _get_competency_keys as _gck
                from diag_project.services.report_prewarm import estimate_label, inflight_elapsed
                _inp = await load_analysis_inputs(db, session)
                _infl = inflight_elapsed(str(session.id))
                _n_ready = sum(1 for _k in _gck() if _k != chapter and (
                    _k in _infl or _GS.chapter_deep_cached(_inp["history"], _inp["chapter_transcripts"], _inp["asked_subs"], _k,
                                                           provider=session.llm_provider)))
                wrap_up = f"{wrap_up} 리포트는 {estimate_label(_n_ready)} 정도면 준비됩니다."
            except Exception as _ee:
                logger.warning("리포트 예상 시간 계산 실패(문구 생략): %s", _ee)
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
        _last_model_msg = next((m for m in reversed(history_messages)
                                if (m.role == MessageRole.MODEL or m.role == "model")), None)
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
                "완전히 동일합니다. 같은 문장을 다시 쓰지 마세요. 요약하는 첫 문장 없이, "
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
    #     (2) (2026-09-22) 되받기 리드·전환 문장은 자르지 않는다 — 자른 문장이 어색하다(4번). 관찰 항목으로만 guard_log 에 남는다.
    #   프로브 턴이 끝까지 질문 없이 남으면 결과 질문 풀이 아니라 현재 타겟 템플릿 앵커(연결 절 포함).
    #   부재 폴백 턴(ABSENCE_PROBE)·템플릿 턴은 가드 대상 아님. 모든 결과는 guard_log 에 남는다.
    #   후처리 단계 전체 표: docs/postprocess_pipeline.md — 프롬프트 규칙을 추가할 때 이 표와 대조한다.
    if system_override_text is None and not _llm_error and clean_reply and instruction_used != "ABSENCE_PROBE":
        from diag_project.services.output_guard import (
            TRANSITION_ALLOWED_INSTRUCTIONS, find_praise, find_sub_names, has_question, has_transition_claim,
            off_target_overlap, split_sentences, strip_praise, strip_sub_name_mentions,
            template_anchor, cap_lead_sentences, same_question_as_previous,
            find_revisit_greeting, strip_revisit_greeting, find_state_leak, strip_state_leak,
        )
        _guard_replaced = False   # (2026-10-21) 교정이 응답을 템플릿 앵커로 통째 교체했는가 — 8-j 앵커 접착이 건너뛴다
        from diag_project.services.output_guard import is_question as is_question_sentence
        # (2026-10-16) 재방문 인사 가드는 같은 자리 안에서만. 자리가 바뀐 뒤 첫 턴(재개: 이번 자리 메시지가 방금 저장한
        #   사용자 메시지 하나뿐)에는 "다시 뵙게 되어" 가 정당하므로 제외한다.
        _resumed_sitting = (_sit_n <= 1 and len(history_messages) > 1)
        # _prev_coach_text / _recent_coach_texts 는 히스토리 로드 직후 계산됨(2026-09-22)

        def _anchor_fallback() -> str:
            """교정 폴백 문장: 현재 타겟 템플릿 앵커(연결 절). 그 앵커가 직전 2턴에 이미 나갔으면(리플레이 F 16·11턴 —
            폴백이 폴백을 반복) 결과 질문 풀에서 안 쓴 문장으로."""
            from diag_project.services.output_guard import norm_sentence as _ns_fb
            nonlocal session
            # (2026-09-29) 직전 2턴이 아니라 이 챕터에서 한 번이라도 나간 앵커면 반복하지 않는다
            _ch_coach_texts = " ".join((m.content or "") for m in history_messages
                                       if (m.role == MessageRole.MODEL or m.role == "model") and m.chapter == chapter)
            # (2026-10-28 P0-3) 사전 앵커 폴백도 페르소나 어미를 거친다(운영에서 6명 동일 앵커의 주 원인).
            if _tgt_q and chapter and _ns_fb(_tgt_q) not in _ns_fb(_ch_coach_texts + " " + " ".join(_recent_coach_texts)):
                return _voiced_q(template_anchor(_tgt_q))
            if chapter:
                from diag_project.services.output_guard import result_fallback_question as _rfq
                _alt = sum(1 for _t in _recent_coach_texts if "그 뒤에는 어떻게 됐어요" in _t)   # 직전 폴백이 A 면 B
                return _rfq((state.get("resume_pending") or {}).get("user_text") or request.content, _prev_user_text, alt=_alt,
                            persona=(state.get("coach_persona") or {}).get("name"))
            return _voiced_q(template_anchor(_tgt_q))
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
            if not _resumed_sitting:
                rv = find_revisit_greeting(txt)
                if rv:
                    v["revisit"] = rv
            sl = find_state_leak(txt)
            if sl:
                v["state_leak"] = sl        # (2026-10-21) '새로운 사례를 들려주셨네요'·'충분히 들었습니다' 류 상태 누설
            # (2026-10-28 P0-2) 내부 어휘 누설 — 프롬프트 템플릿에서 자동 추출한 사전(services/leak_lexicon, 린트와 동일).
            #   리더가 쓴 어절 되받기는 제외. 재생성 1회 → 그래도 남으면 그 문장 삭제(질문 보존).
            try:
                from diag_project.services.leak_lexicon import find_leaks as _find_leaks
                lk = _find_leaks(txt, _prev_user_texts + [request.content or ""])
                lk = [w for w in lk if w not in (sl or [])]
                if lk:
                    v["leak"] = lk
            except Exception as _le:   # noqa: BLE001 — 사전 로드 실패가 턴을 막지 않게
                logger.warning("누설 사전 검사 실패(무시): %s", _le)
            if instruction_used not in TRANSITION_ALLOWED_INSTRUCTIONS and has_transition_claim(txt):
                v["transition"] = True
            if _is_anchor:
                nm = find_sub_names(txt, _all_names)
                if nm:
                    v["names"] = nm
                # (2026-10-21) anchor_missing 폐지 — 앵커 질문은 LLM 이 아니라 시스템이 붙인다(8-j).
                off, oq = off_target_overlap(txt, _asked_qs)
                if off:
                    v["off_target"] = oq
            elif _is_probe:
                nm = find_sub_names(txt, _all_names)
                if nm:
                    v["names_mention"] = nm
            if _is_probe and not _is_anchor:
                # (2026-10-21) 전환 턴(_is_anchor)은 LLM 이 질문을 쓰지 않으므로 질문 검사 제외 — 앵커는 8-j 가 붙인다.
                # (2026-09-22, 4번) 되받기·'네' 시작·리드 겹침은 더 이상 위반이 아니다(자르지 않는다). 관찰용으로만 센다.
                leads = []
                for _s2 in split_sentences(txt):
                    if is_question_sentence(_s2):
                        break
                    leads.append(_s2)
                if leads and (is_recap_turn(leads[0], request.content) or starts_with_ne_recap(leads[0])):
                    v["recap_obs"] = True
                if not has_question(txt):
                    v["no_question"] = True
                _sq = same_question_as_previous(txt, _prev_coach_text)
                if _sq:
                    v["same_question"] = _sq[:60]
                from diag_project.services.output_guard import bare_demonstrative_questions as _bdq
                _bare = _bdq(txt, request.content)
                if _bare:
                    v["bare_ref"] = _bare[0][:60]
            return v

        _v = _violations(clean_reply)
        _tm["violations"] = dict(_v)
        # (2026-09-18 A/B 측정) recap·lead_stack·praise·transition·ne_opening 은 재생성해도 대부분 그대로 남는다
        #   (19턴 중 recap 12 → 재생성 후 11 잔존) → 재생성 없이 바로 교정. 재생성은 문장 교체가 어색한
        #   names·off_target 과, 출력 자체에 질문이 없는 no_question·same_question 에만.
        _REGEN_KEYS = {"names", "off_target", "no_question", "same_question", "bare_ref", "anchor_missing", "leak"}
        # (2026-10-28 P0-1) ALIGN 은 재생성하지 않는다 — 조립(정의·목록·다리·앵커)을 LLM 새 출력이 덮는다. 남은 위반은 하드 교정만.
        _need_regen = bool(set(_v) & _REGEN_KEYS) and instruction_used != "COMPETENCY_ALIGN"
        if _v and not _need_regen:
            logger.info("🛡️ 출력 가드 위반(재생성 생략): %s (instr=%s)", _v, instruction_used)
        if _need_regen:
            logger.info("🛡️ 출력 가드 위반: %s (instr=%s) → 재생성 1회", _v, instruction_used)
            _notes = ["\n\n🚨 [시스템 — 재생성 지시] 방금 만든 응답에 다음 위반이 있습니다. 내용은 유지하되 고쳐 다시 쓰세요."]
            if "praise" in _v:
                _notes.append(f"- 평가적 칭찬 금지: {', '.join(_v['praise'])} 같은 표현을 빼세요. 인정은 사실 확인('그 결정을 내리셨군요')까지.")
            if "transition" in _v:
                _notes.append("- 이번 턴은 영역을 마치거나 다음 챕터로 넘어가는 턴이 아닙니다. 전환·마무리 선언 문장을 빼고 질문으로 이어가세요.")
            if "revisit" in _v:
                _notes.append(f"- 첫 세션(같은 자리)입니다. {', '.join(_v['revisit'])} 같은 재방문·재회 인사를 빼세요.")
            if "names" in _v or "off_target" in _v or "names_mention" in _v:
                _notes.append("- 하위역량 이름을 말하지 말고, 이미 다룬 사건·주제를 다시 묻지 마세요."
                              + (f" 이번 앵커 질문 본문: {_tgt_q}" if (_tgt_q and _is_anchor) else ""))
            if "no_question" in _v:
                _notes.append("- 응답에 질문이 없습니다. 반드시 리더님께 묻는 질문 한 문장으로 끝내세요.")
            if "same_question" in _v:
                _notes.append("- 직전 턴과 같은 질문을 되묻고 있습니다. 리더님이 방금 답한 내용에서 한 걸음 더 들어가는 다른 질문을 하세요.")
            if "anchor_missing" in _v:
                _notes.append(f"- 이번 턴은 새 주제로 넘어가는 턴입니다. 직전 사건을 더 묻지 말고 이 질문의 주제로 넘어가세요: {_tgt_q} "
                              "(주제가 이어지지 않으면 '다른 이야기를 하나 여쭤볼게요.' 한 문장 후 질문)")
            if "bare_ref" in _v:
                _notes.append("- 질문이 '그것·그럴 때·그렇게'로만 대상을 가리킵니다. 리더님이 방금 쓴 말(명사구)을 질문에 넣어 무엇을 묻는지 분명히 하세요.")
            if "leak" in _v:
                _notes.append("- 다음 말은 코치가 리더님께 쓰는 말이 아니라 내부 용어입니다: " + ", ".join(str(x) for x in _v["leak"][:6])
                              + ". 그 문장을 빼거나 리더님께 하는 자연스러운 말로 바꾸세요. 진행 상태·방법을 설명하지 말고 대화만 하세요.")
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
        _OBS_ONLY = {"recap_obs", "transition"}
        if _v and (set(_v) - _OBS_ONLY):
            _tm["hard"] = True
            logger.info("🛡️ 출력 가드 하드 교정: %s", _v)
        elif _v:
            _tm["hard"] = False
            logger.info("🛡️ 출력 가드 관찰(교정 없음): %s", _v)
        if _v and (set(_v) - _OBS_ONLY):
            if ("names" in _v or "off_target" in _v) and _tgt_q:
                clean_reply = _anchor_fallback()
                _guard_replaced = True
                _v = {}
            if "anchor_missing" in _v and _tgt_q:
                from diag_project.services.output_guard import ANCHOR_TRANSITIONS as _ATR
                clean_reply = f"{_ATR[len(asked_for_chapter(session.self_assessment_data, chapter) or []) % len(_ATR)]} {_tgt_q}"
                logger.info("🧭 앵커 미발화 → 전환 문장 + 템플릿 앵커")
            if "same_question" in _v and chapter:
                # 재생성 후에도 직전 턴과 같은 질문 → 타겟 앵커(직전 2턴에 없을 때) 또는 결과 질문(풀)으로 한 걸음 전진.
                clean_reply = _anchor_fallback()
                _guard_replaced = True
                logger.info("🛡️ 직전 턴과 같은 질문 → 교체: %s", clean_reply[:60])
            if "names_mention" in _v:
                _c2, _n = strip_sub_name_mentions(clean_reply, _all_names)
                if has_question(_c2) or not has_question(clean_reply):
                    clean_reply = _c2
            if "praise" in _v:
                _c2, _n = strip_praise(clean_reply)   # 마지막 질문 문장은 보존하는 함수
                if has_question(_c2) or not has_question(clean_reply):
                    clean_reply = _c2
            if "revisit" in _v:
                _c2, _n = strip_revisit_greeting(clean_reply)   # 재방문 인사 문장 제거(질문 보존)
                if _c2.strip() and (has_question(_c2) or not has_question(clean_reply)):
                    clean_reply = _c2
                    logger.info("🛡️ 재방문 인사 %d문장 제거", _n)
            if "state_leak" in _v:
                _c2, _n = strip_state_leak(clean_reply)   # 상태 누설 문장 제거(질문 보존)
                if _c2.strip() and (has_question(_c2) or not has_question(clean_reply)):
                    clean_reply = _c2
                    logger.info("🛡️ 상태 누설 %d문장 제거", _n)
            if "leak" in _v:
                # (2026-10-28 P0-2) 재생성 후에도 내부 어휘가 남으면 그 문장을 지운다(질문 문장이면 어절만 뗀다)
                from diag_project.services.leak_lexicon import strip_leak_sentences as _sls
                _c2, _n = _sls(clean_reply, list(_v["leak"]))
                if _c2.strip() and (has_question(_c2) or not has_question(clean_reply)):
                    clean_reply = _c2
                    _tm["leak_stripped"] = _n
                    logger.info("🛡️ 내부 어휘 누설 %d문장 제거: %s", _n, _v["leak"])
            if "bare_ref" in _v and _is_probe:
                from diag_project.services.output_guard import bare_demonstrative_questions as _bdq2, result_fallback_question as _rfq2
                from diag_project.services.output_guard import followup_from_user as _ffu
                for _bq in _bdq2(clean_reply, request.content):
                    clean_reply = clean_reply.replace(_bq, _rfq2(request.content, _prev_user_text, alt=len(_recent_coach_texts), persona=(state.get("coach_persona") or {}).get("name")) if state.get("force_result_probe")
                                                      else _ffu(request.content), 1)
                    logger.info("🧹 대명사 단독 질문 교체: %s", _bq[:40])
            # (2026-09-22, 4번) 전환 선언·되받기 리드는 자르지 않는다 — 자른 문장이 어색하다. 위반은 guard_log 에만 남는다.
            # 최종 보장: 프로브 턴에 질문이 없으면 현재 타겟 템플릿 앵커(결과 질문 풀 대체는 폐기 — 같은 문장 반복 사고).
            if _is_probe and not _is_anchor and not has_question(clean_reply.strip()) and _tgt_q:
                clean_reply = _anchor_fallback()
                _guard_replaced = True
                logger.info("🛡️ 질문 없는 출력 → 현재 타겟 템플릿 앵커(직전 2턴에 있으면 결과 질문)")

        # (2026-09-29) 앵커 턴의 상투적 다리('그런 경험처럼,') 제거 → 전환 문장
        if _is_anchor:
            from diag_project.services.output_guard import strip_filler_bridge as _sfb
            clean_reply, _fb_hit = _sfb(clean_reply)
            if _fb_hit:
                logger.info("🌉✂️ 앵커 군말 다리 제거 → 전환 문장")

        # (2026-10-22 P1-2) 결과 강제 턴 + 정도 부사·숫자 없음 → 수치 질문 우선(LLM 질문이 수치를 묻지 않으면 교체)
        if (_is_probe and not _is_anchor and not _llm_error and not _guard_replaced
                and state.get("force_result_probe") and state.get("result_quantify")):
            from diag_project.services.intro_messages import persona_line as _pl_q
            from diag_project.services.output_guard import is_quantify_question as _isq
            _qs_now = [x for x in split_sentences(clean_reply) if is_question_sentence(x)]
            if not _qs_now or not _isq(_qs_now[-1]):
                _lead_q = [x for x in split_sentences(clean_reply) if not is_question_sentence(x)][:1]
                clean_reply = " ".join(_lead_q + [_pl_q((state.get("coach_persona") or {}).get("name"), "quantify")]).strip()
                _tm["quantify"] = 1
                logger.info("📏 정도 부사·숫자 없음 → 수치 질문으로 교체")

        # (2026-10-21) 탐침 품질 — 프로브 턴(전환 턴 제외): 한 턴 한 질문(마지막만) · 시점 문형 · 의미 반복 flash 판정 1회
        if _is_probe and not _is_anchor and not _llm_error and not _guard_replaced:
            from diag_project.services.output_guard import fix_moment_question as _fmq, keep_last_question as _klq
            clean_reply, _n_q = _klq(clean_reply)
            if _n_q:
                _tm["one_q"] = _n_q
                logger.info("✂️ 한 턴 한 질문: 앞선 질문 %d문장 제거", _n_q)
            clean_reply, _n_m = _fmq(clean_reply)
            if _n_m:
                _tm["moment"] = _n_m
            # (2026-10-22 P2-3) 되받기 상한을 페르소나별로(Ella·Daniel 2, Jessica·Lucas 1, Olivia·Michael 2) — 관찰 문장 우선 보존
            from diag_project.services.output_guard import cap_leads_persona as _clp, persona_lead_cap as _plc2
            clean_reply, _n_cap = _clp(clean_reply, _plc2((state.get("coach_persona") or {}).get("name")), _llm_user_text)
            if _n_cap:
                _tm["lead_cap"] = _n_cap
            # (2026-10-22 P2-2) 감정·표정·마음속 질문은 챕터당 1회 — 초과면 재생성 1회, 그래도면 행동 질문으로 교체
            from diag_project.services.output_guard import is_emotion_question as _ieq
            from diag_project.services.intro_messages import persona_line as _pl_a
            from diag_project.services.traversal import is_action_probe_text as _iapt
            _AFQ = _pl_a((state.get("coach_persona") or {}).get("name"), "action")   # 페르소나별 행동 질문
            _eq_store = dict(session.self_assessment_data or {})
            _eq_n = int((_eq_store.get("emotion_q_count") or {}).get(chapter, 0) or 0)
            _cur_q = next((x for x in reversed(split_sentences(clean_reply)) if is_question_sentence(x)), "")
            # (2026-10-23 P3) 감정·표정·마음 질문은 S-A-R 미완일 때만, 챕터당 1회 — 완비·사다리 턴이면 바로 교체 대상
            if _cur_q and _ieq(_cur_q) and (_eq_n >= 1 or state.get("sar_complete_answer") or state.get("force_ladder_probe")):
                _tm["emotion"] = 1
                _e_txt = ""
                try:
                    _e_out = await _timed_regen(
                        system_prompt=system_prompt, chapter_context=chapter_context,
                        turn_state_text=turn_state_text + (
                            "\n\n🚨 [시스템 — 재생성 지시] 이 영역에서 감정·표정·마음을 묻는 질문은 이미 한 번 했습니다. "
                            "이번 질문은 리더님이 그때 직접 한 행동이나 그 뒤의 결과를 묻는 질문 하나로 다시 쓰세요."),
                        compressed_history=compressed_history, user_message=_llm_user_text, light_mode=True)
                    _e_txt = _MARKER_RE.sub("", _e_out.get("reply") or "").strip()
                except Exception as _e:
                    logger.error("감정 질문 재생성 실패: %s", _e)
                _e_q = next((x for x in reversed(split_sentences(_e_txt)) if is_question_sentence(x)), "") if _e_txt else ""
                if _e_q and not _ieq(_e_q):
                    clean_reply, _ = _klq(_e_txt)
                else:
                    _tm["emotion"] = 2
                    _lead_e = [x for x in split_sentences(clean_reply) if not is_question_sentence(x)][:1]
                    clean_reply = " ".join(_lead_e + [_AFQ]).strip()
                    logger.info("💭 감정 질문 초과 → 행동 질문으로 교체")
            # (2026-10-23 6번 보정) 대조 도입구는 실제 대조 질문에만. 대조 탐침은 챕터당 1회 — 초과면 재생성 1회, 그래도면 행동 질문으로.
            from diag_project.services.persona_voice import is_contrast_question as _icq, strip_contrast_lead as _scl
            clean_reply, _n_lead = _scl(clean_reply)
            if _n_lead:
                _tm["contrast_lead_fix"] = _n_lead
            _cq_now = next((x for x in reversed(split_sentences(clean_reply)) if is_question_sentence(x)), "")
            _cq_cnt = int(((session.self_assessment_data or {}).get("contrast_q_count") or {}).get(chapter, 0) or 0)
            if _cq_now and _icq(_cq_now) and _cq_cnt >= 1:
                _tm["contrast_fix"] = 1
                _c_txt = ""
                try:
                    _c_out = await _timed_regen(
                        system_prompt=system_prompt, chapter_context=chapter_context,
                        turn_state_text=turn_state_text + (
                            "\n\n🚨 [시스템 — 재생성 지시] 이 영역에서 '반대로 했다면' 식 대조 질문은 이미 한 번 했습니다. "
                            "이번 질문은 리더님이 그때 직접 한 행동이나 그 뒤의 결과를 묻는 질문 하나로 다시 쓰세요."),
                        compressed_history=compressed_history, user_message=_llm_user_text, light_mode=True)
                    _c_txt = _MARKER_RE.sub("", _c_out.get("reply") or "").strip()
                except Exception as _e:
                    logger.error("대조 질문 재생성 실패: %s", _e)
                _c_q = next((x for x in reversed(split_sentences(_c_txt)) if is_question_sentence(x)), "") if _c_txt else ""
                if _c_q and not _icq(_c_q):
                    clean_reply, _ = _klq(_scl(_c_txt)[0])
                else:
                    _tm["contrast_fix"] = 2
                    _lead_c = [x for x in split_sentences(clean_reply) if not is_question_sentence(x)][:1]
                    clean_reply = " ".join(_lead_c + [_AFQ]).strip()
                    logger.info("🔁 대조 질문 초과 → 행동 질문으로 교체")
            # (2026-10-22 P2-2) A 강제 턴인데 행동 질문이 아니면 고정 행동 질문으로
            _cur_q2 = next((x for x in reversed(split_sentences(clean_reply)) if is_question_sentence(x)), "")
            if state.get("force_action_probe") and not _iapt(_cur_q2):
                _lead_a = [x for x in split_sentences(clean_reply) if not is_question_sentence(x)][:1]
                clean_reply = " ".join(_lead_a + [_AFQ]).strip()
                _tm["action_fix"] = 1
                logger.info("🎯 A 강제 턴에 행동 질문 없음 → 고정 행동 질문")
            # (2026-10-23, 4-1) 일반화 탐침 턴: 되받기 1문장 + 페르소나별 "그중 가장 최근 일 하나만요" (LLM 질문은 버린다)
            if state.get("force_generalize_probe"):
                _lead_g = [x for x in split_sentences(clean_reply) if not is_question_sentence(x)][:1]
                clean_reply = " ".join(_lead_g + [_pl_a((state.get("coach_persona") or {}).get("name"), "generalize")]).strip()
                _tm["generalize"] = 1
                logger.info("🧭 일반화 탐침 질문 삽입")
            # (2026-10-23 P3) 사다리 탐침 턴: 되받기 1문장 + 사전 질문(현재 레벨 +1). LLM 질문은 버린다.
            if state.get("force_ladder_probe"):
                _lp = state["force_ladder_probe"]
                _lead_l = [x for x in split_sentences(clean_reply) if not is_question_sentence(x)][:1]
                from diag_project.services.persona_voice import voice_question as _vq_l
                clean_reply = " ".join(_lead_l + [_vq_l((state.get("coach_persona") or {}).get("name"), _lp["q"],
                                                        variant=int(((session.self_assessment_data or {}).get("voice_variant_count") or {}).get(chapter, 0) or 0))]).strip()
                _tm["voiced"] = 1
                _tm["ladder"] = _lp["step"]
                logger.info("🪜 사다리 질문 삽입 [%s] %s", _lp.get("sub"), _lp["step"])
            # (2026-10-29 P1-2) '리더님이 직접 하신 일' 질문 상한 — 하위역량당 1회, 답에 행동(A)이 이미 있으면 묻지 않는다.
            #   초과·불필요면 결과 질문(페르소나 폴백)으로 교체. s28 운영: Jessica 5회·Michael 5회(공격적으로 들림).
            from diag_project.services.output_guard import is_direct_action_question as _idaq, result_fallback_question as _rfq_d
            _dq_now = next((x for x in reversed(split_sentences(clean_reply)) if is_question_sentence(x)), "")
            if _dq_now and _idaq(_dq_now) and not state.get("force_ladder_probe"):
                _dqc = ((session.self_assessment_data or {}).get("direct_q_count") or {}).get(chapter) or {}
                _dq_used = int(_dqc.get(current_target_sub or "", 0) or 0)
                _a_present = bool((state.get("current_event_star_coverage") or {}).get("A"))
                if _dq_used >= 1 or _a_present:
                    _lead_d = [x for x in split_sentences(clean_reply) if not is_question_sentence(x)][:1]
                    _alt_d = sum(1 for _t in _recent_coach_texts if "그 뒤에는 어떻게 됐어요" in _t)
                    clean_reply = " ".join(_lead_d + [_rfq_d(request.content, _prev_user_text, alt=_alt_d,
                                                              persona=(state.get("coach_persona") or {}).get("name"))]).strip()
                    _tm["direct_q_fix"] = "a_present" if _a_present else "cap"
                    logger.info("🧭 '직접 하신' 질문 교체(%s): [%s] %s", _tm["direct_q_fix"], chapter, current_target_sub)
                else:
                    _tm["direct_q"] = 1
            _new_q = next((x for x in reversed(split_sentences(clean_reply)) if is_question_sentence(x)), "")
            _prev_qs = [x for t in _recent_coach_texts for x in split_sentences(t) if is_question_sentence(x)]
            if _new_q and _prev_qs:
                from diag_project.services.llm_judge import same_question_as_recent as _sqr
                if await _sqr(llm, _new_q, _prev_qs) is True:
                    _tm["semrep"] = 1
                    logger.info("🔁 의미 반복 판정: %r → 재생성 1회", _new_q[:50])
                    _r_txt = ""
                    try:
                        _r_out = await _timed_regen(
                            system_prompt=system_prompt, chapter_context=chapter_context,
                            turn_state_text=turn_state_text + (
                                "\n\n🚨 [시스템 — 재생성 지시] 방금 질문이 직전 턴에서 이미 물은 것과 같은 것을 묻고 있습니다. "
                                "같은 대상·시점·행동을 다시 묻지 말고, 리더님이 방금 답한 내용에서 한 걸음 더 들어가는 다른 질문 하나로 다시 쓰세요."),
                            compressed_history=compressed_history, user_message=request.content, light_mode=True)
                        _r_txt = _MARKER_RE.sub("", _r_out.get("reply") or "").strip()
                    except Exception as _e:
                        logger.error("🔁 의미 반복 재생성 실패: %s", _e)
                    _r_txt, _ = _klq(_r_txt)
                    _r_txt, _ = _fmq(_r_txt)
                    _r_q = next((x for x in reversed(split_sentences(_r_txt)) if is_question_sentence(x)), "")
                    if _r_q and await _sqr(llm, _r_q, _prev_qs) is not True:
                        clean_reply = _r_txt
                    else:
                        _tm["semrep"] = 2
                        clean_reply = _anchor_fallback()
                        logger.info("🔁 재생성 후에도 의미 반복 → 다음 앵커: %s", clean_reply[:60])

        # 8-j. (2026-10-21) 전환 턴(STAR_COMPLETE_NEW_EVENT) 앵커 접착 — LLM 본문(되받기+다리, 질문 제거, 최대 2문장) + 시스템 앵커 1개.
        #   본문이 전환 문장뿐('이번엔 조금 다른 장면입니다' 단독)이면 재생성 1회, 그래도면 전환 문장만. 모드·폴백은 guard_log.
        if _is_anchor and not _llm_error and not _guard_replaced:
            from diag_project.services.output_guard import ANCHOR_TRANSITIONS as _ATR_j
            from diag_project.services.output_guard import drop_question_sentences as _dqs_j, is_transition_only as _ito

            def _body_of(txt: str) -> str:
                _b, _ = _dqs_j(txt)
                return " ".join([x.strip() for x in split_sentences(_b) if x.strip()][:2])

            _body = _body_of(clean_reply)
            if state.get("skip_bridge"):
                # (2026-10-29 P1) 입력 이상 3회째 전진 턴 — 본문은 고정 '이 항목은 여기까지 듣고 넘어갈게요' 한 문장
                _body = state["skip_bridge"]
                _tm["skip_bridge"] = 1
            elif _ito(_body):
                _tm["bridge"] = 1
                logger.info("🌉 전환 턴 본문이 전환 문장뿐(되받기 없음) → 재생성 1회")
                _b2 = ""
                try:
                    _b_out = await _timed_regen(
                        system_prompt=system_prompt, chapter_context=chapter_context,
                        turn_state_text=turn_state_text + (
                            "\n\n🚨 [시스템 — 재생성 지시] 리더님 말을 받는 첫 문장 없이 전환 문장만 냈습니다. 방금 리더님 답변의 핵심 사실 한 문장을 먼저 쓰고, "
                            "그 뒤에 다리 한 문장. 질문은 쓰지 마세요."),
                        compressed_history=compressed_history, user_message=request.content, light_mode=True)
                    _b2 = _body_of(_MARKER_RE.sub("", _b_out.get("reply") or ""))
                except Exception as _e:
                    logger.error("🌉 전환 재생성 실패: %s", _e)
                if _b2 and not _ito(_b2):
                    _body = _b2
                else:
                    _tm["bridge"] = 2
                    _body = _ATR_j[0]
            # (2026-10-22 P2-3) 다리 문장 필수 — 되받기만 있으면 페르소나별 다리 한 문장을 붙인다(단독 전환 문장 금지).
            _stm_n = len([x for x in split_sentences(_body) if x.strip()])
            if _stm_n < 2:
                from diag_project.services.intro_messages import transition_bridge as _tbr
                _body = f"{_body} {_tbr((state.get('coach_persona') or {}).get('name'), len(asked_for_chapter(session.self_assessment_data, chapter) or []))}".strip()
                _tm["bridge_added"] = 1
            _ar_q, _ar_mode = await _render_anchor_for(current_target_sub)
            _tm["anchor_render"] = _ar_mode
            clean_reply = f"{_body} {_ar_q}".strip()

        # (2026-09-29) 태도 진술 계기 질문 턴: '계기'를 묻지 않았으면 질문 문장을 계기 질문으로(리드 1문장 유지)
        if state.get("attitude_trigger") and "계기" not in clean_reply:
            from diag_project.services.event_tracker import ATTITUDE_TRIGGER_QUESTION as _ATQ
            _lead_t = [x for x in split_sentences(clean_reply) if not is_question_sentence(x)][:1]
            clean_reply = " ".join(_lead_t + [_ATQ]).strip()
            if _tm.get("ladder"):   # (2026-10-29 P1) 사다리 질문이 덮였다 — 원장에 사용으로 남기지 않는다(p11 샘플: 계기 질문이 사다리로 집계)
                _tm.pop("ladder", None); _tm["ladder_dropped"] = "attitude"; state["force_ladder_probe"] = None
            logger.info("🌱 계기 질문 강제")

        # (2026-09-29) 결과 강제 턴에 결과 질문이 없으면 → 직전 발화 명사구로 만든 결과 질문(풀 문장 X)
        if state.get("force_result_probe") and _is_probe and not is_result_probe_text(
                " ".join(q for q in split_sentences(clean_reply) if is_question_sentence(q))):
            # 먼저 재생성 1회 — 리더의 말(감정·판단)에서 출발한 결과 질문을 LLM 이 만들게 한다(듣기 우선).
            try:
                _rr = await _timed_regen(
                    system_prompt=system_prompt, chapter_context=chapter_context,
                    turn_state_text=turn_state_text + (
                        "\n\n🚨 [시스템 — 재생성 지시] 이번 턴은 결과(R)를 물어야 하는데 결과 질문이 없습니다. "
                        "리더님이 방금 한 말(감정·판단·장면)에서 출발해, 그 일 뒤에 무엇이 어떻게 됐는지 묻는 한 문장으로 끝내세요. "
                        "리더님이 쓴 말을 문장에 넣고 '그것·그럴 때'만으로 가리키지 마세요."),
                    compressed_history=compressed_history, user_message=request.content, light_mode=True,
                )
                _rr_txt = _MARKER_RE.sub("", _rr.get("reply") or "").strip()
            except Exception:
                _rr_txt = ""
            if _rr_txt and is_result_probe_text(" ".join(q for q in split_sentences(_rr_txt) if is_question_sentence(q))):
                clean_reply, _ = cap_lead_sentences(_rr_txt)
                logger.info("🎯 결과 질문 재생성 채택: %s", clean_reply[-60:])
        if state.get("force_result_probe") and _is_probe and not is_result_probe_text(
                " ".join(q for q in split_sentences(clean_reply) if is_question_sentence(q))):
            from diag_project.services.output_guard import result_fallback_question as _rfq3
            _lead3 = [x for x in split_sentences(clean_reply) if not is_question_sentence(x)][:1]
            clean_reply = " ".join(_lead3 + [_rfq3(request.content, _prev_user_text, persona=(state.get("coach_persona") or {}).get("name"))]).strip()
            _tm["hard"] = True
            logger.info("🎯 결과 질문 없음 → 명사구 폴백: %s", clean_reply[-50:])

        # (2026-09-22 결정) 리드 한 문장 상한: 질문 앞 리드가 2문장 이상이면 첫 문장만. 매 턴 한 문장 되받기는 허용,
        #   3턴 1회 제한은 없다. 질문부터는 불변. 프로브 턴만(ALIGN·OPENING 은 정의·목록이 리드).
        if _is_probe:
            clean_reply, _lc = cap_lead_sentences(clean_reply)
            if _lc:
                _v["lead_cap"] = _lc
                _tm["hard"] = True
                logger.info("✂️ 리드 %d문장 → 1문장", _lc + 1)

        # 3(2026-09-17) Result 탐침 문장 변주: 상투형('그렇게 하니 어떻게 됐습니까') 또는 이 챕터에서 이미 쓴
        #   결과 질문과 같은 문장이면 풀에서 안 쓴 문장으로 교체(직전 2턴 제외).
        if chapter and _is_probe:
            from diag_project.services.output_guard import find_repeated_result_probe
            from diag_project.services.traversal import pick_result_probe, used_result_probes
            _dup = find_repeated_result_probe(clean_reply, used_result_probes(session.self_assessment_data, chapter))
            if _dup:
                from diag_project.services.output_guard import result_fallback_question as _rfq4
                _new_q = _rfq4(request.content, _prev_user_text)
                if _new_q not in clean_reply:
                    clean_reply = clean_reply.replace(_dup, _new_q, 1)
                    logger.info("🔁 결과 질문 반복 교체: '%s' → '%s'", _dup[:40], _new_q)

    # (2026-09-29) 대명사 단독 질문 정리 — 가드 밖 턴(ABSENCE_PROBE 등) 포함 모든 LLM 턴: 다른 질문이 남으면
    #   '그럴 때는 어떠셨습니까?' 같은 지시 대상 없는 질문 문장만 뺀다(질문 보존 원칙 유지).
    if system_override_text is None and not _llm_error and clean_reply:
        from diag_project.services.output_guard import bare_demonstrative_questions as _bdq_all, split_sentences as _ss_all, \
            is_question as _isq_all
        _bare_all = _bdq_all(clean_reply, request.content)
        _qs_all = [x for x in _ss_all(clean_reply) if _isq_all(x)]
        if _bare_all and len(_qs_all) > len(_bare_all):
            for _bq in _bare_all:
                clean_reply = clean_reply.replace(_bq, "").strip()
            clean_reply = re.sub(r"[ \t]{2,}", " ", clean_reply)
            logger.info("🧹 대명사 단독 질문 제거(다른 질문 유지): %s", _bare_all)
        elif _bare_all:
            from diag_project.services.output_guard import followup_from_user as _ffu2
            for _bq in _bare_all:
                clean_reply = clean_reply.replace(_bq, _ffu2(request.content), 1)
            logger.info("🧹 대명사 단독 질문 교체(유일 질문): %s", _bare_all)

    # 5(2026-09-21) 문법: '있으시겠습니까' 는 미래·청유형 오용 → '있으셨습니까'
    if clean_reply:
        clean_reply = clean_reply.replace("있으시겠습니까", "있으셨습니까").replace("있으시겠어요", "있으셨어요")

    # 8-n. (2026-10-22 P2-1) 입버릇 반복 가드 — 되받기 마무리 어구(마지막 어절 2개)를 세션 단위로 센다.
    #   같은 어구 2회째 → 재생성 1회, 3회째(또는 재생성 후에도) → 그 문장 삭제. 금지 어구(마음에 남아요·짐작이 되네요·
    #   인상에 남네요·그려지네요·분명하게 들어왔어요)는 1회째부터 재생성. '리더님,' 문두 호칭은 3턴에 1회(직전 2턴에 있으면 뗀다).
    # (2026-10-29) COMPETENCY_ALIGN 도 대상 — 조립이 8-z(맨 끝)로 옮겨져 여기서는 LLM 되받기 2~3문장만 다룬다.
    #   (10/28 에는 조립이 8-b 에 있어 고정 정의 문장 어미가 입버릇으로 세어지고 재생성이 조립을 덮어 제외했었다.)
    _TAIL_EXEMPT = {"DIAGNOSIS_INTRO", "USER_REQUESTS_PAUSE", "CHAPTER_READY_TO_END", "AWAIT_NEXT_CHAPTER_CHOICE"}
    if (system_override_text is None and not _llm_error and clean_reply and instruction_used not in _TAIL_EXEMPT
            and not needs_user_decision):
        from diag_project.services.output_guard import (
            find_banned_tail as _fbt, lead_tails as _lts, starts_with_honorific as _swh,
            strip_lead_sentences as _sls, strip_leading_honorific as _slh,
        )
        _tc = dict((session.self_assessment_data or {}).get("tail_counts") or {})

        def _tail_hits(txt: str) -> tuple[list, list]:
            _b = _fbt(txt)
            _r = [t for t in _lts(txt) if int(_tc.get(t, 0) or 0) >= 1]
            return _b, _r

        _b0, _r0 = _tail_hits(clean_reply)
        if _b0 or _r0:
            _tm["tail"] = (_b0 + _r0)[0]
            _third = any(int(_tc.get(t, 0) or 0) >= 2 for t in _r0)
            _fixed = False
            if not _third:
                try:
                    _t_out = await _timed_regen(
                        system_prompt=system_prompt, chapter_context=chapter_context,
                        turn_state_text=turn_state_text + (
                            "\n\n🚨 [시스템 — 재생성 지시] 첫 문장의 마무리 어구 '" + "', '".join(_b0 + _r0)
                            + "' 는 이 세션에서 이미 썼거나 금지된 표현입니다. 첫 문장을 다른 마무리로 다시 쓰세요(질문은 유지). 이 지시문의 단어를 답에 옮기지 마세요."),
                        compressed_history=compressed_history, user_message=_llm_user_text, light_mode=True)
                    _t_txt = _MARKER_RE.sub("", _t_out.get("reply") or "").strip()
                    _b1, _r1 = _tail_hits(_t_txt) if _t_txt else (["(빈 응답)"], [])
                    if _t_txt and not _b1 and not _r1:
                        clean_reply = _t_txt
                        _fixed = True
                        logger.info("🗣️ 입버릇 반복 → 재생성으로 해결: %s", _tm["tail"])
                except Exception as _e:
                    logger.error("🗣️ 입버릇 재생성 실패: %s", _e)
            if not _fixed:
                clean_reply, _n_tail = _sls(clean_reply, set(_r0))
                _tm["tail_fix"] = 2
                logger.info("🗣️ 입버릇 반복(%s) → 되받기 문장 %d개 삭제", _tm["tail"], _n_tail)
                if instruction_used == "STAR_COMPLETE_NEW_EVENT" and not any(
                        not is_question_sentence(x) for x in split_sentences(clean_reply)):
                    # 전환 턴은 되받기·다리 없이 앵커만 남으면 안 된다 → 페르소나 다리 한 문장을 앞에
                    from diag_project.services.intro_messages import transition_bridge as _tbr_n
                    clean_reply = f"{_tbr_n((state.get('coach_persona') or {}).get('name'), len(asked_for_chapter(session.self_assessment_data, chapter) or []))} {clean_reply}".strip()
                    _tm["bridge_added"] = 1
        if _swh(clean_reply) and any(_swh(_t) for _t in _recent_coach_texts):
            clean_reply, _hon = _slh(clean_reply)
            if _hon:
                _tm["honorific"] = 1
                logger.info("🗣️ '리더님,' 문두 호칭 반복 → 제거")

    # 8-o. (2026-10-22) 최종 '한 턴 한 질문' — 8-n 입버릇 재생성·감정 재생성이 바꾼 본문에도 질문이 2개 이상이면 마지막만 남긴다.
    if (system_override_text is None and not _llm_error and clean_reply and not needs_user_decision
            and instruction_used not in ("DIAGNOSIS_INTRO", "CHAPTER_READY_TO_END", "USER_REQUESTS_PAUSE", "AWAIT_NEXT_CHAPTER_CHOICE",
                                         "COMPETENCY_ALIGN", "STAR_COMPLETE_NEW_EVENT")):
        from diag_project.services.output_guard import keep_last_question as _klq_o
        clean_reply, _n_qo = _klq_o(clean_reply)
        if _n_qo:
            _tm["one_q"] = int(_tm.get("one_q") or 0) + _n_qo
            logger.info("✂️ 최종 한 턴 한 질문: %d문장 제거", _n_qo)

    # 8-p. (2026-10-23 6번 보정) Michael "좋습니다" 도입: 턴당 최대 1회, 챕터에서 2턴에 1회 이하(직전 턴에 썼으면 이번 턴은 뗀다).
    #   고정 문장 턴(안내·확인 템플릿)도 센다 — 재생에서 4·5·6턴 연속 '좋습니다' 가 템플릿 턴에서 났다.
    if (not _llm_error and clean_reply and not needs_user_decision
            and (state.get("coach_persona") or {}).get("name", "").startswith("Michael")):
        from diag_project.services.persona_voice import michael_lead_guard as _mlg
        _good_prev = list(((session.self_assessment_data or {}).get("good_turns") or {}).get(chapter or "_", []))
        _allow_good = (_turn_index - 1) not in _good_prev
        clean_reply, _used_good = _mlg(clean_reply, _allow_good, add=bool(chapter))   # 챕터 밖(라포·인사)에는 붙이지 않는다
        _tm["good_lead"] = 1 if _used_good else 0
        if not _allow_good:
            _tm["good_lead_cut"] = 1

    # 8-m. (2026-10-22 P2-0) 리더 종료 요청 + 넓이 미충족: 되받기 한 문장 + "하나만 더 여쭤봐도 될까요?" + 다음 미탐색 앵커 1개.
    #   원장은 기록하지 않는다 — 답하면 다음 프로브 스텝이 같은 타겟을 골라 기록하고, 거절하면 미탐색으로 남는다.
    if instruction_used == "CHAPTER_ONE_MORE_ASK" and system_override_text is None and not _llm_error:
        from diag_project.data.competencies import find_sub_key_by_name as _fsk_om
        from diag_project.services.anchor_render import dict_anchor as _dict_anchor_om
        from diag_project.services.output_guard import receive_sentence as _recv_om
        from diag_project.services.traversal import select_next_target as _snt_om
        _recv_text = _recv_om(clean_reply, fallback="네, 이 영역은 충분히 들려주셨어요.")
        _next_sub = _snt_om(asked_for_chapter(session.self_assessment_data, chapter), state.get("all_subcompetencies") or [], [])
        _om_q = _dict_anchor_om(_fsk_om(chapter, _next_sub) if _next_sub else None)
        from diag_project.services.intro_messages import persona_line as _pl_om
        clean_reply = f"{_recv_text} {_pl_om((state.get('coach_persona') or {}).get('name'), 'one_more')} {_om_q}"
        _tm["one_more"] = _next_sub or "-"
        logger.info("🙏 종료 요청(넓이 미충족) → 하나만 더: [%s] %s", chapter, _next_sub)

    # 8-k. (2026-10-22 P1-3) 모든 코치 턴은 질문 하나로 끝난다 — LLM 출력에 질문이 없으면 그 턴의 고정 질문을 붙인다.
    #   라포(8-0)·INTRO(안내 끝 '시작해볼까요?')·ALIGN/전환(앵커)·프로브(템플릿 앵커·결과 폴백)는 각자 보장하고,
    #   여기서는 정의 질문 턴(DIAGNOSIS_CONFIRM·COMPETENCY_ASK)을 보장한다. 질문을 두지 않는 턴(일시정지 제안·일시중지·
    #   챕터 종료 다리·세션 종료)은 제외.
    if (system_override_text is None and not _llm_error and clean_reply
            and instruction_used in ("DIAGNOSIS_CONFIRM", "COMPETENCY_ASK")):
        # (2026-10-28 P0-4) 정의 턴의 질문은 '고정 정의 질문' 하나뿐 — LLM 이 다른 질문(간접 질문 포함)으로 끝내면
        #   그 질문을 지우고 고정 질문을 붙인다(10/28 재생: 리더가 코치 앵커를 붙여넣자 CONFIRM 이 정의 질문 없이 사례를 청했다).
        from diag_project.services.intro_messages import definition_question
        from diag_project.services.output_guard import drop_question_sentences as _dqs_k
        _cn_k = COMPETENCY_FRAMEWORK.get(chapter, {}).get("name", "이 역량")
        _defq_k = definition_question(_cn_k, (state.get('coach_persona') or {}).get('name'))
        if _defq_k not in clean_reply:
            _body_k, _nq_k = _dqs_k(clean_reply)
            clean_reply = f"{_body_k.rstrip()} {_defq_k}".strip()
            _tm["no_q_fix"] = "definition" if _nq_k == 0 else f"definition(replaced {_nq_k})"
            logger.info("❓ 정의 턴 질문 고정: LLM 질문 %d문장 제거 후 고정 정의 질문 결합", _nq_k)

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
        # (2026-10-22 P1-1) 제안 턴은 '되받기 한 문장 + 안내'만 — 질문은 삼키되 버리지 않는다:
        #   이 턴의 instruction·타겟·리더 답변을 pending 으로 저장하고, 원장(asked/turns/target)은 스텝 이전으로 되돌린다.
        #   리더가 '계속'이면 다음 턴 decider 가 pending 을 그대로 실행(같은 타겟·같은 탐침), '다음에'면 paused.
        from diag_project.services.intro_messages import pause_suggestion_text
        from diag_project.services.output_guard import receive_sentence as _recv_pause
        from diag_project.services.traversal import restore_ledger as _restore_ledger
        _recv_only = _recv_pause(clean_reply, fallback="")
        if _tm.get("ladder"):   # (2026-10-29 P1) 일시정지 제안이 사다리 질문을 삼켰다 — 재개 턴에서 다시 사다리가 잡히도록 사용 표시를 지운다
            _tm.pop("ladder", None); _tm["ladder_dropped"] = "pause"; state["force_ladder_probe"] = None
        clean_reply = f"{_recv_only}\n\n{pause_suggestion_text(_sit_elapsed, (state.get('coach_persona') or {}).get('name'))}".strip()
        _pst = dict(session.self_assessment_data or {})
        if _ledger_snapshot is not None:
            _pst = _restore_ledger(_pst, _ledger_snapshot)
        _pst["pending_instruction"] = {
            "instruction": instruction_used, "chapter": chapter, "target": current_target_sub,
            "user_text": (request.content or "")[:1000], "at": datetime.utcnow().isoformat(timespec="seconds"),
        }
        session.self_assessment_data = _pst
        from sqlalchemy.orm.attributes import flag_modified as _fm_pst
        _fm_pst(session, "self_assessment_data")
        logger.info("⏸️ 일시정지 제안: 질문 보류 → pending=%s target=%s (원장 되돌림=%s)",
                    instruction_used, current_target_sub, _ledger_snapshot is not None)

    # 8-y. (2026-10-29) 최종 누설 소거 — 8-i 뒤의 재생성(8-j 전환·8-n 입버릇·8-h 느낌표)이 만든 새 LLM 출력은 8-i 의 누설 검사를
    #   거치지 않았다(s291 Jessica t10: 8-n 재생성 출력이 '되받기 한 문장 + 다리 한 문장으로 답하겠습니다.'로 시작). 엄격 사전 어휘·
    #   상태 보고문이 든 평서문만 지운다(질문 보존). ALIGN 은 조립(8-z) 전의 되받기에 걸리므로 고정 문장은 건드리지 않는다.
    if system_override_text is None and not _llm_error and (clean_reply or "").strip():
        try:
            from diag_project.services.leak_lexicon import find_leaks as _fl_y, find_state_report as _fsr_y, strip_leak_sentences as _sls_y
            from diag_project.services.output_guard import strip_state_leak as _ssl_y
            _lk_y = _fl_y(clean_reply, _prev_user_texts + [request.content or ""])
            _sr_y = _fsr_y(clean_reply)
            if _lk_y or _sr_y:
                _c_y, _n_y = clean_reply, 0
                if _lk_y:
                    _c_y, _n_y = _sls_y(_c_y, list(_lk_y))
                if _sr_y:
                    _c_y2, _n_y2 = _ssl_y(_c_y)
                    for _s_y in _sr_y:      # 정규식 상태 보고문(strip_state_leak 이 모르는 문장)은 문장 단위로 뗀다
                        if _s_y in _c_y2:
                            _c_y2 = _c_y2.replace(_s_y, "").strip(); _n_y2 += 1
                    _c_y, _n_y = _c_y2, _n_y + _n_y2
                _c_y = re.sub(r"\n{3,}", "\n\n", _c_y).strip()
                if _c_y and (has_question(_c_y) or not has_question(clean_reply)):
                    clean_reply = _c_y
                    _tm["leak_final"] = {"words": list(_lk_y)[:6], "state": _sr_y[:3], "stripped": _n_y}
                    logger.info("🛡️ 최종 누설 소거 %d문장: 어휘=%s 상태=%s", _n_y, _lk_y, _sr_y)
        except Exception as _le_y:   # noqa: BLE001 — 소거 실패가 턴을 막지 않게
            logger.warning("최종 누설 소거 실패 — 건너뜀: %s", _le_y)   # 로그 문구도 누설 사전 추출 대상이라 내부어가 아닌 낱말로 쓴다

    # 8-z. (2026-10-28 P0-1) ALIGN 최종 조립 — 모든 후처리 뒤. 되받기(가드 통과본) + 고정 정의 + 목록 + 안내 + 다리 + 앵커.
    if _align_ctx is not None and system_override_text is None and not _llm_error and chapter:
        from diag_project.services.align_render import align_shape_ok as _aso_z, render_align as _ra_z
        clean_reply = _ra_z(llm_text=clean_reply, chapter=chapter, **_align_ctx)
        _ok_z, _why_z = _aso_z(clean_reply, _align_ctx["sub_names"])
        _tm["align_shape"] = "ok" if _ok_z else ";".join(_why_z)
        if not _ok_z:
            logger.warning("📐 ALIGN 형식 자가점검 실패: %s", _why_z)

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
    elif instruction_used == "CHAPTER_ONE_MORE_ASK":
        probe_type_used = "ONE_MORE_ASK"   # (2026-10-22 P2-0) 챕터당 1회 판별 마커
    elif _is_warning:
        # 최후 의향 확인(Warning) 턴 — 다음 턴에 '이미 경고함'을 판별해
        # 재경고 루프를 막고 곧바로 종료로 승격시키는 근거 마커.
        probe_type_used = "ABORT_WARNING"
    elif _is_name_reconfirm:
        # 이름 재확인 턴 — 다음 턴에 '이미 되물음'을 판별해 재질문을 막는 마커.
        probe_type_used = "NAME_RECONFIRM"
    elif instruction_used == "RAPPORT_BUILDING" and state.get("rapport_turn_count", 0) == 2:
        # 6(2026-09-17) 담당 업무 질문 턴 — 다음 턴에 답변을 participant_context 로 저장하는 근거 마커.
        #   (2026-10-21) 스몰톡 턴이 앞에 들어가 담당업무 턴은 rapport_turn_count==2.
        #   (2026-10-16) 템플릿이 아니라 LLM 턴이 됐으므로 system_override_text 조건을 뺀다. 카테고리(rapport_turn_count==1)
        #   가 곧 '담당업무' 턴이다. 가이드가 이 턴의 [READY_FOR_INTRO] 를 금지하므로 위 READY_FOR_INTRO 분기에 가려지지 않는다.
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
            events_all=all_events,
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
    await db.flush()   # (2026-09-22) 턴 끝 1회 커밋 — 중간 커밋 폐지

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
        await db.flush()   # (2026-09-22) 턴 끝 1회 커밋 — 중간 커밋 폐지

    # 11-b. 일시중지: 세션을 '대기(paused)' 상태로 전환.
    #   비정상 챕터 전환 없이(위 전진 블록은 is_chapter_completed=False 라 스킵)
    #   진단을 보류하고, 프론트가 대기 상태로 인지하도록 status 를 바꾼다.
    #   현재 챕터/토픽은 그대로 두어 나중에 이어서 재개할 수 있게 한다.
    if is_session_paused and session.status != "completed":
        session.status = "paused"
        db.add(session)
        await db.flush()   # (2026-09-22) 턴 끝 1회 커밋 — 중간 커밋 폐지

    # 11-c. 🚨 3-Strike 강제 종료: 세션 상태를 'aborted' 로 확정한다.
    #   재개 불가 — 완료도 일시중지도 아닌 '중단' 상태로 명확히 분리한다.
    if _is_aborted:
        session.status = "aborted"
        session.current_topic = "Aborted"
        db.add(session)
        await db.flush()   # (2026-09-22) 턴 끝 1회 커밋 — 중간 커밋 폐지
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
        if state.get("resume_pending") and instruction_used != "USER_REQUESTS_PAUSE":
            _gl_store.pop("pending_instruction", None)   # (2026-10-22 P1-1) 재개 턴이 pending 을 소비
        if chapter and system_override_text is None and not _llm_error:
            # (2026-10-22 P2-2) 이번 코치 질문이 감정 질문이면 챕터 카운트 +1, 행동 질문이면 action_probed 기록
            from diag_project.services.output_guard import is_emotion_question as _ieq_g, split_sentences as _ss_g
            from diag_project.services.output_guard import is_question as _isq_g
            from diag_project.services.traversal import is_action_probe_text as _iapt_g, mark_action_probed as _map_g
            _fq = next((x for x in reversed(_ss_g(clean_reply)) if _isq_g(x)), "")
            if _fq and _ieq_g(_fq):
                _eqc = dict(_gl_store.get("emotion_q_count") or {})
                _eqc[chapter] = int(_eqc.get(chapter, 0) or 0) + 1
                _gl_store["emotion_q_count"] = _eqc
            if _fq and _iapt_g(_fq):
                _gl_store = _map_g(_gl_store, chapter)
            if _tm.get("voiced"):
                _vvc = dict(_gl_store.get("voice_variant_count") or {})
                _vvc[chapter] = int(_vvc.get(chapter, 0) or 0) + 1
                _gl_store["voice_variant_count"] = _vvc
            # (2026-10-23 P4) Olivia 대조 탐침 챕터당 1회 집계
            from diag_project.services.persona_voice import is_contrast_question as _icq_g
            if _fq and _icq_g(_fq):
                _cqc = dict(_gl_store.get("contrast_q_count") or {})
                _cqc[chapter] = int(_cqc.get(chapter, 0) or 0) + 1
                _gl_store["contrast_q_count"] = _cqc
                _tm["contrast_q"] = 1
            if _tm.get("generalize"):
                from diag_project.services.traversal import mark_generalize_probed as _mgp_g
                _gl_store = _mgp_g(_gl_store, chapter, current_target_sub)
                # (2026-10-29 P1-3) 다음 턴 답이 여전히 시점 없는 일반화면 generalized 원장에 남긴다(리포트 P2-3)
                _gp = dict(_gl_store.get("generalize_pending") or {}); _gp[chapter] = current_target_sub
                _gl_store["generalize_pending"] = _gp
            if _tm.get("direct_q") and current_target_sub:
                # (2026-10-29 P1-2) '직접 하신' 질문 사용 횟수 — 하위역량당 1회 상한
                _dqc_g = dict(_gl_store.get("direct_q_count") or {}); _dqc_ch = dict(_dqc_g.get(chapter) or {})
                _dqc_ch[current_target_sub] = int(_dqc_ch.get(current_target_sub, 0) or 0) + 1
                _dqc_g[chapter] = _dqc_ch; _gl_store["direct_q_count"] = _dqc_g
            if _tm.get("ladder"):
                from diag_project.services.traversal import mark_ladder_probed as _mlp_g
                _gl_store = _mlp_g(_gl_store, chapter, (state.get("force_ladder_probe") or {}).get("sub") or current_target_sub)
                # (2026-10-29 P1-4) 세션 간 회전용: 어느 사다리 단계를 썼는지 하위역량 키로 남긴다(다음 세션 시작 시 ladder_avoid 로 모음)
                from diag_project.data.competencies import find_sub_key_by_name as _fsk_lu
                _lu_key = _fsk_lu(chapter, (state.get("force_ladder_probe") or {}).get("sub") or current_target_sub)
                if _lu_key:
                    _lu = dict(_gl_store.get("ladder_used") or {})
                    _lu[_lu_key] = sorted(set((_lu.get(_lu_key) or []) + [str(_tm.get("ladder"))]))
                    _gl_store["ladder_used"] = _lu
        if system_override_text is None and not _llm_error:
            # (2026-10-22 P2-1) 이번 턴 되받기 마무리 어구를 세션 카운터에 누적(최근 60개)
            from diag_project.services.output_guard import lead_tails as _lts_g
            _tcg = dict(_gl_store.get("tail_counts") or {})
            for _t in _lts_g(clean_reply):
                _tcg[_t] = int(_tcg.get(_t, 0) or 0) + 1
            if len(_tcg) > 60:
                _tcg = dict(list(_tcg.items())[-60:])
            _gl_store["tail_counts"] = _tcg
        if _tm.get("good_lead"):      # (6번 보정) Michael '좋습니다' 사용 턴 — 템플릿 턴 포함
            _gt = {k_: list(v_) for k_, v_ in (_gl_store.get("good_turns") or {}).items()}
            _gt.setdefault(chapter or "_", []).append(_turn_index)
            _gl_store["good_turns"] = _gt
        _gl = list(_gl_store.get("guard_log") or [])[-199:]
        _gl.append({
            "t": _turn_index, "ch": chapter, "instr": instruction_used,
            "v": sorted((_tm.get("violations") or {}).keys()), "regen": _tm["regen_n"],
            "route": state.get("route_reason"),
            "hard": bool(_tm.get("hard")), "llm": round(_tm["llm"], 1), "total": round(_total, 1), "sql": _sqlc.get(),
            # (2026-10-19) 라포 되받기 반복 가드: 0=미발동, 1=재생성으로 해결, 2=재생성 후에도 반복 → "그러셨군요." 대체
            "echo": int(_tm.get("echo") or 0),
            # (2026-10-21) quote: ALIGN 외부 인용(1 재생성 해결/2 따옴표 제거) · semrep: 의미 반복(1 재생성/2 다음 앵커) ·
            #   bridge: 전환 턴 되받기 없음(1 재생성/2 전환 문장만) · one_q: 제거한 앞선 질문 수 · moment: 시점 문형 교정 수 ·
            #   anchor: 앵커 렌더링 모드(dict/llm/fallback)
            "quote": int(_tm.get("quote") or 0), "semrep": int(_tm.get("semrep") or 0),
            "bridge": int(_tm.get("bridge") or 0), "one_q": int(_tm.get("one_q") or 0),
            "moment": int(_tm.get("moment") or 0), "anchor": _tm.get("anchor_render"),
            "work_q": int(_tm.get("work_q") or 0),   # (2026-10-21) 스몰톡 되물음이 업무·역할 질문이라 삭제됨
            # (2026-10-22 P1) no_q_fix: 질문 없는 턴 보정 경로 · quantify: 정도 부사 → 수치 질문 교체
            "no_q_fix": _tm.get("no_q_fix"), "quantify": int(_tm.get("quantify") or 0),
            "resume": int(_tm.get("resume") or 0),   # (2026-10-22 P1-1) 일시정지 제안 뒤 pending 재개 턴
            # (2026-10-22 P2-0) volunteered: 자발적 사례로 asked 기록된 하위역량 · one_more: '하나만 더' 가 겨냥한 하위역량
            "volunteered": _tm.get("volunteered"), "one_more": _tm.get("one_more"),
            # (2026-10-22 P2-1) tail: 반복·금지 어구 · tail_fix 2=문장 삭제 폴백 · honorific: '리더님,' 문두 제거
            "tail": _tm.get("tail"), "tail_fix": int(_tm.get("tail_fix") or 0), "honorific": int(_tm.get("honorific") or 0),
            # (2026-10-22 P2-2) sar_full: S-A-R 완비 답변(탐침 1회 후 전진) · emotion 1 재생성/2 교체 · action_fix: A 강제 고정 질문
            "sar_full": int(_tm.get("sar_full") or 0), "emotion": int(_tm.get("emotion") or 0),
            "action_fix": int(_tm.get("action_fix") or 0),
            # (2026-10-22 P2-3) lead_cap: 페르소나 상한으로 지운 되받기 문장 수 · bridge_added: 전환 턴에 페르소나 다리 삽입
            "lead_cap": int(_tm.get("lead_cap") or 0), "bridge_added": int(_tm.get("bridge_added") or 0),
            # (2026-10-23, 4-1) generalize_probe: 일반화 답변에 '가장 최근 일 하나' 탐침을 붙인 턴
            "generalize_probe": int(_tm.get("generalize") or 0),
            # (2026-10-23 P3) ladder_probe: 사다리 질문 단계("2_3"|"3_4") · ladder_level: flash 판정 레벨
            "ladder_probe": _tm.get("ladder"), "ladder_level": (state.get("force_ladder_probe") or {}).get("level") if _tm.get("ladder") else None,
            "contrast_q": int(_tm.get("contrast_q") or 0),   # (2026-10-23 P4) 대조 탐침 질문 턴
            # (2026-10-23 6번 보정) contrast_fix 1 재생성/2 교체 · contrast_lead_fix 도입구 제거 수 · good_lead Michael 도입 사용 · good_lead_cut 직전 턴 사용으로 제거
            "contrast_fix": int(_tm.get("contrast_fix") or 0), "contrast_lead_fix": int(_tm.get("contrast_lead_fix") or 0),
            "good_lead": int(_tm.get("good_lead") or 0), "good_lead_cut": int(_tm.get("good_lead_cut") or 0),
            # (2026-10-29 P1) leak_final: 8-y 최종 누설 소거(어휘·상태) · ladder_trigger: 'turns'=턴 조건 사다리 · direct_q/direct_q_fix: '직접 하신' 상한 ·
            #   generalized: 일반화 탐침 뒤에도 시점 없음(원장 기록) · skip_bridge/unconfirmed: 입력 이상 3회째 전진 · anomaly: 종류(#n 회차)
            "leak_final": _tm.get("leak_final"), "ladder_trigger": _tm.get("ladder_trigger"),
            "ladder_skip": _tm.get("ladder_skip"), "ladder_swap": int(_tm.get("ladder_swap") or 0), "ladder_dropped": _tm.get("ladder_dropped"),
            "direct_q": int(_tm.get("direct_q") or 0), "direct_q_fix": _tm.get("direct_q_fix"),
            "generalized": _tm.get("generalized"), "skip_bridge": int(_tm.get("skip_bridge") or 0), "unconfirmed": _tm.get("unconfirmed"),
            "anomaly": _tm.get("anomaly"),
        })
        _gl_store["guard_log"] = _gl
        if _gl_store.get("llm_error_streak"):
            _gl_store["llm_error_streak"] = 0   # 성공 턴 → 연속 실패 리셋
        session.self_assessment_data = _gl_store
        from sqlalchemy.orm.attributes import flag_modified as _fm_gl
        _fm_gl(session, "self_assessment_data")
    except Exception as _e:
        logger.warning("guard_log 기록 실패: %s", _e)
    # (2026-09-22) 턴 끝 1회 커밋 — 사용자 메시지·코치 메시지·원장·사건·guard_log 가 한 트랜잭션. 실패하면 전부 되돌리고
    #   503 으로 알린다(부분 저장 없음, 원장 보존 정책 A-4). 클라이언트는 같은 답변을 다시 보내면 된다.
    try:
        await db.commit()
    except Exception as _ce:
        logger.error("💥 턴 커밋 실패 → 롤백: session=%s instr=%s err=%s", str(session.id)[:8], instruction_used, _ce)
        await db.rollback()
        raise HTTPException(status_code=503, detail="저장에 실패했습니다. 같은 답변을 다시 보내 주세요.")
    # (2026-09-29, A-2) 챕터가 닫힌 턴이면 그 챕터의 심층분석+게이트를 백그라운드로 미리 돌려 캐시에 채운다.
    #   반드시 커밋 '뒤'(마지막 발화까지 포함돼야 완료 시 캐시가 맞는다). 실패는 모듈이 조용히 삼킨다.
    if instruction_used == "CHAPTER_READY_TO_END" and chapter:
        try:
            from diag_project.services.report_prewarm import schedule_chapter_prewarm
            schedule_chapter_prewarm(str(session.id), chapter)
            logger.info("🔥 챕터 사전분석 예약: [%s] session=%s", chapter, str(session.id)[:8])
        except Exception as _pe:
            logger.warning("챕터 사전분석 예약 실패(무시): %s", _pe)
    logger.info("⏱ turn timing session=%s instr=%s decider=%.2fs llm=%.2fs regen=%d(%.2fs) post+db=%.2fs total=%.2fs sql=%d",
                str(session.id)[:8], instruction_used, _tm["decider"], _tm["llm"], _tm["regen_n"], _tm["regen_s"],
                max(0.0, _total - _tm["decider"] - _tm["llm"] - _tm["regen_s"]), _total, _sqlc.get())
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
    events_all: list | None = None,
) -> UUID | None:
    """사건 생명주기 — 백엔드 결정론 (2026-09-22, LLM 자기보고 폐기; 코드 리뷰 2-d 🟥 #1·#2·#5).

    직전 코치 턴의 instruction·문장과 사용자 발화만으로: 새 사건 생성(앵커·부재 폴백·정의 합의 뒤 첫 서술),
    STAR 슬롯 채움(직전 질문이 결과 질문이면 R, 아니면 A→R→T 순), 완결(타겟 전진 또는 새 사건 시작).
    mapped_subcompetency 는 원장 타겟(LLM 추정 아님). 단답·부재·회피·메타 턴은 슬롯을 채우지 않는다.

    Returns: 이 턴이 속한 사건 UUID (없으면 None)
    """
    from diag_project.services.event_tracker import plan_event_update

    if events_all is not None:
        _ch_events = [e for e in events_all if e.chapter == chapter]
        active_event = max((e for e in _ch_events if not e.is_complete), key=lambda e: e.sequence_num, default=None)
    else:
        _ch_events = None
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
        }, commit=False)

    if plan.op == "new":
        if active_event and plan.complete_active:
            await _complete(active_event)
        existing = _ch_events if _ch_events is not None else await get_chapter_events(db, session_id, chapter)
        new_event = await create_event(db=db, session_id=session_id, chapter=chapter, sequence_num=len(existing) + 1, commit=False)
        new_event.mapped_subcompetency = mapped_target
        await update_event_star(db=db, event_id=new_event.id, situation=text, commit=False)
        await increment_probe_count(db, new_event.id, commit=False)
        if events_all is not None:
            events_all.append(new_event)
        return new_event.id

    if active_event is None:
        return None
    if plan.op == "fill" and plan.slot:
        await update_event_star(db=db, event_id=active_event.id, commit=False, **{plan.slot: text})
    await increment_probe_count(db, active_event.id, commit=False)
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