import logging
import os
import uuid
from diag_project.services.participant_auth import Caller, get_caller, assert_can_access_participant, assert_can_access_session  # (2026-10-29 보안) 참여자 API 소유자 확인
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
from diag_project.services import turn_progress as _tp   # (2026-11-11 단계 표시)
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
from diag_project.services.event_service import create_event, update_event_star, complete_event
from diag_project.prompts.phase3a.layer1_system import (
    LAYER1_SYSTEM_PROMPT,
    build_layer1_with_persona,
)
from diag_project.services.time_greeting import (
    build_rapport_greeting,
    build_rapport_first_turn_response,
)
from diag_project.services.intro_messages import build_intro_anchor_section
from diag_project.services.system_lines import system_line as _sys_line   # (P11-A5) 코치 말투별 시스템 고정 문장
from diag_project.data.competencies import COMPETENCY_FRAMEWORK
from diag_project.prompts.phase3a.episode_card import chapter_context_bei   # (2026-11-04 BEI) Layer2 축약
from diag_project.prompts.phase3a.layer3_state import format_turn_state_for_llm
from diag_project.prompts.phase3a.layer3_state import expectation_usable as _expectation_usable
from diag_project.services import bei_engine as _bei   # (2026-11-04 BEI) 사례 상태기계
# (2026-11-12 P11-A5) 아래 이름들은 턴 핸들러 전체에서 쓴다 — 종전에는 8-i(LLM 턴 전용 블록) 안에서 지역 import 돼 시스템 고정 턴(기대 답 없는 진단 안내)에서
#   말투 교정(8-zz)이 "cannot access local variable 'split_sentences'" 로 조용히 건너뛰었다(Daniel 에게 '안내드릴게요·이루어져 있어요·시작해볼까요?').
from diag_project.services.output_guard import (
    find_praise, find_revisit_greeting, find_state_leak, find_sub_names, has_question, same_question_as_previous, split_sentences,
    strip_praise, strip_revisit_greeting, strip_state_leak, strip_sub_name_mentions,
)
from diag_project.services.output_guard import is_question as is_question_sentence

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
    caller: Caller = Depends(get_caller),
):
    await assert_can_access_participant(caller, participant_id, db)
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
    caller: Caller = Depends(get_caller),
):
    await assert_can_access_participant(caller, request.participant_id, db)
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
# [0-b2] (2026-11-06 P7-3) 지금 마치기 — 남은 항목은 1.0 '사례 미확인'으로 확정하고 리포트 생성 대상(completed)으로 (POST /{session_id}/finish)
@router.post("/{session_id}/finish")
async def finish_session_early(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    caller: Caller = Depends(get_caller),
):
    """리더가 '지금 마치기'를 고르면 세션을 completed 로 바꾼다. 묻지 못한 칸은 분석의 미탐색 정책(P7-2)이 1.0 으로 채운다.
    프론트는 이어서 /reports/{sid}/analyze 를 부른다. 열람 토큰·완료 세션은 그대로."""
    if caller.is_viewer:
        raise HTTPException(status_code=403, detail="열람 전용 접속에서는 할 수 없습니다.")
    session = await assert_can_access_session(caller, session_id, db)
    if session.status == "completed":
        return {"status": "completed", "already": True, "session_id": str(session.id)}
    if session.status in ("aborted", ABANDONED):
        raise HTTPException(status_code=409, detail=f"이 세션은 마칠 수 없는 상태입니다: {session.status}")
    _st = dict(session.self_assessment_data or {})
    _st.pop("pending_instruction", None)
    _st["finished_early"] = {"at": datetime.utcnow().isoformat(timespec="seconds"), "topic": session.current_topic}
    session.self_assessment_data = _st
    from sqlalchemy.orm.attributes import flag_modified as _fm_fin
    _fm_fin(session, "self_assessment_data")
    session.status = "completed"
    session.current_topic = "Completed"
    db.add(session)
    await db.commit()
    logger.info("🏁 지금 마치기: session=%s topic=%s", session.id, _st["finished_early"]["topic"])
    return {"status": "completed", "finished_early": True, "session_id": str(session.id)}


# [0-c] 복원 — abandoned → in_progress (POST /restore)  ※ 상태 전이 표의 유일한 복원 경로
#   4(a) 즉시 되돌리기(자가진단 상단 배너)가 호출한다. 같은 참가자의 다른 진행 세션
#   (방금 만든 빈 세션 등)은 abandoned 로. 참가자 인증은 (B) 에서 — 파일럿 범위 감수.
# ------------------------------------------------------------------
@router.post("/restore")
async def restore_abandoned_session(
    request: RestoreRequest,
    db: AsyncSession = Depends(get_db),
    caller: Caller = Depends(get_caller),
):
    await assert_can_access_session(caller, request.session_id, db)
    return await restore_session_by_id(db, request.session_id)


# ------------------------------------------------------------------
# [1] 진단 세션 시작 (POST /start) - ✅ 이어하기 기능 부활!
# ------------------------------------------------------------------
@router.post("/start", status_code=status.HTTP_201_CREATED)
async def start_diagnosis(
    request: DiagnosisStartRequest, 
    db: AsyncSession = Depends(get_db),
    llm: GeminiService = Depends(GeminiService), caller: Caller = Depends(get_caller)):
    await assert_can_access_participant(caller, request.participant_id, db)
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
        try:   # (2026-11-10 P9-6) 첫 인사도 페르소나 말투로(Jessica 는 '~습니다/~습니까'만)
            from diag_project.services.persona_register import apply_register as _areg_first
            first_msg_content = _areg_first(_coach_name, first_msg_content)[0]
        except Exception as _e_first:   # noqa: BLE001
            logger.warning("첫 인사 말투 교정 실패 — 건너뜀: %s", _e_first)
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
    caller: Caller = Depends(get_caller),
):
    await assert_can_access_session(caller, request.session_id, db)
    use_phase3a = phase3a_enabled()
    if use_phase3a:
        # (2026-11-11 단계 표시) 턴이 도는 동안의 단계를 세션별로 기록 — 프론트가 GET /{sid}/turn_stage 로 읽어 대기 문구를 바꾼다
        _tp.start(str(request.session_id))
        try:
            return await _submit_message_phase3a(request, db, llm)
        finally:
            _tp.clear(str(request.session_id))
    return await _submit_message_legacy(request, db, llm)


@router.get("/{session_id}/turn_stage")
async def get_turn_stage(session_id: uuid.UUID, db: AsyncSession = Depends(get_db), caller: Caller = Depends(get_caller)):
    """(2026-11-11 단계 표시) 지금 돌고 있는 코치 턴의 단계 — reading(답을 읽는 중) → thinking(질문을 고르는 중) → polishing(문장을 다듬는 중).
    돌고 있는 턴이 없으면 idle. 프로세스 메모리라 재시작하면 idle 로 보인다(프론트는 점 세 개만 보인다)."""
    await assert_can_access_session(caller, session_id, db)
    return _tp.get_stage(str(session_id))


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

    def _vv_total() -> int:   # (2026-11-04 P3 3차) 어미 변주 인덱스는 세션 누적 — 챕터 경계에서 같은 꼬리가 이어지지 않게
        return sum(int(v or 0) for v in ((session.self_assessment_data or {}).get("voice_variant_count") or {}).values())
    from diag_project.database import sql_count as _sqlc
    _sqlc.set(0)   # 이 턴의 SQL 문 수(FM_SQL_COUNT=1 일 때만 집계)
    _style_tail = ""

    _gen = llm.generate_phase3a_interaction

    async def _timed_regen(**kw):
        """재생성 호출 래퍼 — 횟수·시간 누적 + 꼬리 블록 자동 전달.
        (2026-11-11 P10-1) 스몰톡 턴(_tm["no_regen"])은 LLM 1회만 — 재생성 요청이 와도 부르지 않고 빈 응답을 돌려준다(호출 지점은 결정론 교정으로 넘어간다)."""
        # (2026-11-11 재생성 예산) 한 턴에서 모든 검사를 합쳐 재생성은 최대 1회 — 집중 호출(여는 문장·슬롯·요약·마지막 받기)의 다시 쓰기도 같은 예산.
        #   예산을 쓴 뒤의 위반은 호출 지점의 결정론 수선(삭제·자르기·대상 붙이기·구절 인용 받기)으로만 처리하고, 수선도 안 되면 그대로 내보내 로그에 남긴다.
        _why_rg = kw.pop("why", None)
        if _tm.get("no_regen") or _tm.get("budget_used"):
            _tm["regen_skipped"] = int(_tm.get("regen_skipped") or 0) + 1
            return {"reply": "", "error": "no_regen"}
        _tm["budget_used"] = 1
        _r0 = _time.perf_counter()
        _tm["regen_n"] += 1
        _tm.setdefault("regen_why", []).append(str(_why_rg or "?"))    # (P11b) 재생성 사유 — 보고에 사유별 건수를 낸다
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
    # (2026-11-04 BEI) 사례 단계 턴 + ALIGN(첫 앵커를 품는다) 뒤의 답만 이탈 카운팅 대상
    _BEI_PROBE_INSTR = set(_bei.BEI_INSTRUCTIONS) | {"COMPETENCY_ALIGN", "ABORT_CONFIRM"}
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

    # 4-b. 코치 페르소나 — 모든 고정 문장(여는 앵커·정의 질문·슬롯)의 어미 변환과 Layer3 페르소나 블록이 읽는다.
    coach_key = _coach_key_from_id(session.coach_id)
    _persona = COACHES_PERSONA.get(coach_key) or {}
    state["coach_persona"] = {
        "name": _persona.get("name", ""),
        "coaching_style": _persona.get("coaching_style", ""),
        "tags": _persona.get("tags", ""),
    }

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
                    variant=_vv_total())

    # (2026-10-28 P0-4·P0-7) 사용자 입력 이상 — LLM 호출·원장 전진 없이 시스템 고정 응답으로 직전 질문을 다시 낸다.
    #   종류: 직전 입력 반복 / 세션 앞 답변·기존 사건과 중복 / 코치 질문 되돌아옴 / 일시정지 문구 오입력 /
    #   안내 뒤 비실질 입력 / 정의 답 10자 미만 / 질문 뒤 '네·sp·??'. 판정은 services/input_anomaly.detect(순수 함수).
    _anomaly_override_text = None
    _reask_final = None  # (2026-11-12 P11d-1) 다시 묻기 턴의 완성 문장(사과 + 질문 / 질문) — 전용 호출이 만들고, 뒤 단계가 바꾸지 못하게 끝에서 다시 놓는다
    _reask_kind = None  # (2026-11-12 P11-A3·H) 'clarify'(되묻기) | 'contentless'(받을 내용 없는 답) — 사례 턴에서 원장·슬롯 판정 없이 직전 질문만 다시 쓴다
    _align_ctx = None   # (2026-10-28 P0-1) ALIGN 조립 재료 — 후처리 끝에 render_align 으로 조립
    try:
        from diag_project.services import input_anomaly as _ia
        from diag_project.services.intro_messages import persona_line as _pl_an
        _prev_model_msgs_a = [m for m in history_messages if (m.role == MessageRole.MODEL or m.role == "model")]
        _prev_instr_a = _prev_model_msgs_a[-1].instruction_used if _prev_model_msgs_a else None
        _prev_probe_a = _prev_model_msgs_a[-1].probe_type_used if _prev_model_msgs_a else None
        _store_a = dict(session.self_assessment_data or {})
        # (2026-11-06 P7-3) 직전 턴이 '그만하겠다' 안내(USER_REQUESTS_PAUSE, 선택 대기)였으면: '이어서' 류 입력은 LLM·원장 없이 직전 질문을 다시 낸다.
        _pend_up = dict(_store_a.get("pending_instruction") or {})
        _user_pause_resume = (_pend_up.get("kind") == "user_pause" and _prev_instr_a == "USER_REQUESTS_PAUSE")
        if _user_pause_resume:
            _store_a.pop("pending_instruction", None)
            session.self_assessment_data = _store_a
            from sqlalchemy.orm.attributes import flag_modified as _fm_up
            _fm_up(session, "self_assessment_data")
            if _ia.is_pause_continue_phrase(request.content) and _pend_up.get("question"):
                _anomaly_override_text = f"{_pl_an((state.get('coach_persona') or {}).get('name'), 'continue_ack')} {_pend_up['question']}"
                instruction_used = "QUESTION_REASK"
                _tm["anomaly"] = "user_pause_resume"
        _anomaly = None if (_user_pause_resume and _anomaly_override_text) else _ia.detect(
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
            _ep_an = _bei.current_episode(_store_a, chapter) if chapter else None
            _tgt_an = ((_ep_an or {}).get("opener_sub") or "-") if chapter else "-"
            _ac_all = dict(_store_a.get("anomaly_counts") or {})
            # (2026-11-12 P11e-1) 같은 답(직전 답 반복·앞 답 중복)은 한 사례에서 종류를 합쳐 센다 — 안내는 한 번, 두 번째에는 직전 질문을 다시 붙이지 않고 그 사례를 닫는다
            _ac_kind = "repeat" if _anomaly.kind in ("repeat_prev", "repeat_any") else _anomaly.kind
            _ac_key = f"{chapter}|{_tgt_an}|{_ac_kind}"
            _ac_n = int(_ac_all.get(_ac_key, 0) or 0) + 1
            if _anomaly.kind in ("repeat_any", "ack_reask", "clarify"):
                _ac_all[_ac_key] = _ac_n; _store_a["anomaly_counts"] = _ac_all
                session.self_assessment_data = _store_a
                from sqlalchemy.orm.attributes import flag_modified as _fm_ac
                _fm_ac(session, "self_assessment_data")
            # (2026-11-04 BEI) 같은 사례에서 2회째 단답·반복은 고정 응답 없이 사례 단계로 — 더 작게·다른 각도 재질문(NO_CASE_REFRAME) 1회, 그 뒤 사례 폐기
            if _anomaly.kind == "repeat_prev":
                _ac_all[_ac_key] = _ac_n; _store_a["anomaly_counts"] = _ac_all
                session.self_assessment_data = _store_a
                from sqlalchemy.orm.attributes import flag_modified as _fm_ac2
                _fm_ac2(session, "self_assessment_data")
            # (P11e-1) 같은 질문 2회 상한에 안내 턴이 다시 붙이는 질문도 넣는다 — 그 질문이 이 영역에서 이미 두 번 나갔으면 안내로 한 번 더 붙이지 않고 사례를 닫는 길로
            _q_seen_an = 0
            if _anomaly.kind in ("repeat_prev", "repeat_any") and _q_a and chapter:
                from diag_project.services.turn_checks import same_question as _sq_an
                for _m_an in history_messages:
                    if (_m_an.role == MessageRole.MODEL or _m_an.role == "model") and _m_an.chapter == chapter:
                        _lq_an = [x.strip() for x in split_sentences(_m_an.content or "") if x.strip() and is_question_sentence(x)]
                        if _lq_an and _sq_an(_lq_an[-1], _q_a):
                            _q_seen_an += 1
            _skip_an = (_anomaly.kind in ("repeat_any", "ack_reask", "repeat_prev", "clarify") and (_ac_n >= 2 or _q_seen_an >= 2)
                        and chapter and _tgt_an != "-")
            _in_case_an = bool(chapter and _ep_an is not None and _ep_an.get("status") == "open" and _tgt_an != "-")
            if _skip_an:
                state["bei_anomaly_repeat"] = _anomaly.kind
                _tm["anomaly"] = f"{_anomaly.kind}#{_ac_n}→bei"
            elif _anomaly.kind in ("clarify", "ack_reask") and _in_case_an:
                # (2026-11-12 P11-A3·H) 사례 턴의 되묻기('뭔소리야')·내용 없는 답('네, 맞아요'): 고정 문장으로 같은 질문을 되풀이하지 않는다.
                #   리더 턴·슬롯 판정을 쓰지 않고(원장 그대로) 코치가 직전 질문만 다시 쓴다 — 되묻기는 쉬운 말로(짧은 사과 한 마디는 고정), 내용 없는 답은 장면 하나로 좁혀서.
                #   같은 대상에서 2회째면 위 분기(사례 단계)가 받는다.
                _reask_kind = "clarify" if _anomaly.kind == "clarify" else "contentless"
                _tm["no_regen"] = 1      # (2026-11-12 P11c-5) 다시 묻기 턴에는 어떤 재생성도 끼어들지 않는다 — 사과 1문장 + 질문 1개(내용 없는 답 뒤에는 질문 1개)
                state["bei_reask_only"] = _reask_kind
                instruction_used = "EPISODE_PROBE"          # 결정기가 INVALID_INPUT·META 로 본 턴도 사례 턴으로 돌린다
                _skip_an = True
                _tm["anomaly"] = f"{_anomaly.kind}→reask"
            elif _anomaly.kind == "clarify":
                # 사례 밖(라포·안내·정의 질문)의 되묻기: 짧은 사과 + 같은 질문(정의 질문은 '짧게라도 괜찮다' 꼴, 안내 뒤는 궁금한 점을 물어도 된다는 문장)
                if _prev_instr_a in ("COMPETENCY_ASK", "DIAGNOSIS_CONFIRM") and chapter:
                    from diag_project.services.korean import with_josa as _wj_cl
                    _cn_cl = COMPETENCY_FRAMEWORK.get(chapter, {}).get("name", "이 역량")
                    _anomaly_override_text = f"{_pl_an(_pn_a, 'clarify_sorry')} {_pl_an(_pn_a, 'definition_reask', cn_eul=_wj_cl(_cn_cl, '을/를'))}"
                elif _prev_instr_a == "DIAGNOSIS_INTRO":
                    _anomaly_override_text = _pl_an(_pn_a, "confirm_reask")
                else:
                    _anomaly_override_text = f"{_pl_an(_pn_a, 'clarify_sorry')} {_q_a}"
                instruction_used = "CLARIFY_REASK"
            elif _anomaly.kind == "decline_confirm":
                _anomaly_override_text = _pl_an(_pn_a, "confirm_decline"); instruction_used = "CONFIRM_REASK"
            elif _anomaly.kind == "repeat_prev":
                # (2026-11-12 P11-I) 같은 답 안내는 문구 3종을 돌려 쓰고, 세션 2회째부터는 같은 질문을 되풀이하지 않고 다른 장면을 청한다
                from diag_project.services.intro_messages import duplicate_answer_line as _dal_an
                _dup_n = int(_store_a.get("dup_notice_n") or 0) + 1
                _store_a["dup_notice_n"] = _dup_n
                session.self_assessment_data = _store_a
                from sqlalchemy.orm.attributes import flag_modified as _fm_dn
                _fm_dn(session, "self_assessment_data")
                _dup_line, _dup_has_q = _dal_an(_pn_a, _dup_n)
                _anomaly_override_text = _dup_line if _dup_has_q else f"{_dup_line} {_q_a}"; instruction_used = "INPUT_REPEATED"
                _tm["dup_notice"] = _dup_n
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
            else:   # ack_reask 1회째 — "그럼 여쭤볼게요." + 같은 질문(마지막 질문 문장만)
                # (2026-11-05 3단계 전 2) 직전 코치 턴이 형식 검사를 못 넘었거나(format_miss) 질문이 둘·유도형이면 그대로 되묻지 않는다 —
                #   사례 단계로 보내 LLM 이 더 작은 질문을 새로 쓴다(bei_anomaly_reask 신호). 사례 밖(라포·정의)에서는 종전대로.
                from diag_project.services.output_guard import count_question_markers as _cqm_an, is_leading_choice_question as _ilc_an
                _prev_gl = next((g for g in reversed(_store_a.get("guard_log") or []) if isinstance(g, dict)), {})
                _q_ok = bool(_q_a) and not _prev_gl.get("format_miss") and _cqm_an(_q_a) == 1 and not _ilc_an(_q_a)
                if _q_ok or not (chapter and _tgt_an != "-"):
                    _anomaly_override_text = f"{_pl_an(_pn_a, 'reask_anchor')} {_q_a}"; instruction_used = "ANCHOR_REASK"
                else:
                    _skip_an = True
                    state["bei_anomaly_reask"] = 1
                    _tm["anomaly"] = f"{_anomaly.kind}→bei(regen)"
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

    # ── (2026-11-04 BEI) 사례 단계 — LLM 호출 '이전'에 슬롯 판정(Haiku 1콜)·사례 종료·하위역량 매핑(1콜)·다음 상태를 결정한다.
    #   결정기는 EPISODE_PROBE 를 내고, 여기서 EPISODE_OPEN / NO_CASE_REFRAME / SWEEP_ANCHOR / SWEEP_FOLLOWUP / CHAPTER_READY_TO_END 로 덮어쓴다.
    #   원장(episodes·covered·bei_turns…)은 session.self_assessment_data 에 두고, LLM 실패·일시정지 제안 턴은 스냅숏으로 되돌린다.
    #   설계: docs/design_bei_2026-11.md §1~§4 · 순수 함수: services/bei_engine · 판정: services/slot_judge
    from diag_project.data.competencies import find_sub_key_by_name as _fsk_b
    from diag_project.services.slot_judge import judge_slots as _judge_slots, map_episode as _map_episode, sub_defs_for as _sub_defs
    current_target_sub = None
    _ledger_snapshot = None
    _bei_ep = None                 # 이번 턴 LLM 이 겨냥하는 사례(카드)
    _bei_closed: list[dict] = []   # 이번 턴에 종료된 사례 — 9단계에서 Event 행으로 쓴다
    _bei_anchor_text = None        # EPISODE_OPEN·SWEEP_ANCHOR 에 시스템이 붙일 앵커(EPISODE_OPEN 은 P4-4 여는 문장: 왜 묻는지 + 있었는지 질문)
    _opener_task = None            # (호출 순서) 여는 문장 렌더 — 코치 본 호출과 병렬로 돌리고 본 호출 뒤에 합친다
    _sweep_seq_b = 0               # (P4-5) 연속 SWEEP 순번 — 2 이상이면 앵커 앞 다리 문장 필수
    _bridge_mat_b = None           # (P4-5) 다리 재료 — 앞 사례에서 리더가 쓴 말
    _bei_user_text = (state.get("resume_pending") or {}).get("user_text") or request.content or ""
    _all_subs_b = list(state.get("all_subcompetencies") or [])
    _ch_msgs_b = [m for m in history_messages if m.chapter == chapter] if chapter else []
    _turn_index_b = state.get("turn_count", 0) + state.get("rapport_turn_count", 0)

    def _anchor_for_sub(sub: str | None, *, alt: bool = False) -> str:
        """여는 앵커·SWEEP 앵커 — 사전 52문(세션 회차로 회전) + 페르소나 어미. alt=True 면 다른 문안(같은 하위역량을 이 챕터에서
        이미 여는 질문으로 물었을 때 — s2a Jessica 가 SWEEP 에서 ALIGN 앵커를 그대로 되물었다)."""
        from diag_project.services.anchor_render import dict_anchor as _da
        from diag_project.services.output_guard import strip_frame_lead as _sfl
        _k = _fsk_b(chapter, sub) if (chapter and sub) else None
        _pos = int((session.self_assessment_data or {}).get("anchor_variant") or 0) + (1 if alt else 0)
        # (2026-11-13 P12-4) 끝맺음을 여러 종으로 — 꼬리 변형 가운데 이번 영역에서 가장 덜 쓴 끝맺음을 고른다(같으면 세션 순번 차례).
        #   11/13 운영 Michael: '하나만 들려주세요' 6회 — 순번만 돌려서는 LLM 이 쓴 질문의 끝맺음과 겹쳤다.
        from diag_project.services.persona_voice import MICHAEL_TAIL_N as _mtn_a, persona_key as _pk_a, voice_question as _vq_a
        from diag_project.services.turn_checks import tail_key as _tk_a
        _pn_a2 = (state.get("coach_persona") or {}).get("name")
        _raw_a = _sfl(_da(_k, _pos))
        _nv_a = _mtn_a if _pk_a(_pn_a2) == "Michael" else 3
        _base_a = _vv_total()
        _used_a: dict = {}
        for _key_a in _chapter_question_tails():
            _used_a[_key_a] = _used_a.get(_key_a, 0) + 1
        _cands_a = [_vq_a(_pn_a2, _raw_a, variant=_base_a + i) for i in range(_nv_a)]
        _tm["voiced"] = 1
        return min(enumerate(_cands_a), key=lambda x: (_used_a.get(_tk_a(x[1]), 0), x[0]))[1]

    def _chapter_questions() -> list[str]:
        """이번 영역에서 코치가 이미 한 질문 문장들."""
        _out_cq: list[str] = []
        for _m_cq in history_messages:
            if (_m_cq.role == MessageRole.MODEL or _m_cq.role == "model") and chapter and _m_cq.chapter == chapter:
                _out_cq.extend(x.strip() for x in split_sentences(_m_cq.content or "") if x.strip() and is_question_sentence(x))
        return _out_cq

    def _chapter_question_tails() -> list[str]:
        from diag_project.services.turn_checks import tail_key as _tk_cq
        return [_tk_cq(x) for x in _chapter_questions()]

    async def _opener_for(sub: str | None, fallback_q: str) -> tuple[str, str]:
        """(2026-11-05 P4-4) 사례 여는 문장 = [왜 묻는지 1문장] + [있었는지 질문] — LLM 렌더(형식 검사·재생성 1회), 불합격은 사전 앵커(fallback_q)."""
        # (2026-11-13 P12-6) 여는 문장은 질문만 — 칸 설명을 문형에 끼워 넣은 문장("…에 관한 건데요", "다음은 …에 대해서예요", "이번에는 … 쪽 이야기")이
        #   어색했다(11/13 운영 Michael). 사전 질문(이미 코치 어미, 끝맺음은 _anchor_for_sub 가 고른다)을 그대로 낸다. LLM 호출 없음.
        from diag_project.services.anchor_render import OPENER_BARE_FRAME as _obf_op
        _tm["opener_frame"] = _obf_op
        return fallback_q, "bare"

    def _ep_transcript(ep: dict) -> list[tuple[str, str]]:
        """사례 전문 = 사례를 연 코치 턴부터 이번 리더 답까지(opened_at = 열 때의 챕터 메시지 수)."""
        _from = int(ep.get("opened_at") or 0)
        out = [("model" if (m.role == MessageRole.MODEL or m.role == "model") else "user", m.content or "") for m in _ch_msgs_b[_from:]]
        if not out or out[-1][0] != "user" or out[-1][1] != (request.content or ""):
            out.append(("user", _bei_user_text))
        elif state.get("resume_pending"):
            out[-1] = ("user", _bei_user_text)
        return out

    if chapter and instruction_used in ("COMPETENCY_ALIGN", "EPISODE_PROBE"):
        _store = dict(session.self_assessment_data or {})
        _ledger_snapshot = _bei.snapshot(_store)

        def _open(kind: str) -> dict | None:
            nonlocal _store, current_target_sub
            _sub = _bei.pick_opener(_store, chapter, _all_subs_b) if kind == "episode" else _bei.sweep_target(_store, chapter, _all_subs_b)
            if not _sub:
                return None
            _store, _ep_new = _bei.new_episode(_store, chapter, _sub, _fsk_b(chapter, _sub), kind=kind)
            _ep_new["opened_at"] = len(_ch_msgs_b)
            _mqp_o = dict(_store.get("michael_q_pending") or {}); _mqp_o.pop(chapter, None); _store["michael_q_pending"] = _mqp_o   # 사례 경계에서 대기 해제
            _store = _bei.update_episode(_store, chapter, _ep_new)
            _store = _bei.set_chapter_state(_store, chapter, _bei.STATE_EPISODE if kind == "episode" else _bei.STATE_SWEEP)
            current_target_sub = _sub
            return _ep_new

        async def _close_and_map(ep: dict, status: str) -> None:
            nonlocal _store
            labels: list[dict] = []
            if status not in ("no_case", "repeat") and _bei.filled_slots(ep):
                labels = await _map_episode(llm, transcript=_ep_transcript(ep), chapter_name=COMPETENCY_FRAMEWORK.get(chapter, {}).get("name", chapter),
                                            sub_defs=_sub_defs(chapter), opener_sub=ep.get("opener_sub"))
            _store = _bei.close_episode(_store, chapter, ep, status, labels, _all_subs_b)
            if status == "no_case":
                _store = (_bei.mark_unconfirmed(_store, chapter, ep.get("opener_sub")) if ep.get("kind") == "sweep"
                          else _bei.mark_no_case(_store, chapter, ep.get("opener_sub")))
            if status == "repeat":
                _store = _bei.mark_repeat(_store, chapter, ep.get("opener_sub"))      # (P12b-3) 사례 없음과 구분 — 근거는 원래 사례에 있다
            _closed = next((e for e in _bei.episodes(_store, chapter)
                            if e.get("idx") == ep.get("idx") and e.get("kind", "episode") == ep.get("kind", "episode")), None)
            if _closed:
                _bei_closed.append(_closed)
                _tm["mapped"] = [f"{x['sub']}:{x['strength'][0]}" for x in (_closed.get("labels") or [])]
            _tm["closed"] = f"{ep.get('kind', 'episode')}{ep.get('idx')}:{status}"
            _tm["closed_turns"] = int(ep.get("leader_turns") or 0)

        def _next_after_close() -> None:
            nonlocal _bei_ep, instruction_used, _store
            plan = _bei.plan_after_episode(_store, chapter, _all_subs_b)
            if plan == _bei.STATE_EPISODE:
                _bei_ep = _open("episode")
                instruction_used = "EPISODE_OPEN"
                if _bei_ep is None:
                    plan = _bei.STATE_SWEEP
            if plan == _bei.STATE_SWEEP:
                _bei_ep = _open("sweep")
                instruction_used = "SWEEP_ANCHOR"
                if _bei_ep is None:
                    plan = _bei.STATE_CLOSE
            if plan == _bei.STATE_CLOSE:
                _store = _bei.set_chapter_state(_store, chapter, _bei.STATE_CLOSE)
                instruction_used = "CHAPTER_READY_TO_END"
                # (2026-11-05 2단계 판정 4) 종료 턴 요약 재료 — 들은 사례의 상황·행동 인용. 직전 답이 '없다'면 그 답은 받지 않는다.
                # (2026-11-10 P9-9) 재료 = 사례(조기 종료 포함) + 보완 답(SWEEP 에서 들은 것) — 인용이 하나라도 있는 항목만
                state["bei_close_episodes"] = [
                    x for x in (
                        {"idx": e.get("idx"), "kind": e.get("kind", "episode"),
                         **{k: ((e.get("slots") or {}).get(k) or {}).get("quote") or "" for k in ("context", "action", "result")}}
                        for e in _bei.episodes(_store, chapter)
                        if e.get("status") in ("done", "turns", "budget", "stalled", "reserve", "switched", "sweep_done"))
                    if any(x.get(k) for k in ("context", "action", "result"))]
                #   (p9c) 보완 답이 앞 사례의 말을 되풀이한 것('아까 말씀드린 그 일에서요 …')은 재료에서 뺀다 — 중복 재료가 지시문 되읊기를 불렀다
                from diag_project.services.output_guard import _content_chunks as _cc_m
                _seen_m: list[set] = []
                _uniq_m = []
                for _x in state["bei_close_episodes"]:
                    _cx = {c for k in ("context", "action", "result") for c in _cc_m(_x.get(k) or "") if len(c) >= 2}
                    if _cx and any(len(_cx & s_) >= 0.6 * len(_cx) for s_ in _seen_m):
                        continue
                    _seen_m.append(_cx); _uniq_m.append(_x)
                state["bei_close_episodes"] = _uniq_m
                state["bei_close_no_case"] = bool(state.get("bei_last_no_case"))
            _tm["bei"] = plan

        if instruction_used == "COMPETENCY_ALIGN":
            # 사례 1 여는 앵커 = ALIGN 꼬리(앵커 문장은 8-b/8-z 가 붙인다). 리더 턴은 다음 답부터 센다.
            _bei_ep = _open("episode")
            _tm["bei"] = "open1"
        else:
            _ep = _bei.current_episode(_store, chapter)
            if _ep is None:
                _bei_ep = _open("episode")
                if _bei_ep is not None:
                    instruction_used = "EPISODE_OPEN"
                    _tm["bei"] = "open_fallback"
                else:
                    _store = _bei.set_chapter_state(_store, chapter, _bei.STATE_CLOSE)
                    instruction_used = "CHAPTER_READY_TO_END"
                    _tm["bei"] = "close"
            elif state.get("bei_reask_only"):
                # (2026-11-12 P11-A3·H) 되묻기·내용 없는 답 — 원장을 건드리지 않는다(리더 턴·슬롯·무진전 횟수 그대로). 카드의 '이번 턴' 슬롯도 그대로다.
                _bei_ep = _ep
                instruction_used = "SWEEP_FOLLOWUP" if (_ep.get("kind") == "sweep" and _ep.get("promote") != "promoted") else "EPISODE_PROBE"
                _tm["bei"] = "reask"
            else:
                _store, _ep = _bei.record_leader_turn(_store, chapter, _ep, turn_index=_turn_index_b)
                _tr = _ep_transcript(_ep)
                _filled_before = len(_bei.filled_slots(_ep))
                _jd = await _judge_slots(llm, transcript=_tr, prev_slots=_ep.get("slots"))
                # (2026-11-06 P7-1) 사례 유무는 사례를 열기 전에 — 여는 답(재질문 답 포함)에 시점·인물·구체 행동이 하나도 없으면(incident=false) 사례가 아니다
                _opening_turn = int(_ep.get("leader_turns") or 0) <= 1 + int(_ep.get("retry") or 0)
                _no_incident = (_jd.get("incident") is False) and _opening_turn and not _bei.filled_slots(_ep)
                _no_case = bool(_jd.get("no_case")) or _no_incident or _bei.is_no_case_text(_bei_user_text) or bool(state.get("bei_anomaly_repeat"))
                _repeat_ask_now = False
                # (2026-11-12 P11e-2) 여는 답이 이번 영역에서 이미 닫힌 사례와 같은 사건이면 새 사례·보완 사례로 올리지 않는다(사례 없음과 같은 길로 간다).
                #   그 답에 새로 나온 사실은 원래 사례의 근거로만 덧붙이고(addenda), 덧붙인 칸과 인용을 그 사례에 따로 적는다.
                if _opening_turn and not _no_case:
                    from diag_project.services.turn_checks import is_new_fact as _newfact_r, same_incident as _same_inc
                    _all_eps_r = _bei.episodes(_store, chapter)
                    _closed_r: dict = {}
                    for _i_r, _e_r in enumerate(_all_eps_r):
                        if _e_r.get("status") not in ("done", "turns", "budget", "stalled", "reserve", "switched", "sweep_done"):
                            continue
                        _a_r = int(_e_r.get("opened_at") or 0)
                        _b_r = next((int(x.get("opened_at") or 0) for x in _all_eps_r[_i_r + 1:] if x.get("opened_at") is not None), len(_ch_msgs_b))
                        _tag_r = _e_r.get("idx") if _e_r.get("kind", "episode") == "episode" else f"sweep{_e_r.get('idx')}"
                        _closed_r[_tag_r] = " ".join((m.content or "") for m in _ch_msgs_b[_a_r:_b_r] if not (m.role == MessageRole.MODEL or m.role == "model"))
                    _rep_tag = _same_inc(_bei_user_text, _closed_r)
                    if _rep_tag is not None:
                        _orig_r = next((e for e in _all_eps_r if (e.get("idx") if e.get("kind", "episode") == "episode" else f"sweep{e.get('idx')}") == _rep_tag), None)
                        _added_r = []
                        if _orig_r is not None:
                            # (2026-11-13 P12b-3) 그 답의 문장을 전부 원래 사례의 덧붙인 기록(addenda)에 남긴다 — 지금 묻던 칸(sub)을 붙여서.
                            #   p12: 비전 칸의 답에 "교육팀이 어떤 모습이 될지 그려서 보여주고"가 있었는데 칸 판정 인용 하나만 남았다. new = 원래 사례에 없던 사실.
                            _orig_r = dict(_orig_r)
                            for _s_r in split_sentences(_bei_user_text or ""):
                                _s_r = _s_r.strip()
                                if len(re.sub(r"\s+", "", _s_r)) < 8:
                                    continue
                                _added_r.append({"sub": _ep.get("opener_sub"), "quote": _s_r[:200], "new": bool(_newfact_r(_s_r, _closed_r.get(_rep_tag) or "")),
                                                 "from": f"{_ep.get('kind', 'episode')}{_ep.get('idx')}", "turn": _turn_index_b})
                            if _added_r:
                                _orig_r["addenda"] = list(_orig_r.get("addenda") or []) + _added_r
                                _store = _bei.update_episode(_store, chapter, _orig_r)
                        _ep["repeat_of"] = _rep_tag
                        _no_case = True
                        _tm["repeat_case"] = {"of": _rep_tag, "added": len(_added_r), "new": sum(1 for x in _added_r if x.get("new"))}
                        state["bei_repeat_case"] = True
                        if not _ep.get("repeat_asked"):
                            # 닫지 않고 한 번만 청한다 — '그 일은 잘 들었다'는 한마디 + 같은 칸의 다른 장면을 묻는 사전 질문(LLM 호출 없음).
                            #   이 답은 이 사례의 리더 턴으로 세지 않는다(다음 답이 이 사례의 첫 답이다).
                            _ep["repeat_asked"] = 1
                            _ep["leader_turns"] = max(0, int(_ep.get("leader_turns") or 0) - 1)
                            _repeat_ask_now = True
                state["bei_last_no_case"] = _no_case
                _tm["incident"] = _jd.get("incident")
                if not (_no_case and _opening_turn):
                    # 여는 답(재질문 답 포함)이 '그런 일 없다'면 슬롯을 채우지 않는다 — 없는 사례에 인용이 붙는 것을 막는다
                    _ep["slots"] = _bei.merge_slots(_ep.get("slots"), _jd.get("slots"), " ".join(t for r, t in _tr if r == "user"))
                _ep = _bei.update_stall(_ep, _filled_before)
                _tm["stall"] = int(_ep.get("stall") or 0)
                _store = _bei.update_episode(_store, chapter, _ep)
                _tm["slot_judge"] = "stub" if _jd.get("stub") else ("error" if _jd.get("error") else "ok")
                _tm["slots_filled"] = len(_bei.filled_slots(_ep))
                _tm["slot_ctx"] = ((_ep.get("slots") or {}).get("context") or {}).get("status")      # (P11d-3) 상황 칸 판정 상태 — 시점·인물을 말했는데 안 찬 턴을 찾는 기록
                if _repeat_ask_now:
                    # (P12b-3) 닫힌 사례를 다시 말한 답 — 고정 한마디 + 같은 칸의 다른 사전 질문으로 한 번만 청한다
                    from diag_project.services.intro_messages import persona_line as _pline_rp
                    _alt_rp = _anchor_for_sub(_ep.get("opener_sub"), alt=True)
                    _anomaly_override_text = f"{_pline_rp((state.get('coach_persona') or {}).get('name'), 'repeat_heard')} 그 일 말고, {_alt_rp}".strip()
                    _bei_ep = _ep; instruction_used = "NO_CASE_REFRAME"; _tm["bei"] = "repeat_ask"; _tm["repeat_ask"] = 1
                elif _ep.get("repeat_asked") and _no_case and _opening_turn:
                    # 한 번 더 청했는데도 다른 장면이 없다(없다는 답·같은 사건을 또 말함) — '사례 없음'과 구분해 repeat 로 닫는다
                    await _close_and_map(_ep, "repeat")
                    _next_after_close()
                elif state.get("bei_anomaly_repeat") in ("repeat_prev", "repeat_any"):
                    # (2026-11-12 P11e-1) 같은 답이 또 들어왔다(안내는 이미 한 번 했다) — 직전 질문을 다시 붙이지 않고 이 사례를 닫고 다음 칸으로
                    _tm["dup_close"] = 1
                    await _close_and_map(_ep, "no_case" if not _bei.filled_slots(_ep) else ("sweep_done" if _ep.get("kind") == "sweep" else "stalled"))
                    _next_after_close()
                elif _ep.get("kind") == "sweep":
                    # SWEEP 항목: 앵커 답 1턴 → (허용되면) 후속 1턴 → 매핑 → 다음
                    if _no_case and int(_ep.get("leader_turns") or 0) <= 1:
                        await _close_and_map(_ep, "no_case")
                        _next_after_close()
                    else:
                        # (2026-11-12 P11b-7) 보완 질문의 답이 실제 사건이면 일반 사례처럼 올린다 — 빠진 것만 묻고 리더 턴 최대 4, 미질문 예약은 지킨다.
                        #   예산이 모자라면 올리지 않고 종전대로(앵커 + 후속 1턴). 어느 쪽으로 갔는지 원장(항목의 promote·promote_end)에 적는다.
                        _pd_b = _bei.sweep_promote_decision(_store, chapter, _all_subs_b, _ep, incident=_jd.get("incident"))
                        if _pd_b:
                            _ep["promote"] = _pd_b
                            _store = _bei.update_episode(_store, chapter, _ep)
                            _tm["sweep_promote"] = _pd_b
                        if _ep.get("promote") == "promoted":
                            _reason_p = _bei.promoted_done_reason(_ep, _store, chapter, _all_subs_b)
                            if _reason_p:
                                _ep["promote_end"] = _reason_p
                                _tm["sweep_promote"] = f"promoted:{_reason_p}"
                                await _close_and_map(_ep, "no_case" if _reason_p == "stalled_empty" else "sweep_done")
                                _next_after_close()
                            else:
                                _bei_ep = _ep; instruction_used = "EPISODE_PROBE"; _tm["bei"] = "sweep_promoted"
                        elif int(_ep.get("leader_turns") or 0) == 1 and _bei.sweep_followup_allowed(_store, chapter, _all_subs_b, _ep):
                            _bei_ep = _ep; instruction_used = "SWEEP_FOLLOWUP"; _tm["bei"] = "sweep_followup"
                        else:
                            await _close_and_map(_ep, "sweep_done")
                            _next_after_close()
                else:
                    _reason = _bei.episode_done_reason(_ep, _store, chapter, _all_subs_b)   # (P9-1) 미질문 예약 침범 시 'reserve'
                    if _no_case and not _bei.filled_slots(_ep):
                        if int(_ep.get("retry") or 0) < _bei.EPISODE_RETRY_MAX and int(_ep.get("leader_turns") or 0) <= 2 and _reason is None:
                            # (P7-1) 더 작게·다른 각도로 1회(NO_CASE_REFRAME). 그래도 없으면 no_case 기록, 다음 하위역량 — 사례를 열지 않는다
                            _ep["retry"] = int(_ep.get("retry") or 0) + 1
                            _store = _bei.update_episode(_store, chapter, _ep)
                            _bei_ep = _ep; instruction_used = "NO_CASE_REFRAME"; _tm["bei"] = "reframe"
                        else:
                            await _close_and_map(_ep, "no_case")
                            _next_after_close()
                    elif _reason:
                        # (2026-11-12 P11c-4) 'stalled_empty' = 채운 칸 없이 2턴 연속 진전 없음 → 사례 없음으로 닫고 다음 칸으로
                        await _close_and_map(_ep, "done" if _reason == "slots" else ("no_case" if _reason == "stalled_empty" else _reason))   # (P7-1) 'stalled' 포함 — 들은 슬롯만으로 매핑
                        _next_after_close()
                    else:
                        _bei_ep = _ep; instruction_used = "EPISODE_PROBE"; _tm["bei"] = "probe"
                        if _jd.get("switched_case"):
                            state["bei_switched"] = True
        if instruction_used == "EPISODE_PROBE" and _bei_ep is not None and not state.get("bei_reask_only"):
            # (2026-11-13 P12-2) 같은 것을 채우려는 질문은 사례당 2회까지 — 이번 턴이 향하는 것을 사례에 적는다(다시 묻기 턴은 세지 않는다)
            _bei_ep = _bei.bump_slot_ask(_bei_ep, _bei.next_slot(_bei_ep))
            _store = _bei.update_episode(_store, chapter, _bei_ep)
            _tm["ask_slot"] = _bei_ep.get("ask_slot")
        session.self_assessment_data = _store
        from sqlalchemy.orm.attributes import flag_modified as _fm_bei
        _fm_bei(session, "self_assessment_data")
        await db.flush()   # 턴 끝 1회 커밋 — 중간 커밋 없음
        state["instruction_for_this_turn"] = instruction_used
        if instruction_used in ("EPISODE_OPEN", "SWEEP_ANCHOR") and current_target_sub:
            _openers_b = [e.get("opener_sub") for e in _bei.episodes(_store, chapter) if e.get("kind", "episode") == "episode"]
            _bei_anchor_text = _anchor_for_sub(current_target_sub, alt=(instruction_used == "SWEEP_ANCHOR" and current_target_sub in _openers_b))
            if instruction_used == "EPISODE_OPEN":
                # (2026-11-11 호출 순서) 여는 문장 렌더(1.2초, 다시 쓰면 2.5초)는 코치 본 호출과 서로 기다릴 이유가 없다 — 본 호출은 닫는 쪽 받기 1문장만 쓰고
                #   여는 문장의 주제만 알면 된다. 카드에는 사전 앵커(같은 하위역량)를 주고 렌더는 본 호출과 병렬로 돌린 뒤, 본 호출이 끝난 자리에서 합친다.
                import asyncio as _aio_op
                _opener_task = _aio_op.ensure_future(_opener_for(current_target_sub, _bei_anchor_text))
            else:
                _sweep_seq_b = _bei.consecutive_sweeps(_store, chapter)
                _last_ep_b = next((e for e in reversed(_bei.episodes(_store, chapter))
                                   if e.get("kind", "episode") == "episode" and e.get("status") in ("done", "turns", "budget", "stalled", "reserve")), None)
                _qa_b = ""
                if _last_ep_b:
                    _sl_b = _last_ep_b.get("slots") or {}
                    _qa_b = (_sl_b.get("action") or {}).get("quote") or (_sl_b.get("context") or {}).get("quote") or ""
                _bridge_mat_b = f"'{_qa_b[:70]}'" if _qa_b else None
        # 사례 카드(system 프롬프트의 턴 동적 부분)
        _signal = ""
        _ans_len = len((_bei_user_text or "").replace(" ", ""))
        if instruction_used in ("EPISODE_PROBE", "NO_CASE_REFRAME", "SWEEP_FOLLOWUP"):
            if _ans_len < 20 or state.get("contains_avoidance_keywords"):
                _signal = f"직전 답이 짧거나 회피 표지({_ans_len}자) — 더 작은 단위(리더가 말한 그 일에서 처음 한 말)로 묻는다"
            elif _ans_len >= 150:
                _signal = "직전 답이 길고 구체적 — 질문 앞 평서문은 쓰더라도 1문장, 가장 또렷한 장면 하나의 낱말 한두 개만 넣는다(답 전체를 다시 읊지 않는다)"
            if state.get("bei_switched"):
                _signal = (_signal + " / " if _signal else "") + "리더가 다른 사례로 넘어간 듯하다 — 한 번은 따라가되 질문은 지금 사례로 돌아온다"
            if state.get("bei_repeat_case") and instruction_used == "NO_CASE_REFRAME":
                _signal = "리더가 앞에서 이미 들은 이야기를 다시 말했다 — 그 이야기는 다시 묻지 않는다. 그것 말고 다른 일이 있었는지를 묻는다"
            if state.get("bei_anomaly_reask"):
                _signal = "리더가 짧게 수긍만 했고 직전 질문은 형식이 어긋나 되묻지 않는다 — 질문만 짧게, 같은 것을 장면 하나로 좁힌 새 질문 하나"
        _weak_hint = None
        if instruction_used == "SWEEP_ANCHOR" and current_target_sub:
            _w_eps = [x for x in (_bei.weak_map(_store, chapter).get(current_target_sub) or []) if isinstance(x, int)]
            if _w_eps:
                # (2026-11-10 P10) 사례를 번호로 부르지 않는다 — 그 사례에서 리더가 쓴 말로 지칭한다
                _w_ep = next((e for e in _bei.episodes(_store, chapter) if e.get("kind", "episode") == "episode" and e.get("idx") == _w_eps[0]), None)
                _w_sl = (_w_ep or {}).get("slots") or {}
                _w_q = ((_w_sl.get("context") or {}).get("quote") or (_w_sl.get("action") or {}).get("quote") or "")[:40]
                _weak_hint = ((f"아까 리더가 '{_w_q}' 라고 말한 이야기에서 이쪽이 살짝 나왔다" if _w_q else "앞서 들은 이야기에서 이쪽이 살짝 나왔다")
                              + " — '그쪽을 하나 더' 결로 잇는다. 그 이야기는 내용으로 지칭하고 번호로 부르지 않는다")
        _prev_eps_card = [{"idx": i + 1, "summary": f"[{e.get('chapter')}] {e.get('summary')}"}
                          for i, e in enumerate((state.get("all_collected_events") or [])[-5:])]
        from diag_project.prompts.phase3a.episode_card import build_episode_card as _bec
        # (2026-11-13 P12-4) 이번 영역에서 두 번 이상 쓴 질문 끝맺음(청하는 꼴) — 카드에 넘겨 다른 끝맺음을 쓰게 한다
        from diag_project.services.turn_checks import ending_counts as _ec_b, ending_label as _el_b
        _end_cnt_b = _ec_b(_chapter_questions())
        _used_end_b = [_el_b(k) for k, v in sorted(_end_cnt_b.items(), key=lambda kv: -kv[1]) if v >= 2]
        state["bei_card"] = _bec(instruction=instruction_used, chapter=chapter, ep=_bei_ep, bei_turns=_bei.bei_turns(_store, chapter),
                                 budget=_bei.chapter_budget(chapter), prev_episodes=_prev_eps_card, signal=_signal,
                                 anchor_text=_bei_anchor_text, sweep_sub=current_target_sub, weak_hint=_weak_hint,
                                 sweep_seq=_sweep_seq_b, bridge_material=_bridge_mat_b, used_endings=_used_end_b)
        logger.info("🧭 BEI [%s] state=%s instr=%s ep=%s%s turns=%d/%d filled=%s closed=%s", chapter, _bei.chapter_state(_store, chapter),
                    instruction_used, (_bei_ep or {}).get("kind", "-"), (_bei_ep or {}).get("idx", "-"), _bei.bei_turns(_store, chapter),
                    _bei.chapter_budget(chapter), _tm.get("slots_filled"), _tm.get("closed"))
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
    # (2026-11-04 BEI) Layer2 = 역량 정의 1문장 + 하위역량 이름·행동 단서(내부용). 목표·특수 지시·시작 스크립트·Backup 은 폐지.
    _LAYER2_EXCLUDED = {"COMPETENCY_ALIGN", "DIAGNOSIS_INTRO"}
    chapter_context = "" if instruction_used in _LAYER2_EXCLUDED else chapter_context_bei(chapter)
    # 페르소나 통합 system prompt — 사용자가 '선택한' 코치(session.coach_id) 기준.
    # (2026-11-04 BEI) 페르소나는 BEI 단계 앞(아래 4-b)에서 state 에 넣는다 — 여는 앵커 어미 변환이 페르소나를 봐야 한다.
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
            "\n\n🔁 [시스템 — 재개] 직전 턴에 잠시 쉬어갈지 안내했고 리더님이 '계속'을 골랐습니다. '계속'이라는 이번 메시지는 재개 의사일 뿐이니 "
            "그 말에는 답하지 않습니다. 아래 [Latest User Message]는 그 전에 리더님이 하신 답변입니다 — 그 답변에서 들은 사실을 리더님이 쓴 낱말을 넣어 평서문 한 문장으로 쓰고, "
            "이번 지시대로 이어가세요. 새 주제·새 앵커·'다시 시작' 류 인사 금지.")
    if state["style_at_tail"]:
        from diag_project.prompts.phase3a.layer3_state import build_style_tail
        _style_tail = build_style_tail(state)
    user_name = state.get("user_name", "리더")
    # (2026-09-22) light 턴(라포·INTRO·CONFIRM·ALIGN·META 등)은 BEI 절을 뺀 Layer1 — 매핑표 docs/prompt_reduction_2026-09-22.md
    _LIGHT_LAYER1_INSTRUCTIONS = {
        "RAPPORT_BUILDING", "DIAGNOSIS_INTRO", "DIAGNOSIS_CONFIRM", "COMPETENCY_ASK", "COMPETENCY_ALIGN",
        "META_QUESTION_FROM_USER", "USER_REQUESTS_PAUSE", "INVALID_INPUT", "PROMPT_INJECTION_DETECTED",
        "NAME_RECONFIRM",
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
        system_override_text = _sys_line("await_choice", (state.get('coach_persona') or {}).get('name'), nm=_nm)   # (P11-A5) 코치 말투별

    # 🚨 3-Strike 강제 종료 (Session Abort) — 최우선 처리.
    #   세션 전체 비생산 응답 누적 → 정중한 종료 멘트 출력 후 세션 영구 종료.
    #   (3회 카운팅은 철저히 백엔드 내부 처리 — 멘트에 '3회' 등 수치 노출 금지.)
    #   LLM 을 우회해 정해진 문구만 내보내고 다음 질문은 절대 생성하지 않는다.
    _is_aborted = (instruction_used == "SESSION_ABORT_3STRIKE")
    if _is_aborted:
        system_override_text = _sys_line("abort_3strike", (state.get('coach_persona') or {}).get('name'))   # (P11-A5) 코치 말투별

    # ⚠️ 최후 의향 확인(Warning) — 종료 직전 1회. 세션은 아직 종료하지 않는다.
    #   (경고 후에도 유효 답변 없이 억지 → 다음 턴에 SESSION_ABORT_3STRIKE)
    _is_warning = (not _is_aborted
                   and instruction_used == "SESSION_ABORT_WARNING")
    if _is_warning:
        # 재촉·시간불평("빨리 합시다")으로 촉발된 경고면 과제6 지정 문구로,
        # 그 외(남탓·비아냥)는 기본 경고 문구로 분기.
        system_override_text = _sys_line("warning_rush" if detect_rush(request.content) else "warning_focus", (state.get('coach_persona') or {}).get('name'))   # (P11-A5)

    # 🙋 이름 재확인(Fallback) — 명확한 성함을 못 뽑았을 때 1회. 억지 호칭 금지.
    _is_name_reconfirm = (not _is_aborted and not _is_warning
                          and instruction_used == "NAME_RECONFIRM")
    if _is_name_reconfirm:
        system_override_text = _sys_line("name_reconfirm", (state.get('coach_persona') or {}).get('name'))   # (P11-A5) 종전 문장은 합쇼체와 해요체가 한 턴에 섞여 있었다

    # 🚦 A-3: 참여 이탈 중단 '확인' — 곧바로 끊지 않고 선택권을 준다.
    #   평가·판단 표현 절대 금지("사례를 못 하셨다"/"참여도" 등) — 대상자가
    #   자신이 부족해 끊긴 것으로 느끼면 재개율이 떨어진다. 고정 문구.
    _is_abort_confirm = (not _is_aborted and not _is_warning
                         and not _is_name_reconfirm
                         and instruction_used == "ABORT_CONFIRM")
    if _is_abort_confirm:
        system_override_text = _sys_line("abort_confirm", (state.get('coach_persona') or {}).get('name'))   # (P11-A5) 코치 말투별
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
        system_override_text = _sys_line("abort_disengaged", (state.get('coach_persona') or {}).get('name'))   # (P11-A5) 코치 말투별
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
            greeting_question=state.get("current_greeting_question"),   # (2026-11-04 P3-5)
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
        # (2026-11-12 P11b-2) 다리('…오늘 흐름부터 안내드리겠습니다.')가 안내를 예고하므로 본문의 첫 문장(같은 예고)은 뺀다
        system_override_text = f"{_pl_i((state.get('coach_persona') or {}).get('name'), 'intro_bridge')}\n\n{build_intro_anchor_section((state.get('coach_persona') or {}).get('name'), lead=False)}"
        _tm["intro_dup"] = 1

    # (2026-11-11 P10-1) 스몰톡 턴: 리더 답이 10자 이하이거나 받을 내용이 없으면('그냥 그래요'·'별로요') LLM 을 부르지 않는다 —
    #   고정 받기 1문장 + 예비 되물음(코치별 3종 × 시간대). 그 밖의 스몰톡 턴은 LLM 1회만(재생성 없음, 검사 탈락 시 예비 되물음).
    _smalltalk_turn = (not _is_aborted and not _is_warning and not _is_name_reconfirm and instruction_used == "RAPPORT_BUILDING"
                       and state.get("rapport_turn_count", 0) == 1)

    def _smalltalk_reserve() -> str:
        from diag_project.services.intro_messages import smalltalk_reserve_question as _srq
        from diag_project.services.time_greeting import current_daypart as _cdp_s
        return _srq((state.get("coach_persona") or {}).get("name"), state.get("current_daypart") or _cdp_s(),
                    sum(map(ord, str(session.id))))   # 세션마다 고정된 순번 — 3종을 세션 사이에서 돌린다

    if _smalltalk_turn and system_override_text is None:
        from diag_project.services.input_anomaly import is_contentless_smalltalk as _ics
        from diag_project.services.intro_messages import smalltalk_flat_receive as _sfr
        _tm["no_regen"] = 1
        if _ics(request.content):
            from diag_project.services.intro_messages import rapport_fixed_receive as _rfr1      # (P12d-2) 3종 가운데 직전 턴에 쓴 것은 뺀다
            system_override_text = f"{_rfr1((state.get('coach_persona') or {}).get('name'), _prev_coach_text, start=0)} {_smalltalk_reserve()}"
            _tm["smalltalk"] = "fixed"
    # (2026-11-12 P11-A1) 스몰톡 되물음(LLM 되물음·예비 되물음)의 답은 다음 턴(라포 2턴, 담당 업무 질문 턴)에 온다. 종전 고정 받기는 라포 1턴에만 걸려 있어
    #   "점심에는 무엇을 드셨습니까?" → "밥" 이 LLM 받기로 갔다("밥은 드셨는지 여쭤봐 주신 셈이네요…"). 같은 기준(10자 이하·내용 없음)이면 LLM 을 부르지 않는다.
    if (not _is_aborted and not _is_warning and not _is_name_reconfirm and instruction_used == "RAPPORT_BUILDING"
            and state.get("rapport_turn_count", 0) == 2 and system_override_text is None):
        from diag_project.services.input_anomaly import is_contentless_smalltalk as _ics2
        from diag_project.services.intro_messages import persona_line as _pl_s2, smalltalk_flat_receive2 as _sfr2
        if _ics2(request.content):
            _pn_s2 = (state.get("coach_persona") or {}).get("name")
            from diag_project.services.intro_messages import rapport_fixed_receive as _rfr2
            system_override_text = f"{_rfr2(_pn_s2, _prev_coach_text, start=1)} {_pl_s2(_pn_s2, 'role_q')}"
            _tm["smalltalk"] = "fixed2"; _tm["no_regen"] = 1

    # (2026-11-13 P12-7) 담당 업무 답(라포 3턴)이 조사 없는 낱말 나열이면('교육팀 팀장 4명 팀원 교육기획') 풀어 옮기지 않는다 — 고정 받기 + 기대 질문.
    #   11/13 운영: "팀장 네 분을 이끌면서" 로 잘못 옮겼다. 10자 이하 기준은 이 턴에 걸지 않는다(짧아도 '영업팀장입니다' 는 받을 말이 있다).
    if (not _is_aborted and not _is_warning and not _is_name_reconfirm and instruction_used == "RAPPORT_BUILDING"
            and state.get("rapport_turn_count", 0) == 3 and system_override_text is None):
        from diag_project.services.input_anomaly import is_bare_noun_list as _ibnl
        if _ibnl(request.content):
            from diag_project.services.intro_messages import persona_line as _pl_s3, smalltalk_flat_receive2 as _sfr3
            _pn_s3 = (state.get("coach_persona") or {}).get("name")
            from diag_project.services.intro_messages import role_fixed_receive as _rfr3      # (P12d-2) 다음 질문(기대)으로 이어지는 짧은 말
            system_override_text = f"{_rfr3(_pn_s3)} {_pl_s3(_pn_s3, 'expect_q')}"
            _tm["smalltalk"] = "fixed3"; _tm["no_regen"] = 1

    # (2026-11-14 P12d-1) 둘째 이후 영역의 시작 턴(COMPETENCY_ASK) — LLM 호출 없이 조립한다: [영역별 범위 문장(사전, 코치 말투)] + [정의 질문 5종 중 하나].
    #   11/13 운영·p12b·p12c: LLM 이 쓴 범위 문장 자리에 경험을 묻는 문장("…그 과정이 어땠는지 떠올라 보세요"), "정의 질문은 바로 이어서 드릴게요" 가 나갔다.
    #   넘어간다는 말은 직전 턴(영역 종료 턴)의 고정 다리가 이미 했다. 첫 영역(DIAGNOSIS_CONFIRM)은 '시작해도 되겠느냐'의 답(거절·질문)을 LLM 이 받아야 해 그대로 둔다.
    if (instruction_used == "COMPETENCY_ASK" and chapter and system_override_text is None and not _is_aborted and not _is_warning
            and chapter in COMPETENCY_FRAMEWORK):
        from diag_project.services.intro_messages import chapter_scope_line as _csl_ca, definition_question as _dq_ca
        from diag_project.services.persona_register import apply_register as _areg_ca
        _pn_ca = (state.get("coach_persona") or {}).get("name")
        _ch_i_ca = [k for k in COMPETENCY_FRAMEWORK if k != "supplementary"].index(chapter)
        _scope_ca = _areg_ca(_pn_ca, _csl_ca(chapter, _pn_ca), scope="strict")[0]      # 합쇼체 코치는 합쇼체 판(사전), 그 위에 말투 교정
        system_override_text = f"{_scope_ca} {_dq_ca(COMPETENCY_FRAMEWORK[chapter].get('name', '이 역량'), _pn_ca, _ch_i_ca)}".strip()
        _tm["def_variant"] = _ch_i_ca % 5; _tm["scope_fixed"] = 1; _tm["no_regen"] = 1

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
            # 주입 대응 턴: 사례 수집 없음 — 거절+복귀 문장만 (경량)
            "PROMPT_INJECTION_DETECTED",
        }
        _l0 = _time.perf_counter()
        _tp.set_stage(str(session.id), "thinking")
        if instruction_used == "CHAPTER_READY_TO_END":
            # (2026-11-11 호출 순서) 챕터 종료 턴은 코치 본 호출을 하지 않는다 — 본 호출 출력은 쓰이지 않았다(요약은 재료만 주는 집중 호출이 쓰고,
            #   마지막 챕터는 받기 1문장 + 고정 종료 문구, 사례 0 챕터는 고정 문장). 종전에는 본 호출 1회 + 요약 재생성 2회가 먼저 돌았다(p10a·p10b·lb1 전부 집중 호출로 끝남).
            llm_output = {"reply": ""}
            _tm["close_main_skipped"] = 1
        elif _reask_kind and chapter and _bei_ep is not None:
            # (2026-11-12 P11d-1) 다시 묻기 턴은 코치 본 호출 대신 전용 호출 1회로 끝낸다 — 되묻기에는 직전 질문을 더 쉬운 낱말·더 짧은 문장으로,
            #   내용 없는 답에는 직전 질문을 한 가지로 좁혀 다시 묻는다. 직전 질문과 글자가 같거나 질문을 못 썼을 때만 그 칸의 기본 질문으로 바꾼다.
            #   (p11c: 본 호출 + 뒤 단계의 고르기 방식에서는 4턴 모두 직전 질문이 그대로 나갔다.) 다른 검사·재생성은 끼어들지 않는다(no_regen).
            from diag_project.services.input_anomaly import last_question_of as _lqo_rq
            from diag_project.services.intro_messages import line_register as _lreg_rq, persona_line as _pline_rq
            from diag_project.services.reask_render import render_reask as _rr_rq, same_text as _same_rq
            from diag_project.services.turn_checks import default_slot_question as _dsq_rq
            _pn_rq = (state.get('coach_persona') or {}).get('name')
            _orig_rq = _lqo_rq(_prev_coach_text) or ""
            _lead_rq = [t for r, t in _ep_transcript(_bei_ep) if r == "user"][:-1]      # 이번 입력('뭔소리야'·'네')은 뺀다
            _q_rq, _mode_rq = await _rr_rq(llm, kind=_reask_kind, prev_question=_orig_rq, leader_texts=_lead_rq, persona_name=_pn_rq)
            if not _q_rq:
                _un_rq = (_bei.unfilled_slots(_bei_ep) or ["reflection"])
                _topic_rq = ((_bei_ep.get("slots") or {}).get("context") or {}).get("quote") or ""
                _formal_rq = _lreg_rq(_pn_rq) == "formal"
                _cands_rq = [_dsq_rq(_un_rq[0], formal=_formal_rq, topic_text=_topic_rq), _dsq_rq(_un_rq[0], formal=_formal_rq, topic_text=None)] \
                    + [_dsq_rq(sl, formal=_formal_rq, topic_text=_topic_rq) for sl in _un_rq[1:]]
                _q_rq = next((c for c in _cands_rq if not _same_rq(c, _orig_rq)), _cands_rq[0])
                _mode_rq = f"{_mode_rq}→default:{_un_rq[0]}"
            _sorry_rq = _pline_rq(_pn_rq, "clarify_sorry") if _reask_kind == "clarify" else ""
            _reask_final = f"{_sorry_rq} {_q_rq}".strip()
            llm_output = {"reply": _reask_final}
            _tm["reask"] = f"{_reask_kind}:{_mode_rq}"
            # (2026-11-14 P12c-1) 다시 묻기에 넘긴 '직전 질문'과, 그것이 실제로 마지막에 나간 코치 턴의 마지막 질문인지를 남긴다
            _last_coach_rq = next((m.content or "" for m in reversed(history_messages) if (m.role == MessageRole.MODEL or m.role == "model")), "")
            _tm["reask_prev"] = {"q": _orig_rq[:160], "is_last": bool(_orig_rq) and _same_rq(_orig_rq, _lqo_rq(_last_coach_rq) or "")}
            logger.info("🔁 다시 묻기(%s): %r ← %r", _tm["reask"], _reask_final[:80], _orig_rq[:60])
        else:
            # (2026-11-11 호출 순서) 조직관리 정의 잇기 턴(ALIGN)의 사례 1 여는 문장도 본 호출과 병렬로
            if instruction_used == "COMPETENCY_ALIGN" and chapter and current_target_sub and _opener_task is None:
                import asyncio as _aio_al
                _opener_task = _aio_al.ensure_future(_opener_for(current_target_sub, _anchor_for_sub(current_target_sub)))
                _tm["opener_align_task"] = 1
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
            if _opener_task is not None:
                _opener_task.cancel()
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

    # (2026-11-11 호출 순서) 병렬로 돌린 여는 문장 렌더를 여기서 합친다 — 이후 단계는 전부 완성된 여는 문장을 본다
    _opener_result = None
    if _opener_task is not None:
        try:
            _opener_result = await _opener_task
        except Exception as _e_ot:   # noqa: BLE001 — 렌더 실패는 사전 앵커로
            logger.warning("여는 문장 렌더 태스크 실패 → 사전 앵커: %s", _e_ot)
        if instruction_used == "EPISODE_OPEN" and _opener_result:
            _bei_anchor_text, _op_mode = _opener_result
            _tm["opener"] = _op_mode
    _tp.set_stage(str(session.id), "polishing")

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
    # (2026-11-10 P9-8) 이번 자리 = 세션 시작 또는 재개(30분 공백·'다음에 하기' 뒤) 이후. 제안은 40분 뒤 첫 회, 이후 30분 간격, 사례가 끝난 턴에서만.
    from diag_project.services.event_tracker import sitting_start_index as _ssi
    _sit_msgs = history_messages[_ssi(history_messages):]
    _now_sp = datetime.utcnow()
    _sit_elapsed, _sit_n = _sst([m.created_at for m in _sit_msgs if m.created_at], now=_now_sp)
    _last_sp_at = next((m.created_at for m in reversed(_sit_msgs) if m.probe_type_used == "SUGGEST_PAUSE" and m.created_at), None)
    _min_since_sp = max(0.0, (_now_sp - _last_sp_at).total_seconds() / 60) if _last_sp_at else None
    # (2026-11-12 P11b-8) 사례가 자연스럽게 끝난 턴에서만 — 일반 사례가 여섯 가지를 다 채웠거나 8턴에 닿았을 때. 보완 사례가 닫힌 턴·조기 종료(무진전·예약)·
    #   사례 없음 뒤에는 내지 않는다. 영역 경계는 영역 종료 턴의 '다음 챕터로 이동' 대기 화면이 맡는다(그 화면에서 멈췄다가 돌아오면 이어진다).
    _natural_close = _bei.is_natural_close(_tm.get("closed"))
    _backend_pause_suggested = (system_override_text is None and not _llm_error and not state.get("resume_pending") and _ssp(
        elapsed_min=_sit_elapsed, minutes_since_last_suggest=_min_since_sp, instruction_used=instruction_used,
        case_closed=_natural_close,
    ))
    if _tm.get("closed") and not _natural_close and not state.get("resume_pending") and _ssp(
            elapsed_min=_sit_elapsed, minutes_since_last_suggest=_min_since_sp, instruction_used=instruction_used, case_closed=True):
        _tm["pause_block"] = str(_tm.get("closed"))        # 시간은 됐지만 자연스러운 닫힘이 아니라 내지 않았다
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
    _COMPLETE_ALLOWED = {"CHAPTER_READY_TO_END"}   # 챕터 종료는 코드가 확정한다(8-d)
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
    _EARLY_END_ALLOWED = set(_bei.BEI_INSTRUCTIONS) | {
        "META_QUESTION_FROM_USER", "INVALID_INPUT", "RAPPORT_BUILDING", "PROMPT_INJECTION_DETECTED",
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
        elif state.get("suggest_pause_count", 0) >= 2 and not _backend_pause_suggested:   # (P9-8) 시간 기준 제안(30분 간격)은 횟수 상한·강제 종료 승격 대상이 아니다
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
        clean_reply = f"{clean_reply}\n\n{_sys_line('forced_end', (state.get('coach_persona') or {}).get('name'))}"   # (P11-A5) 종전 문장은 '…보여요' 가 합쇼체 사이에 섞여 있었다

    # 일시중지 확정: USER_REQUESTS_PAUSE 면 LLM 의 [SESSION_PAUSE] 마커 누락과
    # 무관하게 무조건 일시중지 처리 (챕터 전환 차단 + 세션 대기 전환).
    _decision_kind = None
    if instruction_used == "USER_REQUESTS_PAUSE":
        _prev_model_p = next((m for m in reversed(history_messages) if (m.role == MessageRole.MODEL or m.role == "model")), None)
        _after_suggest = _prev_model_p is not None and (_prev_model_p.probe_type_used == "SUGGEST_PAUSE" or _prev_model_p.instruction_used == "USER_REQUESTS_PAUSE")
        if _after_suggest:
            is_session_paused = True            # 제안 뒤 '다음에 하기' / 안내 뒤 다시 그만하겠다 → 종전대로 일시정지(재개 가능)
        else:
            # (2026-11-06 P7-3) 자발적 중단 요청: 바로 멈추지 않고 안내 한 줄 + 선택(이어서 하기 / 지금 마치기). 선택 전까지 in_progress.
            is_session_paused = False
            needs_user_decision = True
            _decision_kind = "finish_or_continue"
            state["finish_choice_turn"] = True

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
                     variant=_vv_total())
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
            from diag_project.services.output_guard import count_question_markers as _cqm_r
            if _q_last and _cqm_r(_recv) >= 2:   # (2026-11-05 s2d) 되물음이 두 질문('어떻게 정하세요, 누구와 조율하셨어요?')이면 되물음을 뺀다
                _tm["work_q"] = 1
                _recv = _recv_multi(_recv, max_statements=2, allow_question=False)
                _q_last = ""
            if _q_last and not _sf_ok(_q_last):
                _tm["work_q"] = 1
                _recv = _recv_multi(_recv, max_statements=2, allow_question=False)
                logger.info("✂️ 스몰톡 되물음이 업무·역할 질문 → 삭제: %r", _q_last[:40])
                _q_last = ""
            # (2026-11-10 P9-2) 아직 오지 않은 시간대(오전의 '오후')를 말한 문장은 지운다. 되물음은 물음표로 끝나는 질문형만 —
            #   아니면 되물음을 빼고 아래에서 고정 스몰톡 질문을 붙인다.
            from diag_project.services.output_guard import mentions_future_daypart as _mfd
            from diag_project.services.time_greeting import current_daypart as _cdp_r
            _part_r = state.get("current_daypart") or _cdp_r()
            if _mfd(_recv, _part_r) or (_q_last and not _q_last.rstrip().endswith("?")):
                _tm["smalltalk_time"] = 1
                _kept_r = [x for x in split_sentences_g(_recv) if not _mfd(x, _part_r) and not (is_question_g(x) and not x.rstrip().endswith("?"))]
                logger.info("✂️ 스몰톡 되물음 시간대·질문형 위반(%s) → 해당 문장 삭제", _part_r)
                _recv = " ".join(_kept_r).strip() or "그러셨군요."
        # (2026-11-12 P11-A1·A4) 라포 받기 금지 꼴 — 리더가 질문한 것처럼('여쭤봐 주신')·말투 언급('편하게 말씀해 주셔서')·해석형. 평서문만 고정 받기로 바꾼다
        from diag_project.services.turn_checks import receive_ban_reason as _rbr_r
        from diag_project.services.intro_messages import smalltalk_flat_receive as _sfr_b
        if any(_rbr_r(x) for x in split_sentences_g(_recv)):
            _tm["recv_ban"] = [r for r in (_rbr_r(x) for x in split_sentences_g(_recv)) if r]
            _kept_b = [x for x in split_sentences_g(_recv) if not _rbr_r(x)]
            _recv = " ".join([_sfr_b(_persona_name_r)] + [x for x in _kept_b if is_question_g(x)]).strip()
        _st_reserve = False
        if _smalltalk and _echoes(_recv, request.content):
            # (2026-11-11 P10-1) 스몰톡은 LLM 1회만 — 되받기가 리더 말을 그대로 옮겼으면 재생성하지 않고 고정 받기 + 예비 되물음
            _tm["echo"] = 2
            _st_reserve = True
        elif _echoes(_recv, request.content):
            _tm["echo"] = 1
            logger.info("🔁 라포 되받기가 리더 발화를 반복: %r → 재생성 1회", _recv[:40])
            try:
                _e_regen = await _timed_regen(why="rapport_echo", 
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
            # (2026-11-11 P10-1) 검사에서 떨어지면 재생성 없이 예비 되물음(코치별 3종 × 시간대). 평가 말투·내부 문구가 섞인 출력도 여기서 통째로 바꾼다.
            from diag_project.services.intro_messages import smalltalk_flat_receive as _sfr_r
            from diag_project.services.output_guard import find_praise as _fp_r, find_state_leak as _fsl_r
            _rq = _smalltalk_reserve()
            if not _st_reserve and (_fp_r(_recv) or _fsl_r(_recv)):
                _st_reserve = True
                _tm["smalltalk_guard"] = "praise_or_state"
            if _st_reserve:
                clean_reply = f"{_sfr_r(_persona_name_r)} {_rq}"
                _tm["smalltalk"] = "reserve"
            elif _consent_in:
                clean_reply = _rq
                _tm["no_q_fix"] = "smalltalk_consent"; _tm["smalltalk"] = "reserve"
            elif not any(is_question_g(x) for x in split_sentences_g(_recv)):
                # 10/22 2턴 "그러셨군요." 단독 출력 차단 — 모든 코치 턴은 질문 하나로 끝난다
                clean_reply = f"{_recv} {_rq}"
                _tm["no_q_fix"] = "smalltalk"; _tm["smalltalk"] = "llm+reserve"
            else:
                clean_reply = _recv
                _tm["smalltalk"] = "llm"
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
        # (2026-11-12 P11b-2) LLM 받기가 안내를 예고하는 문장이면('네, 그러면 오늘 흐름부터 안내드리겠습니다.') 버린다 — 고정 안내의 첫 문장
        #   ('그러면 오늘 진단이 어떻게 진행되는지 간단히 안내드리겠습니다.')과 겹쳤다. 둘 중 고정 안내만 남긴다.
        from diag_project.services.turn_checks import is_intro_announce as _iia_a
        if llm_acknowledgment and _iia_a(llm_acknowledgment):
            _tm["intro_dup"] = 1
            llm_acknowledgment = ""
        anchor_section = build_intro_anchor_section((state.get('coach_persona') or {}).get('name'))   # (P11-A5) 코치 말투별 본문
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
            # (2026-11-14 P12d-1) 다시 쓰지 않는다 — 리더가 하지 않은 말의 따옴표만 뗀다
            _tm["quote"] = 2
            clean_reply = _sqm(clean_reply, _bad_q)
            logger.info("🔒 ALIGN 인용 가드: 리더 정의에 없는 인용 %s → 따옴표 제거", _bad_q)
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
            # (P12d-1) 다시 쓰지 않는다 — 내부 낱말이 든 문장만 지운다(받기가 비면 아래에서 고정 받기로 받는다)
            _tm["align_leak"] = list(_lk_al)
            clean_reply, _n_al = _sls_al(clean_reply, _lk_al)
            _tm["align_leak_stripped"] = _n_al
            logger.info("🛡️ ALIGN 받기 내부 어휘 %s → 문장 삭제 %d", _lk_al, _n_al)
        # (2026-11-05 3단계 소수정 4) ALIGN 되받기도 P3-1 규칙 — 리더 정의의 명사구를 그대로 인용한 평서문. 없으면 재생성 ≤2,
        #   그래도 없으면 본문을 비워 render_align 이 인용 문장(align_receive_quote)으로 조립한다. '네, 잘 들었어요' 류 폴백 없음.
        try:
            from diag_project.services.align_render import leader_definition_body as _ldb_al, receive_sentences as _rs_al
            from diag_project.services.receive_check import check_receive as _chk_al, quote_phrase as _qp_al
            _subs_al = list(state.get("all_subcompetencies") or [])
            _ut_al = _ldb_al(chapter or "", request.content or "")   # 역량 이름('조직관리는 …')은 인용으로 치지 않는다

            def _recv_state(txt: str) -> tuple[bool, bool]:
                _r = " ".join(_rs_al(txt, chapter=chapter or "", sub_names=_subs_al, user_text=_ut_al))
                return _chk_al(_r, _ut_al) if _r else (False, False)
            _has_al, _quoted_al = _recv_state(clean_reply)
            # (2026-11-14 P12d-1) 정의 답을 받는 문장은 LLM 1회 그대로 — 받는 문장이 없거나 리더의 정의 답과 겹치는 낱말이 하나도 없으면
            #   다시 쓰지 않고 고정 받기(말투별 3종, 영역 순서로)로 받는다. 종전: 구절을 그대로 인용하지 않으면 다시 쓰기 최대 2회.
            from diag_project.services.turn_checks import question_overlap as _qov_al
            _recv_txt_al = " ".join(_rs_al(clean_reply, chapter=chapter or "", sub_names=_subs_al, user_text=_ut_al))
            _ov_al = _qov_al(_recv_txt_al, _ut_al) if _recv_txt_al else []
            _tm["align_regen"] = 0
            if not (_has_al and _ov_al):
                _tm["align_receive_miss"] = 1
                clean_reply = ""   # 받기를 비운다 → render_align 이 고정 받기로 받는다
                logger.info("📐 ALIGN 받기에 리더 답의 낱말 없음 → 고정 받기")
        except Exception as _e_al2:   # noqa: BLE001
            logger.warning("ALIGN 되받기 인용 검사 실패(무시): %s", _e_al2)
        if chapter and current_target_sub:
            # (2026-10-28 P0-1) ALIGN 조립은 백엔드 결정론(services/align_render.render_align):
            #   [LLM 공감 되받기 2~3문장] + [고정 정의 1문장] + [목록 · 줄 전부] + [고정 안내] + [고정 다리] + [앵커 1개].
            #   LLM 출력의 질문·목록·다른 챕터 문구·선택 넘기기 문장은 전부 제거. 고정 문장은 페르소나 어미. 챕터 크기와 무관하게 같은 렌더러.
            # (2026-10-21) ANCHOR_RENDER=llm 이면 렌더링 질문으로(판정 불합격·실패는 사전 문장 폴백). dict 모드는 그대로(어미 변환 포함).
            _ar_q, _ar_mode = await _render_anchor_for(current_target_sub)
            _tm["anchor_render"] = _ar_mode
            from diag_project.services.output_guard import strip_frame_lead
            _anchor = strip_frame_lead(_ar_q)
            if _opener_result and _tm.get("opener_align_task"):
                # (호출 순서) 본 호출과 병렬로 만든 여는 문장 — 렌더가 불합격(사전 폴백)이면 종전 경로의 앵커(_anchor)를 그대로 쓴다
                _op_txt_al, _op_mode_al = _opener_result
                if _op_mode_al in ("llm", "llm_regen"):
                    _anchor = _op_txt_al
            else:
                _anchor, _op_mode_al = await _opener_for(current_target_sub, _anchor)   # (P4-4) 사례 1 여는 문장
            _tm["opener"] = _op_mode_al
            # 조립은 모든 후처리(8-i 가드·8-n 입버릇·8-h 느낌표 …)가 끝난 뒤 '마지막'(8-z)에 한다 — 중간 단계의 재생성이
            #   조립 결과를 덮지 못하게. 여기서는 재료만 보관하고, clean_reply 는 LLM 되받기 원문 그대로 가드를 통과시킨다.
            #   (2026-11-04 BEI) 끝은 '먼저 하나를 깊게 들어볼게요.'(align_open) + 사례 1 여는 앵커.
            _align_ctx = dict(
                sub_names=list(state.get("all_subcompetencies") or []),
                persona_name=(state.get("coach_persona") or {}).get("name"),
                anchor=_anchor, user_text=request.content or "",
                variant=([k for k in COMPETENCY_FRAMEWORK if k != "supplementary"].index(chapter) if chapter in COMPETENCY_FRAMEWORK else 0),   # (P4-1) 안내·다리 3종 순환
            )
            # (P12d-1) 받기가 비었을 때(낱말 없음·금지 꼴로 삭제) 쓸 고정 받기 — 영역 순서로 돌린다
            from diag_project.services.intro_messages import align_fixed_receive as _afr_al
            _align_ctx["fixed_receive"] = _afr_al(_align_ctx["persona_name"], _align_ctx["variant"])
            # 다음 턴 decider 가 CHAPTER_OPENING 을 다시 내지 않도록 원장에 표식.
            _st_om = dict(session.self_assessment_data or {})
            _om = dict(_st_om.get("opening_merged") or {})
            _om[chapter] = True
            _st_om["opening_merged"] = _om
            session.self_assessment_data = _st_om
            from sqlalchemy.orm.attributes import flag_modified as _fm_om
            _fm_om(session, "self_assessment_data")
            await db.flush()   # (2026-09-22) 턴 끝 1회 커밋 — 중간 커밋 폐지

    _next_ch = _get_next_chapter(chapter)

    # 8-d. CHAPTER_READY_TO_END 하이브리드 (종결 + 강제 전환):
    #   중간 챕터: LLM 이 wrap-up(요약+공감) + '강제 전환 선언 + 다음 역량 첫
    #   질문'을 생성한다. 사용자에게 계속/휴식을 묻지 않고(선택권 이양 금지),
    #   코치가 주도권을 쥐고 즉시 다음 챕터로 전환한다.
    #   → CHAPTER_CONTINUE_CONFIRMED 와 동일하게 완료·시작 마커를 세운다.
    if instruction_used == "CHAPTER_READY_TO_END":
        # 1-b: 내부 종료 사유는 로그에만 남긴다(리더에게 나가는 문구는 중립).
        logger.info("🏁 챕터 종료 [%s] bei_state=%s bei_turns=%s asked=%s turn_count=%s", chapter, state.get("bei_state"),
                    state.get("bei_turns"), len(state.get("asked_in_chapter") or []), state.get("turn_count"))
        # 5(2026-09-17) 마무리 총평 금지: LLM 문장을 쓰지 않고 고정 문구만.
        from diag_project.services.intro_messages import final_closing_message
        if _next_ch:
            # (2026-10-21) '여기까지 충분히 들었습니다' 대신 들은 것 요약 2문장(LLM, 사실만) + 고정 다리.
            #   질문·칭찬·상태 누설 문장은 걷어내고 두 문장으로 자른다. 남는 게 없으면 중립 문장.
            from diag_project.services.intro_messages import chapter_end_bridge
            from diag_project.services.output_guard import drop_question_sentences as _dqs_e, split_sentences as _ss_e
            from diag_project.services.output_guard import strip_praise as _sp_e, strip_state_leak as _ssl_e
            from diag_project.services.output_guard import _content_chunks as _cc_e, strip_transition_sentences as _sts_e
            _eps_c = state.get("bei_close_episodes") or []
            _n_eps_c = len(_eps_c)
            _n_sum_c = min(3, max(2, _n_eps_c))          # (2026-11-10 P9-9) 요약은 사례와 보완 답을 합쳐 2~3문장
            _need_c = min(_n_eps_c, 2)                   # 재료 가운데 최소 이만큼은 실제로 되짚어야 한다

            def _clean_close(txt: str) -> str:
                """질문·칭찬·상태 누설·전환·예고 문장을 걷어내고 사례 수만큼(최소 2문장) 남긴다."""
                from diag_project.services.output_guard import drop_summary_noise as _dsn_e, drop_unfinished_tail as _dut_e
                t, _ = _dut_e(txt); t, _ = _dsn_e(t); t, _ = _dqs_e(t); t, _ = _sp_e(t); t, _ = _ssl_e(t); t, _ = _sts_e(t)
                t = " ".join(x for x in _ss_e(t) if not re.search(r"(보세요|주세요|볼게요|보겠습니다|주십시오)[.!…]?$|되짚어|여쭙|여쭤|궁금", x))
                if state.get("bei_close_no_case"):
                    # (2026-11-05 2단계 판정 4) SWEEP 마지막 답이 '없음'이면 그 답을 받는 문장·'방향을 바꿔/좁혀' 류를 걷어낸다
                    t = " ".join(x for x in _ss_e(t) if not re.search(r"(없(었|으|다|을|는)|떠오르|좁혀|방향을\s*(조금\s*)?바꿔|다른\s*(방향|쪽|질문)|여쭙|여쭤)", x))
                from diag_project.services.output_guard import strip_case_numbering as _scn_e
                return " ".join([_scn_e(x).strip() for x in _ss_e(t) if _scn_e(x).strip()][:_n_sum_c]).strip()   # (P4-6) '사례 1에서는' 번호 매기기 제거 · (P9-9) 2~3문장

            def _eps_matched(txt: str) -> int:
                """재료(사례 인용)와 2개 이상 겹치는 사례 수 — 사례마다 한 문장이 실제로 그 사례를 되짚는지.
                (P9 p9c) 재료가 2개 이상인데 요약이 한 문장뿐이면 요건(_need_c)에 못 미친 것으로 친다 — 재생성·집중 렌더로 넘긴다."""
                _ct = set(_cc_e(txt))
                _m = sum(1 for e in _eps_c
                         if len({c for k in ("context", "action", "result") for c in _cc_e(e.get(k) or "") if len(c) >= 2} & _ct) >= 2)
                if _n_eps_c >= 2 and len([x for x in _ss_e(txt) if x.strip()]) < 2:
                    _m = min(_m, _need_c - 1)
                return _m

            # (2026-11-05 P4-6) 인용은 재료 — LLM 이 사례 전부(2~3개)를 한 문장씩 되짚는다. 빠진 사례가 있으면 재생성 ≤2, 그래도 어느 사례도
            #   되짚지 못하면 고정 다리만(지어낸 서술 없음). 인용을 나열하던 옛 템플릿(…하셨고, …하셨다고 들었습니다)은 폐지.
            _sum = _clean_close(clean_reply)
            _best_n = _eps_matched(_sum) if (_sum and _eps_c) else 0
            # (2026-11-11 재생성 예산·호출 순서) 본 호출 재생성 루프(≤2회)는 없앴다 — 본 호출은 직전 답에 끌려 요약을 못 썼고(전부 집중 호출로 끝남)
            #   그만큼 3~4초가 먼저 지나갔다. 요약은 재료만 주는 집중 호출 1회, 재료를 다 못 짚으면 1회 다시(이 턴의 재생성 예산).
            _close_mode = "llm"
            if _eps_c and _best_n < _need_c:
                # (P4-6) 본 호출이 직전 답('네, 맞아요')에 끌려 질문을 이어 쓰는 일이 잦다(p4a Michael 3/3) — 이력 없이 재료만 주는 집중 호출로 다시 만든다
                try:
                    from diag_project.services.close_render import render_close_summary as _rcs
                    from diag_project.services.intro_messages import PERSONA_LINES as _PL_c, persona_key as _pk_c
                    _pn_c = (state.get("coach_persona") or {}).get("name")
                    _cs_txt, _cs_n = await _rcs(llm, episodes=_eps_c, persona_name=_pn_c, rounds=(1 if _tm.get("budget_used") else 2),
                                               register_hint="어미 결: " + _PL_c[_pk_c(_pn_c)]["align_definition"].format(cn_eul="'○○'을", defn="…"))
                    _tm["budget_used"] = 1          # 집중 호출이 다시 쓰기까지 썼을 수 있다 — 종료 턴의 뒤 단계는 결정론 수선만
                    if _cs_n > _best_n:
                        _sum, _best_n, _close_mode = _cs_txt, _cs_n, "focused"
                except Exception as _e_cs:   # noqa: BLE001
                    logger.error("종료 요약 집중 렌더 실패: %s", _e_cs)
            if _eps_c and _best_n == 0:
                _sum = ""
            if not _eps_c:
                # (2026-11-06 P7 승인 조건 2) 사례 0 챕터: 다리만 남기지 않고 고정 1문장(페르소나별). LLM 요약은 쓰지 않는다(지어낼 재료가 없다).
                from diag_project.services.intro_messages import close_no_case_line as _cncl
                _sum, _close_mode = _cncl((state.get("coach_persona") or {}).get("name")), "no_case_fixed"
            _tm["close_summary_mode"] = _close_mode if _sum else "bridge_only"
            _tm["close_summary_eps"] = f"{_best_n}/{_n_eps_c}"
            # (2026-11-13 P12-7) 요약도 코치 말투로 — 해요체 코치(Michael 등)의 요약이 합쇼체로 나갔다(말투 교정이 질문 문장만 봤다)
            from diag_project.services.persona_register import apply_register as _areg_cs
            _sum, _n_cs_reg, _ = _areg_cs((state.get("coach_persona") or {}).get("name"), _sum, scope="strict")
            if _n_cs_reg:
                _tm["register_fix"] = int(_tm.get("register_fix") or 0) + _n_cs_reg
            wrap_up = f"{_sum} {chapter_end_bridge(chapter_to_topic(_next_ch), (state.get('coach_persona') or {}).get('name'))}".strip()
        else:
            # (2026-11-10 P9-9) 세션 마지막 답도 받기 1문장 뒤에 종료한다 — 고정 종료 문구만 나가면 마지막 답이 허공에 뜬다
            _pn_fin = (state.get("coach_persona") or {}).get("name")
            _recv_fin = ""
            try:
                from diag_project.services.close_render import render_last_receive as _rlr
                # (2026-11-11 P10-5) LLM 1문장, 리더 답 인용 필수 — 불합격이면 리더 절 인용, 받을 내용이 없으면 받기 없이 종료 문구
                _recv_fin, _fin_mode = await _rlr(llm, user_text=_bei_user_text or request.content, persona_name=_pn_fin,
                                                  rounds=(1 if _tm.get("budget_used") else 2))
                if _fin_mode in ("llm_regen", "quote"):
                    _tm["budget_used"] = 1
                _tm["final_receive_mode"] = _fin_mode
            except Exception as _e_fin:   # noqa: BLE001
                logger.error("마지막 답 받기 렌더 실패: %s", _e_fin)
            _tm["final_receive"] = 1 if _recv_fin else 0
            wrap_up = f"{_recv_fin} {final_closing_message(_pn_fin)}".strip()
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
        _tm["no_regen"] = 1   # (재생성 예산) 종료 턴 본문은 요약(또는 고정 문구) — 뒤 단계가 본 호출 재생성으로 덮지 않는다. 남은 위반은 결정론 수선만
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

    # 8-f. 🦜 앵무새 방어: 직전 AI 멘트와 '동일한' 응답이 또 생성되면 제약을 붙여 재생성 1회. (2026-11-04 BEI) 앵커 폴백 문장은 없다 —
    #   재생성도 같으면 그대로 두고 guard_log parrot=2 로 남긴다(린트가 잡는다).
    if system_override_text is None and clean_reply:
        _last_model_msg = next((m for m in reversed(history_messages)
                                if (m.role == MessageRole.MODEL or m.role == "model")), None)
        if (_last_model_msg and _last_model_msg.content and _last_model_msg.content.strip() == clean_reply.strip()):
            logger.warning("🦜 동일 응답 반복 감지 → 제약 추가 후 LLM 재생성 1회")
            _tm["parrot"] = 1
            _regen: dict = {}
            try:
                _regen = await _timed_regen(why="parrot", 
                    system_prompt=system_prompt, chapter_context=chapter_context,
                    turn_state_text=turn_state_text + (
                        "\n\n🚨 [시스템 — 재생성 지시] 방금 만든 응답이 직전 코치 발화와 완전히 동일합니다. 같은 문장을 다시 쓰지 마세요. "
                        "리더님이 방금 한 말에서 출발해 다른 되받기와 다른 질문 하나로 다시 쓰세요."),
                    compressed_history=compressed_history, user_message=request.content, light_mode=True)
                _regen_reply = _MARKER_RE.sub("", _regen.get("reply") or "").strip()
            except Exception as _e:
                logger.error("🦜 재생성 실패: %s", _e)
                _regen_reply = ""
            if _regen_reply and not _regen.get("error") and _regen_reply != clean_reply.strip():
                clean_reply = _regen_reply
            else:
                _tm["parrot"] = 2
                logger.warning("🦜 재생성도 동일/실패 → 그대로 내보냄(폴백 없음)")

    # 8-g. 최종 안전망: 하이브리드 조립 이후에도 남아있을 수 있는 시스템
    #   마커를 프론트 전달 직전에 한 번 더 완벽 제거.
    clean_reply = _MARKER_RE.sub("", clean_reply).strip()

    # 8-i0. (2026-11-02 p2f) '사건' 치환 — LLM 되받기가 BEI 용어 '사건'을 리더에게 쓴다(p2c 25세션 중 12턴: '이번 사건의 중심으로',
    #   '앞서 말씀하신 세 사건에서는'). 엄격 사전에 '사건'을 수동 복원(GUARD_KEEP)했으므로 가드가 문장을 지우기 전에 리더 말로 바꾼다
    #   ('이번 사건'→'그 일', '세 사건'→'세 가지', 그 외 '사건'→'일'). 재생성 출력은 8-y 에서 같은 치환을 한 번 더 한다.
    if system_override_text is None and not _llm_error and clean_reply and "사건" in clean_reply:
        from diag_project.services.output_guard import rewrite_incident_word as _riw
        clean_reply, _n_riw = _riw(clean_reply)
        if _n_riw:
            _tm["incident_word"] = _n_riw
            logger.info("✏️ 낱말 바꿈 %d곳", _n_riw)

    # 8-i. 통합 출력 가드(2026-09-16 도입 → 2026-11-04 BEI 축소) — LLM 턴만.
    #   위반 감지 → [names_mention·no_question·same_question·bare_ref·leak] 재생성 1회 → 남은 위반은 하드 교정(문장 단위, 질문 보존).
    #   (BEI) off_target·transition·recap 관찰·앵커 폴백은 폐지 — 질문이 끝내 없으면 8-w 턴 형식 검사가 다시 재생성한다(폴백 문장 없음).
    #   후처리 단계 전체 표: docs/postprocess_pipeline.md
    _is_probe = instruction_used in ("EPISODE_PROBE", "NO_CASE_REFRAME", "SWEEP_FOLLOWUP")   # 질문을 LLM 이 쓰는 사례 턴
    _is_open = instruction_used in ("EPISODE_OPEN", "SWEEP_ANCHOR")                        # 질문은 시스템 앵커, LLM 은 되받기+다리
    if system_override_text is None and not _llm_error and clean_reply:
        # (2026-10-16) 재방문 인사 가드는 같은 자리 안에서만. 자리가 바뀐 뒤 첫 턴(재개)에는 "다시 뵙게 되어" 가 정당하므로 제외한다.
        _resumed_sitting = (_sit_n <= 1 and len(history_messages) > 1)
        from diag_project.data.competencies import COMPETENCY_FRAMEWORK as _CF
        _all_names = [v.get("name") for c in _CF.values() for v in (c.get("indicators") or {}).values()]

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
            try:
                from diag_project.services.leak_lexicon import find_leaks as _find_leaks
                lk = [w for w in _find_leaks(txt, _prev_user_texts + [request.content or ""]) if w not in (sl or [])]
                if lk:
                    v["leak"] = lk
            except Exception as _le:   # noqa: BLE001 — 사전 로드 실패가 턴을 막지 않게
                logger.warning("누설 사전 검사 실패(무시): %s", _le)
            if chapter and (_is_probe or _is_open):
                nm = find_sub_names(txt, _all_names)
                if nm:
                    v["names_mention"] = nm
            if _is_probe:
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
        _REGEN_KEYS = {"names_mention", "no_question", "same_question", "bare_ref", "leak", "praise"}   # (2026-11-05 P4-2) 평가 말투는 전면 재생성
        # (2026-10-28 P0-1) ALIGN 은 재생성하지 않는다 — 조립(정의·목록·다리·앵커)을 LLM 새 출력이 덮는다. 남은 위반은 하드 교정만.
        _need_regen = bool(set(_v) & _REGEN_KEYS) and instruction_used != "COMPETENCY_ALIGN"
        if _need_regen and instruction_used in ("DIAGNOSIS_CONFIRM", "COMPETENCY_ASK") and set(_v) & _REGEN_KEYS <= {"praise"}:
            _need_regen = False   # (2026-11-11 P10) 정의 턴은 범위 1문장만 쓴다 — 평가 리드('좋습니다')는 아래 하드 교정이 떼면 충분(재생성 1.5초 절약)
        if _v and not _need_regen:
            logger.info("🛡️ 출력 가드 위반(재생성 생략): %s (instr=%s)", _v, instruction_used)
        if _need_regen:
            logger.info("🛡️ 출력 가드 위반: %s (instr=%s) → 재생성 1회", _v, instruction_used)
            _notes = ["\n\n🚨 [시스템 — 재생성 지시] 방금 만든 응답에 다음 위반이 있습니다. 내용은 유지하되 고쳐 다시 쓰세요."]
            if "praise" in _v:
                _notes.append(f"- 평가적 칭찬 금지: {', '.join(_v['praise'])} 같은 표현을 빼세요. 들은 사실만 말하세요.")
            if "revisit" in _v:
                _notes.append(f"- 첫 세션(같은 자리)입니다. {', '.join(_v['revisit'])} 같은 재방문·재회 인사를 빼세요.")
            if "names_mention" in _v:
                _notes.append("- 하위역량 이름을 말하지 말고, 리더님 답이 어느 역량에 속하는지 설명하지 마세요.")
            if "no_question" in _v:
                _notes.append("- 응답에 질문이 없습니다. 반드시 리더님께 묻는 질문 한 문장으로 끝내세요.")
            if "same_question" in _v:
                _notes.append("- 직전 턴과 같은 질문을 되묻고 있습니다. 리더님이 방금 답한 내용에서 한 걸음 더 들어가는 다른 질문을 하세요.")
            if "bare_ref" in _v:
                _notes.append("- 질문이 가리키는 말로만 대상을 대신합니다. 리더님이 방금 쓴 낱말을 질문에 넣어 무엇을 묻는지 분명히 하세요.")
            if "leak" in _v:
                _notes.append("- 다음 말은 코치가 리더님께 쓰는 말이 아니라 내부 용어입니다: " + ", ".join(str(x) for x in _v["leak"][:6])
                              + ". 그 문장을 빼거나 리더님께 하는 자연스러운 말로 바꾸세요. 진행 상태·방법을 설명하지 말고 대화만 하세요.")
            try:
                _g_regen = await _timed_regen(why="guard", 
                    system_prompt=system_prompt, chapter_context=chapter_context,
                    turn_state_text=turn_state_text + "\n".join(_notes),
                    compressed_history=compressed_history, user_message=request.content, light_mode=True,
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
            if "names_mention" in _v:
                _c2, _n = strip_sub_name_mentions(clean_reply, _all_names)
                if has_question(_c2) or not has_question(clean_reply):
                    clean_reply = _c2
            if "praise" in _v:
                _c2, _n = strip_praise(clean_reply)   # 마지막 질문 문장은 보존하는 함수
                if has_question(_c2) or not has_question(clean_reply):
                    clean_reply = _c2
                # (2026-11-05 P4-3) 칭찬 구절을 뗀 흉터 문장은 8-v 가 삭제한다(교체·재생성 없음) — 되받기가 비면 8-w 가 재생성
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
                from diag_project.services.leak_lexicon import strip_leak_sentences as _sls
                _c2, _n = _sls(clean_reply, list(_v["leak"]))
                if _c2.strip() and (has_question(_c2) or not has_question(clean_reply)):
                    clean_reply = _c2
                    _tm["leak_stripped"] = _n
                    logger.info("🛡️ 내부 어휘 누설 %d문장 제거: %s", _n, _v["leak"])
            if "bare_ref" in _v and _is_probe:
                from diag_project.services.output_guard import bare_demonstrative_questions as _bdq2, followup_from_user as _ffu
                for _bq in _bdq2(clean_reply, request.content):
                    clean_reply = clean_reply.replace(_bq, _ffu(request.content), 1)
                    logger.info("🧹 대명사 단독 질문 교체: %s", _bq[:40])

        # (2026-11-04 BEI) 여는 턴·SWEEP 앵커 턴 조립: LLM 본문에서 질문을 지우고 [되받기+다리 ≤3문장] + 시스템 앵커(사전 문장·페르소나 어미).
        if _is_open and _bei_anchor_text:
            from diag_project.services.output_guard import drop_question_sentences as _dqs_o
            from diag_project.services.output_guard import clean_close_side as _ccs_o
            _body_o, _nq_o = _dqs_o(clean_reply)
            # (2026-11-10 P9-4) 닫는 쪽 = 직전 답 받기 1문장(연속 SWEEP 은 다리 1문장 더). 질문·'여쭙고 싶습니다'·'궁금'·조언·가정은 지운다.
            _max_o = 2 if (instruction_used == "SWEEP_ANCHOR" and _sweep_seq_b >= 2) else 1
            _body_o, _n_cs_o = _ccs_o(_body_o, max_statements=_max_o)
            # (2026-11-11 P10-5) 받기는 직전 답의 내용을 담는다 — 리더 답에 받을 낱말이 없거나('네, 맞아요') 받는 문장에 리더 낱말이 하나도 없으면
            #   그 문장은 받기가 아니다(p10a: "그럼 이 사례를 조금 더 펼쳐 볼게요."). 지우고 여는 문장만 낸다.
            from diag_project.services.receive_check import leader_nouns as _ln_o, receive_has_content as _rhc_o
            _so_all = [x.strip() for x in split_sentences(_body_o) if x.strip()]
            if _so_all and (not _ln_o(_llm_user_text) or not _rhc_o(_so_all[0], _llm_user_text)):
                _n_cs_o += 1
                _tm["receive_dropped"] = 1
                _body_o = " ".join(_so_all[1:])
            if _n_cs_o:
                _tm["close_side_cut"] = _n_cs_o
            if instruction_used == "SWEEP_ANCHOR" and _sweep_seq_b >= 2:
                # (2026-11-05 P4-5) 연속 SWEEP 2개째부터 앵커 앞 다리 1문장 필수 — 없으면 재생성 1회
                from diag_project.services.output_guard import has_sweep_bridge as _hsb
                # (2026-11-13 P12b-1) 없어도 다시 쓰지 않는다 — 있는 문장(직전 답을 받은 1문장)과 질문만 낸다(p12: 다시 쓰기 3턴, 그중 하나는 지시문 낱말을 옮겼다)
                _tm["sweep_bridge"] = 1 if _hsb(_body_o) else 0
                # (2026-11-11 P10-4) 다리 문장(받기 뒤의 평서문)은 코치 어미 강제 — 받는 문장(첫 문장)만 자유
                from diag_project.services.persona_register import apply_register as _areg_o
                _so = [x.strip() for x in split_sentences(_body_o) if x.strip()]
                if len(_so) >= 2:
                    _br_new, _n_br, _ = _areg_o((state.get("coach_persona") or {}).get("name"), _so[-1], scope="strict")
                    if _n_br:
                        _body_o = " ".join(_so[:-1] + [_br_new])
                        _tm["register_fix"] = int(_tm.get("register_fix") or 0) + _n_br
            clean_reply = f"{_body_o} {_bei_anchor_text}".strip()
            _tm["anchor_attached"] = 1
            if _nq_o:
                _tm["open_q_dropped"] = _nq_o
        # 사례 탐침 턴: 시점 문형 결정론 교정 + 되받기 뒤 권유 평서문('…떠올려 주셔도 좋아요') 제거(질문 보존). 질문 수·되받기는 8-w 가 본다.
        if _is_probe:
            from diag_project.services.output_guard import fix_moment_question as _fmq, strip_suggestion_statements as _sss_c
            clean_reply, _n_m = _fmq(clean_reply)
            if _n_m:
                _tm["moment"] = _n_m
            clean_reply, _n_sug = _sss_c(clean_reply)
            if _n_sug:
                _tm["suggestion_cut"] = _n_sug

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
        # (2026-11-04 P3 2차) 고정 문장(전환 다리·응원·관찰)은 입버릇 집계·삭제·재생성 대상이 아니다 — p3r 에서 다리 '다른 쪽이에요'가
        #   2회째부터 입버릇으로 잡혀 전환 턴 전체가 재생성되며 다리·앵커가 사라졋다(Michael 2/3턴, Jessica 1/3턴).
        from diag_project.services.intro_messages import persona_line as _pl_tn
        from diag_project.services.receive_check import lead_cap_for as _lcf_n, splice_receive as _spl_n, _compact as _cpt_n
        _pn_n = (state.get("coach_persona") or {}).get("name")
        _fixed_n = [x for x in ([_tm.get("slot_text")] + list((session.self_assessment_data or {}).get("slot_texts") or [])
                                + split_sentences(_bei_anchor_text or "")) if x]   # (BEI → P10-2) 고정 문장 = 슬롯 문장(렌더본)·시스템 앵커(문장 단위)
        _fixed_n_c = {_cpt_n(x) for x in _fixed_n}

        def _sans_fixed(txt: str) -> str:
            return " ".join(x for x in split_sentences(txt or "") if x.strip() and _cpt_n(x) not in _fixed_n_c)

        def _tail_hits(txt: str) -> tuple[list, list]:
            _t = _sans_fixed(txt)
            _b = _fbt(_t)
            _r = [t for t in _lts(_t) if int(_tc.get(t, 0) or 0) >= 1]
            return _b, _r
        # 앵커·슬롯 턴은 질문부가 시스템 문장 — 재생성 본문으로 통째로 바꾸지 않고 되받기만 교체한다.
        _keep_q_n = bool(_tm.get("anchor_attached") or _tm.get("slot"))

        _b0, _r0 = _tail_hits(clean_reply)
        if _b0 or _r0:
            _tm["tail"] = (_b0 + _r0)[0]
            _third = any(int(_tc.get(t, 0) or 0) >= 2 for t in _r0)
            _fixed = False
            if not _third:
                try:
                    _t_out = await _timed_regen(why="tail", 
                        system_prompt=system_prompt, chapter_context=chapter_context,
                        turn_state_text=turn_state_text + (
                            "\n\n🚨 [시스템 — 재생성 지시] 첫 문장의 마무리 어구 '" + "', '".join(_b0 + _r0)
                            + "' 는 이 세션에서 이미 썼거나 금지된 표현입니다. 첫 문장을 다른 마무리로 다시 쓰세요(질문은 유지). 이 지시문의 단어를 답에 옮기지 마세요."),
                        compressed_history=compressed_history, user_message=_llm_user_text, light_mode=True)
                    _t_txt = _MARKER_RE.sub("", _t_out.get("reply") or "").strip()
                    _b1, _r1 = _tail_hits(_t_txt) if _t_txt else (["(빈 응답)"], [])
                    if _t_txt and not _b1 and not _r1:
                        clean_reply = _spl_n(clean_reply, _t_txt, _lcf_n(_llm_user_text), keep_fixed=_fixed_n) if _keep_q_n else _t_txt
                        _fixed = True
                        logger.info("🗣️ 입버릇 반복 → 재생성으로 해결: %s", _tm["tail"])
                except Exception as _e:
                    logger.error("🗣️ 입버릇 재생성 실패: %s", _e)
            if not _fixed:
                clean_reply, _n_tail = _sls(clean_reply, set(_r0))
                _tm["tail_fix"] = 2
                logger.info("🗣️ 입버릇 반복(%s) → 되받기 문장 %d개 삭제", _tm["tail"], _n_tail)
        if _swh(clean_reply) and any(_swh(_t) for _t in _recent_coach_texts):
            clean_reply, _hon = _slh(clean_reply)
            if _hon:
                _tm["honorific"] = 1
                logger.info("🗣️ '리더님,' 문두 호칭 반복 → 제거")

    # 8-v. (2026-11-05 P4-3) 흉터 문장 삭제 — 가드가 구절을 떼고 남긴 문장(서술어 없음 '…게 인데요'·호칭만 '리더님.'·조사 끝)은 교체하지 않고 지운다.
    #   고정 문장(슬롯·시스템 앵커)은 제외. 되받기가 0이 되면 아래 8-w 가 재생성한다(ALIGN 은 render_align 이 인용 문장으로 받는다).
    if system_override_text is None and not _llm_error and (clean_reply or "").strip():
        from diag_project.services.output_guard import delete_broken_statements as _dbs_v, split_sentences as _ss_v
        _keep_v = [x for x in ([_tm.get("slot_text")] + _ss_v(_bei_anchor_text or "")) if x]
        clean_reply, _n_bk = _dbs_v(clean_reply, keep=_keep_v)
        if _n_bk:
            _tm["broken_cut"] = _n_bk
            logger.info("🩹 흉터 문장 %d개 삭제", _n_bk)

    # (2026-11-12 시뮬 p11b) 구절 인용 받기('…'는 말씀이셨군요.)는 두 꼴을 번갈아 쓴다 — 세션에서 이미 쓴 횟수
    from diag_project.services.receive_check import QUOTE_RECEIVE_SESSION_MAX, quote_receive_count as _qrc_v
    _qr_variant = _qrc_v([m.content or "" for m in history_messages if (m.role == MessageRole.MODEL or m.role == "model")])

    # 8-w0. (2026-11-12 P11-A3·H → P11d-1) 다시 묻기 턴 — 전용 호출이 만든 문장(되묻기: 사과 1문장 + 질문 1개 / 내용 없는 답: 질문 1개)을 그대로 놓는다.
    #   앞 단계(가드)가 손댄 것이 있어도 되돌린다. 직전 질문을 골라내던 검사(딴 질문·말하지 않은 사실 판정)는 삭제했다.
    if _reask_kind and _reask_final and system_override_text is None and not _llm_error:
        clean_reply = _reask_final

    # 8-w00. (2026-11-12 P11-A1·A4·H) 받는 문장 금지 꼴 — 리더가 질문한 것처럼 쓰는 말('여쭤봐 주신')·리더의 말투를 언급하는 말('편하게 말씀해 주셔서')·
    #   해석형 받기('…뜻으로 들리네요', '흥미롭습니다'). 그 문장을 지우고, 받기가 없어지면 아래 8-w 가 재생성 1회 → 구절 인용 받기로 메운다.
    if (system_override_text is None and not _llm_error and chapter and (_is_probe or _is_open) and (clean_reply or "").strip()
            and _align_ctx is None and not _reask_kind and not needs_user_decision):
        from diag_project.services.turn_checks import drop_banned_receives as _dbr_w0
        _keep_w0 = {re.sub(r"\s+", "", x) for x in (split_sentences(_bei_anchor_text or "") + [str(_tm.get("slot_text") or "")]) if x}
        _c_w0, _r_w0 = _dbr_w0(clean_reply, keep=_keep_w0)
        if _r_w0:
            clean_reply = _c_w0
            _tm["recv_ban"] = list(_tm.get("recv_ban") or []) + _r_w0
            logger.info("🚫 받는 문장 금지 꼴 삭제: %s", _r_w0)
            # (2026-11-12 P11c-1) 지운 자리를 메우지 않는다 — 재생성도 구절 인용 대체도 없이 그 문장만 삭제(질문만 나가는 것이 정상)

    # 8-w. (2026-11-04 BEI) 턴 형식 검사 — [되받기 1~3문장(리더 직전 답의 명사구 인용)] + [질문 1개]. 위반 사유를 모아 재생성 최대 2회.
    #   폴백 문장은 없다: 2회 뒤에도 되받기가 없으면 그대로 내보내고 guard_log receive_miss(린트 '되받기 없는 턴' 0 기준),
    #   질문이 2개면 마지막 질문만 남긴다(결정 1). 질문부가 시스템 문장(앵커·슬롯)인 턴은 되받기만 교체한다(splice_receive).
    from diag_project.services.receive_check import RECEIVE_REQUIRED_INSTRUCTIONS as _RECV_INSTR
    if (system_override_text is None and not _llm_error and (clean_reply or "").strip() and not needs_user_decision
            and chapter and instruction_used in _RECV_INSTR and _align_ctx is None and not _reask_kind):
        from diag_project.services.output_guard import count_question_markers as _cq_w, keep_last_question as _klq_w   # 복합 질문 절도 센다
        from diag_project.services.output_guard import find_praise as _fp_w, is_leading_choice_question as _ilc_w
        from diag_project.services.receive_check import (
            _compact as _cpt_w, check_receive as _chk_r, lead_cap_for as _lcf_w, quote_phrase as _qp_r, splice_receive as _spl_r,
        )
        _q_expected = _is_probe                       # 여는·SWEEP 앵커 턴은 시스템 질문이 이미 붙어 있다
        _fixed_w = [x for x in ([_tm.get("slot_text")] + split_sentences(_bei_anchor_text or "")) if x]   # (P4-4) 여는 문장은 2~3문장
        _fixed_wc = {_cpt_w(x) for x in _fixed_w}

        # (2026-11-06 P7) 리더 답이 '없어요·글쎄요' 류(사례 아님, incident=false)면 인용할 명사구가 없다 — 되받기만 요구하고 인용은 면제
        _quote_required = not (_bei.is_no_case_text(_llm_user_text) or _tm.get("incident") is False)
        from diag_project.services.receive_check import leader_nouns as _ln_w
        _recv_optional = _is_open and not _ln_w(_llm_user_text)   # (P10-5) 받을 낱말이 없는 답('네, 맞아요') 뒤의 여는 턴은 받기 없이 연다

        def _format_issues(txt: str) -> list[str]:
            issues: list[str] = []
            _has_r, _quoted_r = _chk_r(txt, _llm_user_text)
            # (2026-11-12 P11c-1) 탐침 턴(_q_expected)은 질문 앞 평서문이 없어도 된다 — no_receive·no_quote 검사는 닫고 넘어가는 턴(여는·보완 앵커)에만
            #   닫고 넘어가는 턴이라도 이 턴에 금지 꼴이라 지운 문장의 자리는 메우지 않는다(재생성·대체 없이 삭제만)
            if _recv_optional or _q_expected or _tm.get("recv_ban"):
                pass
            elif not _has_r:
                issues.append("no_receive")
            elif not _quoted_r and _quote_required:
                issues.append("no_quote")
            _n_st = sum(1 for x in split_sentences(txt) if x.strip() and not is_question_sentence(x) and _cpt_w(x) not in _fixed_wc)
            if _n_st > (1 if _q_expected else 3):   # (2026-11-12 P11-H) 탐침 턴의 받는 문장은 1문장 — 여는 턴(받기+다리)은 8-w2 가 맞춘다
                issues.append("long_receive")
            # (2026-11-12 P11c-2) 질문 수 = 질문 '문장' 수 — 한 문장짜리 질문은 두 질문 처리 대상이 아니다(절을 자르지 않는다)
            _nq = sum(1 for x in split_sentences(txt) if x.strip() and is_question_sentence(x) and _cpt_w(x) not in _fixed_wc)
            if _q_expected and _nq == 0:
                issues.append("no_question")
            if _nq > 1:
                issues.append("two_questions")
            # (2026-11-12 P11d-2) 선택지 질문 재생성은 삭제 — 다시 써도 남았다(p11c). 프롬프트 규칙만 둔다.
            if _fp_w(" ".join(x for x in split_sentences(txt) if _cpt_w(x) not in _fixed_wc)):
                issues.append("praise")           # (P4-2) 재생성 출력에 새로 들어온 평가 말투('인상적이었어요')도 형식 위반 — 8-i 뒤 재생성은 8-i 를 다시 안 지난다
            return issues

        # (2026-11-11 지연 단축 b) 두 질문은 재생성하지 않는다 — 바로 마지막 질문만 남긴다(한 문장 안의 복합 질문은 뒤 질문만). 재생성은 2회를 돌고도
        #   절반이 못 고쳤고(p10b: 미해결 3턴) 턴마다 3초 안팎이 들었다. 남긴 질문에 대상이 없으면 아래 8-w3(P9-5)이 그대로 보정한다.
        #   질문을 LLM 이 쓰는 턴(_q_expected)에만 — 여는 턴의 질문은 시스템 앵커라 8-w2 가 닫는 쪽을 정리한다.
        def _trim_two(txt: str) -> tuple[str, int]:
            from diag_project.services.output_guard import keep_main_question as _kmq_t
            from diag_project.services.output_guard import revive_question_receive as _rqr_t
            txt, _n_rv_t = _rqr_t(txt, _llm_user_text)   # (재생성 예산) 질문 꼴 받기("…뜻이었을까요?")는 지우지 않고 평서 꼴("…뜻이었군요.")로 살린다
            if _n_rv_t:
                _tm["recv_revived"] = int(_tm.get("recv_revived") or 0) + _n_rv_t
            # (2026-11-12 P11-C 시뮬 p11a) 열린 질문 + 고르게 하는 질문이면 열린 질문을 남긴다 — 종전에는 뒤 질문의 끝 절만 남아 주어 없는 조각이 됐다
            from diag_project.services.turn_checks import prefer_open_question as _poq_t
            txt, _n_po_t = _poq_t(txt)
            if _n_po_t:
                _tm["open_q_kept"] = int(_tm.get("open_q_kept") or 0) + _n_po_t
                return txt, _n_po_t
            _t, _n_qo_t = _kmq_t(txt)                 # (lb1) 질문 뒤 도움말을 먼저 걷어내고, 질문 문장이 둘 이상이면 마지막 하나만(문장 단위 — 한 문장 안은 자르지 않는다)
            return _t, _n_qo_t

        def _trim_recv(txt: str) -> tuple[str, int]:
            """(P11-H) 탐침 턴의 받는 문장을 1문장으로 — 재생성 없이, 리더가 쓴 낱말이 든 첫 문장을 남긴다."""
            from diag_project.services.receive_check import receive_statements as _rst_t
            _sts_t = [x for x in _rst_t(txt) if _cpt_w(x) not in _fixed_wc]
            if len(_sts_t) <= 1:
                return txt, 0
            _best_t = next((x for x in _sts_t if _chk_r(x, _llm_user_text)[1]), _sts_t[0])
            return _spl_r(txt, _best_t, 1, keep_fixed=_fixed_w), len(_sts_t) - 1

        def _issues_for_regen(txt: str) -> list[str]:
            # 두 질문은 재생성 사유가 아니다 — 탐침 턴은 위에서 자르고, 여는 턴은 8-w2 가 LLM 이 덧쓴 질문을 걷어낸다(P11c-2)
            return [x for x in _format_issues(txt) if x != "two_questions"]

        _iss = _format_issues(clean_reply)
        if _q_expected and "two_questions" in _iss:
            clean_reply, _n_tq = _trim_two(clean_reply)
            _tm["one_q"] = _n_tq
            _tm["two_q_trim"] = 1
            logger.info("✂️ 두 질문 → 재생성 없이 마지막 질문만 남김(%d개 삭제)", _n_tq)
            _iss = _issues_for_regen(clean_reply)
        elif "two_questions" in _iss:
            _iss = [x for x in _iss if x != "two_questions"]      # 여는 턴 — 8-w2 가 맡는다
        if _q_expected and "long_receive" in _iss:
            clean_reply, _n_tr = _trim_recv(clean_reply)
            if _n_tr:
                _tm["recv_trim"] = _n_tr
            _iss = _issues_for_regen(clean_reply)
        _rounds = 0
        _ph = _qp_r(_llm_user_text)
        _only_long_w = bool(_iss) and set(_iss) == {"long_receive"}     # (P12b-1) 긴 받기만 남았으면 다시 쓰지 않는다 — 아래 수선이 넘친 문장을 지운다
        while _iss and _rounds < 1 and not (_tm.get("budget_used") or _tm.get("no_regen") or _only_long_w):   # (재생성 예산) 턴당 1회 — 이미 썼으면 바로 결정론 수선으로
            _rounds += 1
            _notes_w = ["\n\n🚨 [시스템 — 재생성 지시] 방금 응답의 형식이 어긋났습니다. 질문 1개로 끝나게 다시 쓰세요(질문 앞 평서문은 1문장까지). 이 지시문의 단어를 답에 옮기지 마세요."]
            if "no_receive" in _iss or "no_quote" in _iss:
                _notes_w.append("- 첫 문장은 리더님이 방금 쓴 표현" + (f"('{_ph}' 같은 말)" if _ph else "") + "을 그대로 하나 넣어 들은 사실을 그대로 말하는 평서문으로 쓰세요(평가·칭찬·짐작 없이).")
            if "long_receive" in _iss:
                _notes_w.append("- 질문 앞 평서문이 길어요. 1문장, 리더님이 쓴 핵심 낱말 한두 개만 넣으세요.")
            if "no_question" in _iss:
                _notes_w.append("- 질문이 없습니다. 마지막은 리더님께 묻는 질문 한 문장이어야 합니다.")
            if "two_questions" in _iss:
                _notes_w.append("- 질문이 두 개 이상입니다. 질문은 하나만 남기세요.")
            if "praise" in _iss:
                _notes_w.append("- 평가·칭찬 표현이 있습니다. 질문 앞 평서문은 리더님이 한 일의 사실만 말하세요.")
            try:
                _r_out = await _timed_regen(why=("format:" + "+".join(_iss)), 
                    system_prompt=system_prompt, chapter_context=chapter_context, turn_state_text=turn_state_text + "\n".join(_notes_w),
                    compressed_history=compressed_history, user_message=_llm_user_text, light_mode=True)
                _r_txt = _MARKER_RE.sub("", _r_out.get("reply") or "").strip()
            except Exception as _e_r:
                logger.error("턴 형식 재생성 실패: %s", _e_r)
                _r_txt = ""
            if not _r_txt:
                continue
            # 질문부가 시스템 문장인 턴(앵커·슬롯)은 되받기만 바꾼다. LLM 질문 턴은 재생성 본문 전체를 후보로.
            _cand = _spl_r(clean_reply, _r_txt, 3, keep_fixed=_fixed_w) if (_fixed_w or not _q_expected) else _r_txt
            _n_tq2 = 0
            if _q_expected and "two_questions" in _format_issues(_cand):
                _cand, _n_tq2 = _trim_two(_cand)          # (b) 다른 사유로 재생성한 본문이 두 질문이어도 다시 돌리지 않고 자른다
            if _q_expected:
                _cand, _ = _trim_recv(_cand)              # (P11-H) 재생성 본문의 받기도 1문장으로
            _iss2 = _issues_for_regen(_cand)
            if len(_iss2) < len(_iss):
                clean_reply, _iss = _cand, _iss2
                if _n_tq2:
                    _tm["one_q"] = int(_tm.get("one_q") or 0) + _n_tq2
                    _tm["two_q_trim"] = 1
        _tm["format_regen"] = _rounds
        if _iss:
            # (2026-11-11 재생성 예산) 재생성 뒤에도 남은 위반은 결정론 수선 — 긴 받기는 3문장으로 자르고, 질문이 없으면 리더 말을 받아 한 걸음 더 묻는 문장을 붙인다.
            #   받기 없음·미인용은 아래에서 구절 인용 받기로, 두 질문은 위에서 이미 잘랐다. 수선하지 못한 사유(유도형 질문 등)만 format_miss 로 남긴다.
            _fixed_iss: list[str] = []
            if "long_receive" in _iss:
                from diag_project.services.receive_check import receive_statements as _rst_w
                _keep3 = [x for x in _rst_w(clean_reply) if _cpt_w(x) not in _fixed_wc][:(1 if _q_expected else 3)]
                if _keep3:
                    clean_reply = _spl_r(clean_reply, " ".join(_keep3), 3, keep_fixed=_fixed_w)
                    _fixed_iss.append("long_receive")
            if "no_question" in _iss and _q_expected:
                from diag_project.services.output_guard import followup_from_user as _ffu_w
                clean_reply = f"{clean_reply.rstrip()} {_ffu_w(_llm_user_text)}".strip()
                _fixed_iss.append("no_question")
            if _fixed_iss:
                _tm["format_repaired"] = _fixed_iss
                _iss = [x for x in _iss if x not in _fixed_iss]
        if _iss:
            _tm["format_miss"] = list(_iss)
            if "no_receive" in _iss or "no_quote" in _iss:
                # (2026-11-11 P10-5) 받기는 직전 답의 내용을 담는다 — 2회 뒤에도 내용 없는 받기('흥미로운 지점이에요' 류)면 리더가 한 말의 마지막 절을
                #   그대로 받는 문장으로 바꾼다. 받을 절이 없으면 그대로 두고 receive_miss 로 남긴다.
                from diag_project.services.receive_check import quote_receive as _qrcv_w
                # (2026-11-12 P11c-1) 여기는 닫고 넘어가는 턴만 온다(탐침 턴은 받는 문장 검사가 없다). 구절 인용 받기는 세션 2회까지 — 넘으면 받는 문장 없이 내보낸다
                _qr_w = _qrcv_w(_llm_user_text, _qr_variant) if (_quote_required and _qr_variant < QUOTE_RECEIVE_SESSION_MAX) else ""
                if _qr_w:
                    clean_reply = _spl_r(clean_reply, _qr_w, 1, keep_fixed=_fixed_w)
                    _tm["receive_fallback"] = "quote"
                    _iss = [x for x in _iss if x not in ("no_receive", "no_quote")]
                    _tm["format_miss"] = list(_iss) or None
                else:
                    _tm["receive_miss"] = 1
                _tm["receive_phrase"] = _ph
            logger.info("📐 턴 형식 미해결: %s", _iss)

    # 8-w2. (2026-11-10 P9-4) 여는 턴: 8-w 재생성이 들여온 질문·예고·조언·가정 문장을 다시 걷어내고 받기 문장 수를 맞춘다. 받기가 하나도 없으면
    #   (P10-5) 리더가 한 말의 마지막 절을 그대로 받는다(quote_receive) — 어느 답에나 붙는 고정 받기 문구는 쓰지 않는다. 받을 절도 없으면 여는 문장만.
    if (_is_open and _bei_anchor_text and system_override_text is None and not _llm_error and not needs_user_decision
            and (clean_reply or "").strip() and _align_ctx is None):
        from diag_project.services.output_guard import clean_close_side as _ccs_w2
        from diag_project.services.receive_check import quote_receive as _qrcv_w2
        _fixed_w2 = [x for x in split_sentences(_bei_anchor_text or "") if x.strip()]
        from diag_project.services.receive_check import leader_nouns as _ln_w2
        _recv_optional_w2 = not _ln_w2(_llm_user_text)        # 받을 낱말이 없는 답 — 인용 폴백도 만들 수 없다
        _max_w2 = 2 if (instruction_used == "SWEEP_ANCHOR" and _sweep_seq_b >= 2) else 1
        _c_w2, _n_w2 = _ccs_w2(clean_reply, max_statements=_max_w2, keep=_fixed_w2)
        _fx_c = {re.sub(r"\s+", "", x) for x in _fixed_w2}
        if not [x for x in split_sentences(_c_w2) if x.strip() and re.sub(r"\s+", "", x) not in _fx_c]:
            _qr_w2 = "" if (_recv_optional_w2 or _qr_variant >= QUOTE_RECEIVE_SESSION_MAX) else _qrcv_w2(_llm_user_text, _qr_variant)
            _c_w2 = f"{_qr_w2} {_bei_anchor_text}".strip()
            _tm["close_side_tail"] = 1 if _qr_w2 else 0
            if _qr_w2:
                _tm["receive_fallback"] = "quote"
            elif not _recv_optional_w2:
                _tm["receive_miss"] = 1
        if _n_w2:
            _tm["close_side_cut"] = int(_tm.get("close_side_cut") or 0) + _n_w2
        # (2026-11-12 시뮬 p11b) 여는 턴은 반드시 [받기] + [여는 문장]이다 — 여는 질문이 남아 있지 않으면 받는 문장만 추려 여는 문장을 다시 붙인다
        #   (p11b 조직관리 둘째 사례: 받는 문장만 나가고 질문이 없었다).
        _q_op_w2 = [x.strip() for x in _fixed_w2 if is_question_sentence(x)]
        if _q_op_w2 and re.sub(r"\s+", "", _q_op_w2[-1]) not in re.sub(r"\s+", "", _c_w2):
            _st_w2 = [x.strip() for x in split_sentences(_c_w2) if x.strip() and not is_question_sentence(x) and re.sub(r"\s+", "", x) not in _fx_c][:_max_w2]
            _c_w2 = " ".join(_st_w2 + [_bei_anchor_text]).strip()
            _tm["opener_restored"] = 1
            logger.info("🧷 여는 질문 유실 → [받기] + 여는 문장으로 다시 조립")
        clean_reply = _c_w2

    # 8-w3. (2026-11-10 P9-5) 질문이 하나 남았는데 주어·대상이 없으면("달라진 부분이 있었는지 궁금합니다") 재생성 1회, 그래도 없으면
    #   리더 답의 핵심 명사구를 질문 앞에 붙여 조립한다. 사례 탐침 턴(질문을 LLM 이 쓰는 턴)만.
    if (_is_probe and system_override_text is None and not _llm_error and not needs_user_decision and chapter
            and (clean_reply or "").strip() and _align_ctx is None and not _reask_kind):   # (시뮬 p11b) 다시 묻기 턴은 8-w0 가 조립한 그대로 — 재생성 본문이 사과·설명을 덧붙였다
        from diag_project.services.output_guard import attach_referent as _ar_w3, question_lacks_referent as _qlr_w3
        _sents_w3 = [x for x in split_sentences(clean_reply) if x.strip()]
        _qs_w3 = [x for x in _sents_w3 if is_question_sentence(x)]
        _ctx_w3 = [_llm_user_text or ""]
        # 질문 하나만 남긴 턴(앞 질문을 지움)이거나 질문 앞에 받는 문장이 없는 턴에서만 본다 — 받는 문장이 대상을 말한 짧은 후속 질문은 그대로 둔다
        from diag_project.services.output_guard import _PERSON_RE as _per_w3, _REACTION_RE as _rea_w3
        _trimmed_w3 = bool(_tm.get("one_q")) or not [x for x in _sents_w3 if not is_question_sentence(x)]
        #   (승인 조건 3) 누구의 반응·태도·표정·변화인지 없는 질문은 언제나 본다 — 같은 턴의 받는 문장이 사람을 말했으면 대상이 있는 것으로 친다
        _react_w3 = bool(_qs_w3) and bool(_rea_w3.search(_qs_w3[-1])) and not _per_w3.search(" ".join(_sents_w3))
        # (2026-11-11 P10-2) 탐침 질문 최소 길이 — 대상·장면 없이 15자 이하인 질문("그때 어떤 이야기가 오갔나요?")은 재생성 없이 직전 답의 대상을 붙여 다시 쓴다
        from diag_project.services.output_guard import is_short_bare_question as _isbq_w3
        _short_w3 = len(_qs_w3) == 1 and _isbq_w3(_qs_w3[0], _ctx_w3)
        if _short_w3:
            _new_q3s = _ar_w3(_qs_w3[0], _llm_user_text)
            if _new_q3s != _qs_w3[0]:
                clean_reply = clean_reply.replace(_qs_w3[0], _new_q3s, 1)
                _tm["no_referent"] = "attached_short"
                logger.info("🎯 짧은 질문에 대상 붙임: %r → %r", _qs_w3[0][:40], _new_q3s[:60])
        elif len(_qs_w3) == 1 and (_trimmed_w3 or _react_w3) and _qlr_w3(_qs_w3[0], _ctx_w3) and not (not _trimmed_w3 and not _react_w3):
            # (2026-11-12 P11c) 재생성하지 않는다 — 직전 답의 대상(사람·일)을 질문 앞에 붙여 바로 고친다. 질문만 나가는 턴이 정상이 되면서
            #   이 검사가 걸리는 턴이 늘 수 있어(질문 앞 평서문이 없는 턴을 본다) 재생성 경로를 없앴다.
            _tm["no_referent"] = 1
            _new_q3 = _ar_w3(_qs_w3[0], _llm_user_text)
            if _new_q3 != _qs_w3[0]:
                clean_reply = clean_reply.replace(_qs_w3[0], _new_q3, 1)
                _tm["no_referent"] = "attached"
            logger.info("🎯 대상 없는 질문 교정(%s): %r", _tm.get("no_referent"), _qs_w3[0][:50])

    # 8-w4. (2026-11-12 P11-C) 질문 완결성 — 접속·조건어로 시작('있었다면 누가 …') · 무엇을 묻는지 없는 조각('…태도였는지 궁금합니다') ·
    #   두 질문('…셨는지, 혹시 … 언제였습니까?') · 가리키는 말의 대상이 직전 답에 없음('그 변화', '그 과정', '그때').
    #   순서: 결정론 수선(머리말 떼기·뒤 질문만 남기기) → 남으면 재생성 1회(턴 예산이 남았을 때만) → 그래도 남으면 그 슬롯의 기본 질문으로 바꾼다.
    #   다시 묻기 턴(_reask_kind)은 직전 답이 '네'·'뭔소리야' 라 대상 대조를 하지 않는다.
    #   (시뮬 p11b) 사례 없음 뒤의 재질문 턴(NO_CASE_REFRAME)은 보지 않는다 — 직전 답이 '없다'라 가리킬 말이 없는 것이 정상이고, 잘 쓴 재질문이 기본 질문
    #   ('언제 누구와 있었던 일인지')으로 바뀌었다. 가리키는 말의 대상은 직전 답만이 아니라 이 사례에서 리더가 한 말 전체에서 찾는다(재생성·기본 질문 줄임).
    if (_is_probe and system_override_text is None and not _llm_error and not needs_user_decision and chapter
            and (clean_reply or "").strip() and _align_ctx is None and not _reask_kind and instruction_used != "NO_CASE_REFRAME"):
        from diag_project.services.intro_messages import line_register as _lreg_c
        from diag_project.services.turn_checks import default_slot_question as _dsq_c, question_issues as _qi_c, strip_question_start as _sqs_c

        def _last_q_c(txt: str) -> str:
            _qs = [x.strip() for x in split_sentences(txt or "") if x.strip() and is_question_sentence(x)]
            return _qs[-1] if _qs else ""
        _q_c = _last_q_c(clean_reply)
        _formal_c = _lreg_c((state.get('coach_persona') or {}).get('name')) == "formal"
        _slot_now_c = _bei.ask_slot(_bei_ep) if _bei_ep else "action"
        _fixed_c = {re.sub(r"\s+", "", x) for x in ([str(_tm.get("slot_text") or "")] + split_sentences(_bei_anchor_text or "")) if x}
        # (2026-11-12 P11c-2·5) 한 문장 안 두 질문 자르기(P11b-6)와 꼬리 규칙(자른 뒤 남은 질문을 기본 질문으로)은 삭제 — 한 문장짜리 질문은 그대로 둔다
        def _qi2_c(q: str) -> list[str]:
            return [x for x in _qi_c(q) if x != "two_questions"]
        _iss_c = _qi2_c(_q_c) if (_q_c and re.sub(r"\s+", "", _q_c) not in _fixed_c) else []
        if _iss_c:
            _tm["q_issues"] = list(_iss_c)
            _new_q_c = _q_c
            if "dangling_start" in _iss_c:
                _new_q_c = _sqs_c(_new_q_c)
            if _new_q_c and _new_q_c != _q_c:
                clean_reply = clean_reply.replace(_q_c, _new_q_c, 1)
                _tm["q_complete"] = "repaired"
            _left_c = _qi2_c(_new_q_c)
            if _left_c:
                _done_c = False
                if not (_tm.get("budget_used") or _tm.get("no_regen")):
                    try:
                        _r_c = await _timed_regen(why="q_complete", 
                            system_prompt=system_prompt, chapter_context=chapter_context,
                            turn_state_text=turn_state_text + (
                                "\n\n🚨 [시스템 — 재생성 지시] 방금 질문이 혼자서는 뜻이 서지 않습니다. 질문 1개로 끝나게 다시 쓰되, 질문은 "
                                "접속어나 조건절로 시작하지 않고, 누구의 무엇을 묻는지가 문장 안에 낱말로 있어야 합니다. '그 변화'·'그 과정'·'그때' 처럼 "
                                "가리키기만 하는 말 대신 리더님이 방금 쓴 낱말을 넣으세요. 질문은 하나만. 이 지시문의 단어를 답에 옮기지 마세요."),
                            compressed_history=compressed_history, user_message=_llm_user_text, light_mode=True)
                        _t_c = _MARKER_RE.sub("", _r_c.get("reply") or "").strip()
                        _q2_c = _last_q_c(_t_c)
                        if _t_c and _q2_c and not _qi2_c(_q2_c):
                            clean_reply = clean_reply.replace(_new_q_c, _q2_c, 1)   # 받는 문장은 그대로 두고 질문만 바꾼다
                            _done_c = True
                            _tm["q_complete"] = "regen"
                    except Exception as _e_c:   # noqa: BLE001
                        logger.error("질문 완결성 재생성 실패: %s", _e_c)
                if not _done_c:
                    _slot_c = _bei.ask_slot(_bei_ep) if _bei_ep else "action"
                    _topic_c = (((_bei_ep or {}).get("slots") or {}).get("context") or {}).get("quote") or ""      # (P11e-6) 머리 낱말은 사례의 상황 인용에서만 — 없으면 머리 없이
                    _dq_c = _dsq_c(_slot_c, formal=(_lreg_c((state.get('coach_persona') or {}).get('name')) == "formal"), topic_text=_topic_c)
                    clean_reply = clean_reply.replace(_new_q_c, _dq_c, 1)
                    _tm["q_complete"] = f"default:{_slot_c}"
            logger.info("❓ 질문 완결성(%s) → %s: %r", _iss_c, _tm.get("q_complete"), _q_c[:60])

    # 8-w4b. (2026-11-13 P12-4) 질문 끝맺음 — 청하는 꼴의 같은 끝맺음('떠올려 주실 수 있을까요')이 이번 영역에서 이미 3회면(이번이 4회째) 다시 쓰기 1회
    #   (이 턴의 예산이 남았을 때만). 다시 쓴 질문의 끝맺음이 다르면 질문만 바꾸고, 아니면 그대로 내보낸다(표로 바꾸지 않는다).
    #   (P12b-1) 질문과 리더 답이 겹치는 낱말을 보던 검사와 그 다시 쓰기는 삭제했다 — p12: 6턴이 걸렸고 2건은 오탐('두 분'↔'두 강사', '다시 한다면' 질문),
    #   다시 쓴 질문이 더 나쁜 경우도 있었다. 질문 안에 리더가 쓴 낱말을 넣으라는 지시문은 그대로 둔다.
    if (instruction_used in ("EPISODE_PROBE", "SWEEP_FOLLOWUP") and system_override_text is None and not _llm_error and not needs_user_decision and chapter
            and (clean_reply or "").strip() and _align_ctx is None and not _reask_kind and not str(_tm.get("q_complete") or "").startswith("default")):
        from diag_project.services.turn_checks import QUESTION_ENDING_MAX as _qem_b, ending_label as _el_w, request_ending_key as _rek_b
        _qs_b4 = [x.strip() for x in split_sentences(clean_reply) if x.strip() and is_question_sentence(x)]
        _fixed_b4 = {re.sub(r"\s+", "", x) for x in ([str(_tm.get("slot_text") or "")] + split_sentences(_bei_anchor_text or "")) if x}
        if _qs_b4 and re.sub(r"\s+", "", _qs_b4[-1]) not in _fixed_b4:
            _q_b4 = _qs_b4[-1]
            _key_b4 = _rek_b(_q_b4)
            _end_n_b4 = sum(1 for x in _chapter_questions() if _key_b4 and _rek_b(x) == _key_b4)
            if _key_b4 and _end_n_b4 >= _qem_b:
                _tm["q_stand"] = "ending"
                if not (_tm.get("budget_used") or _tm.get("no_regen")):
                    try:
                        _r_b4 = await _timed_regen(why="q_stand:ending",
                            system_prompt=system_prompt, chapter_context=chapter_context,
                            turn_state_text=turn_state_text + (
                                f"\n\n🚨 [시스템 — 재생성 지시] 방금 질문의 끝맺음('{_el_w(_key_b4)}')은 이번 영역에서 이미 여러 번 썼습니다. "
                                "묻는 것은 그대로 두고 다른 끝맺음으로 끝나는 질문 1개만 씁니다. 이 지시문의 단어를 답에 옮기지 마세요."),
                            compressed_history=compressed_history, user_message=_llm_user_text, light_mode=True)
                        _t_b4 = _MARKER_RE.sub("", _r_b4.get("reply") or "").strip()
                        _q2s_b4 = [x.strip() for x in split_sentences(_t_b4) if x.strip() and is_question_sentence(x)]
                        _q2_b4 = _q2s_b4[-1] if _q2s_b4 else ""
                        if _q2_b4 and _rek_b(_q2_b4) != _key_b4:
                            clean_reply = clean_reply.replace(_q_b4, _q2_b4, 1)      # 질문 앞 평서문은 그대로 두고 질문만 바꾼다
                            _tm["q_stand"] += "→regen"
                        else:
                            _tm["q_stand"] += "→left"
                    except Exception as _e_b4:   # noqa: BLE001
                        logger.error("질문 다시 쓰기 실패(q_stand): %s", _e_b4)
                else:
                    _tm["q_stand"] += "→no_budget"
                logger.info("🧍 질문 끝맺음 검사(%s): %r", _tm.get("q_stand"), _q_b4[:60])

    # 8-w5. (2026-11-12 P11b-5 → P11c-1) 질문 앞 평서문 — ① '리더님께서' 로 시작하면 세션 2회까지, 주어가 리더가 아닌 문장에 붙었으면 그 머리를 뗀다.
    #   ② 탐침 턴: 답 전체를 되풀이한 문장(리더 답 어절의 60% 이상 + 내용 어절 10개 이상)과 세션 3회째부터의 구절 인용 꼴('…'는 말씀이셨군요)은
    #   그 문장만 삭제한다(재생성·대체 없음 — 질문만 나간다). 닫고 넘어가는 턴(여는·보완 앵커)의 문장은 그대로 둔다.
    if (system_override_text is None and not _llm_error and chapter and (_is_probe or _is_open) and (clean_reply or "").strip()
            and _align_ctx is None and not _reask_kind and not needs_user_decision):
        from diag_project.services.receive_check import is_quote_receive as _iqr_5
        from diag_project.services.turn_checks import (
            LEADER_PREFIX_SESSION_MAX as _lp_max, RECEIVE_MAX_EOJEOL, RECEIVE_REPEAT_MAX, RECEIVE_REPEAT_MIN_CHUNKS, leader_prefix_wrong_subject as _lpws_5, receive_overlap as _rov_5,
            starts_with_leader_prefix as _swlp_5, strip_leader_prefix as _slp_5,
        )
        _fx_5 = {re.sub(r"\s+", "", x) for x in (split_sentences(_bei_anchor_text or "") + [str(_tm.get("slot_text") or "")]) if x}
        _recv_5 = next((x.strip() for x in split_sentences(clean_reply) if x.strip() and not is_question_sentence(x) and re.sub(r"\s+", "", x) not in _fx_5), "")
        if _recv_5:
            _ov_5 = _rov_5(_recv_5, _llm_user_text)
            _drop_5 = ""
            if _is_probe and _ov_5[1] >= RECEIVE_REPEAT_MAX and _ov_5[2] >= RECEIVE_REPEAT_MIN_CHUNKS:
                _drop_5 = "repeat"
            elif _is_probe and _iqr_5(_recv_5) and _qr_variant >= QUOTE_RECEIVE_SESSION_MAX:
                _drop_5 = "quote_cap"
            elif (_is_probe or str(_tm.get("closed") or "").endswith(":repeat")) and len(_recv_5.split()) > RECEIVE_MAX_EOJEOL:      # (P12d-4) repeat 로 닫는 턴은 '사례 닫는 턴' 예외에서 뺀다
                _drop_5 = "long"                 # (2026-11-12 P11e-5) 12어절을 넘는 문장은 삭제(재생성 없음) — 되풀이 비율 60% 아래로 통과하던 긴 문장
            from diag_project.services.slot_render import has_leader_first_person as _hlfp_5
            if _hlfp_5(re.sub(r"['‘“\"][^'’”\"\n]{0,80}['’”\"]", "", _recv_5)):
                _drop_5 = "first_person"         # (P11e-5) 코치 문장에 리더의 1인칭('저 혼자', '제가', '내가') — 따옴표 안의 인용은 보지 않는다
            if _drop_5 and any(is_question_sentence(x) for x in split_sentences(clean_reply)):
                clean_reply = re.sub(r"[ \t]{2,}", " ", clean_reply.replace(_recv_5, "", 1)).strip()
                _tm["recv_cap"] = [_drop_5, _ov_5[1], _ov_5[2]]
                logger.info("✂️ 질문 앞 문장 삭제(%s)", _drop_5)
                _recv_5 = ""
            if _swlp_5(_recv_5):
                _n_lp_5 = sum(1 for m in history_messages if (m.role == MessageRole.MODEL or m.role == "model") and _swlp_5(m.content or ""))
                _why_lp_5 = "subject" if _lpws_5(_recv_5) else ("cap" if _n_lp_5 >= _lp_max else "")
                if _why_lp_5:
                    clean_reply = clean_reply.replace(_recv_5, _slp_5(_recv_5), 1)
                    _tm["lead_prefix"] = _why_lp_5

    # 8-s. (2026-11-04 BEI → 2026-11-11 P10-2) 페르소나 슬롯 — 사례당 1회, 사례 리더 턴 3~5, 되받기 뒤. Jessica·Lucas·Olivia 는 LLM 질문을 슬롯 질문으로 대체,
    #   Daniel 은 [되받기] + 관찰 + LLM 질문, Michael 은 [되받기] + 응원 문장 + LLM 질문(실행 의지 질문은 다음 턴). Ella 는 슬롯 없음. 문장은 전부 렌더(고정 문구 없음).
    #   8-w 뒤에서 조립해 '되받기 뒤' 자리를 보장한다. 되받기가 없는 턴에는 넣지 않는다(단독 슬롯 금지 — 다음 턴에 다시 시도).
    if (instruction_used == "EPISODE_PROBE" and _bei_ep and system_override_text is None and not _llm_error and chapter
            and not needs_user_decision and (clean_reply or "").strip() and not _reask_kind):
        from diag_project.services.intro_messages import persona_line as _pl_s
        from diag_project.services.output_guard import is_request_statement as _irs_s, starts_without_main_clause as _swmc_s
        from diag_project.services.persona_voice import persona_key as _pk_s
        _pn_s = _pk_s((state.get("coach_persona") or {}).get("name"))
        _sd_s = session.self_assessment_data or {}
        _ep_turn_s = int(_bei_ep.get("leader_turns") or 0)
        _mq_pending = bool(((_sd_s.get("michael_q_pending") or {}).get(chapter))) if chapter else False
        _ch_i_pre = [k for k in COMPETENCY_FRAMEWORK if k != "supplementary"].index(chapter) if chapter in COMPETENCY_FRAMEWORK else 0
        _sents_s = [x for x in split_sentences(clean_reply) if x.strip()]
        _lead_s = [x for x in _sents_s if not is_question_sentence(x) and not _swmc_s(x)
                   and not re.search(r"(여쭤보겠|여쭙겠|질문드리|물어보겠|묻겠|여쭤볼게요|여쭙니다)[.!…]?$", x.strip())
                   and not _irs_s(x)][:2]   # (P4) 예고 문장은 되받기가 아니다 · (P10) 요청형('…조금 더 듣고 싶습니다')도 — 슬롯 질문과 겹쳐 한 턴에 두 번 묻게 된다
        _qi_s = next((i for i, x in enumerate(_sents_s) if is_question_sentence(x)), None)
        _q_now_s = " ".join(_sents_s[_qi_s:]) if _qi_s is not None else ""
        _filled_s = set(_bei.filled_slots(_bei_ep))
        # (2026-11-05 P4-1 → 2026-11-11 P10-2) 세션 단위 상한 — 슬롯은 챕터당 1회·세션 5회, Michael 실행 의지 질문은 세션 3회.
        #   문장은 고정 문구가 아니라 LLM 이 이 사례의 구체 내용(리더가 고른 선택·버린 선택·그 자리의 사람)을 넣어 쓴다(slot_render, 집중 호출 1회).
        #   형식 불합격·실패면 넣지 않는다(고정 문장으로 메우지 않음) — 사례 리더 턴 3~5 안에서 다음 턴에 다시 시도한다.
        from diag_project.services.intro_messages import (
            MICHAEL_WILL_SESSION_CAP as _mw_cap, SLOT_KIND_TARGET as _skt, SLOT_SESSION_CAP as _sl_cap, slot_kind_for as _skf,
        )
        from diag_project.services.slot_render import render_slot as _rsl
        _slot_used_idx = list(_sd_s.get("slot_used_idx") or [])
        _slot_chapters = dict(_sd_s.get("slot_chapters") or {})
        _slot_texts_s = list(_sd_s.get("slot_texts") or [])
        _mq_n = int(_sd_s.get("michael_q_count") or 0)
        _slot_kind = _skf(_pn_s, len(_slot_used_idx))
        _slot_target_now = _skt.get(_slot_kind or "")
        if _pn_s == "Michael" and _mq_pending and "reflection" in _filled_s:
            _tm["michael_q_done"] = 1   # 다시 한다면·배운 것이 이미 나왔다 — 대기 해제만
            _mq_pending = False
        if _pn_s == "Michael" and _mq_pending and _lead_s:
            if _mq_n < _mw_cap:
                # (P12b-1) 한 번만 쓴다 — 불합격이면 다시 쓰지 않고 그 문장 없이 내보낸다
                _mq, _mq_mode = await _rsl(llm, kind="will", persona_name=_pn_s, transcript=_ep_transcript(_bei_ep), used=_slot_texts_s, rounds=1)
                _tm["slot_render"] = _mq_mode
                if _mq:
                    clean_reply = " ".join(_lead_s + [_mq]).strip()
                    _tm["slot"] = "Michael_q"; _tm["slot_text"] = _mq; _tm["slot_kind"] = "will"; _tm["michael_q_n"] = _mq_n + 1
                    logger.info("🎭 Michael 실행 의지 질문(세션 %d/%d, %s): [%s] 사례 %s", _mq_n + 1, _mw_cap, _mq_mode, chapter, _bei_ep.get("idx"))
                _tm["michael_q_done"] = 1   # 렌더가 안 됐어도 대기는 푼다 — 다음 턴까지 끌지 않는다
            else:
                _tm["michael_q_done"] = 1; _tm["michael_q_cap"] = 1   # 세션 상한 — 대기만 해제
        elif (_slot_kind and not _slot_chapters.get(chapter)
              and len(_slot_used_idx) < _sl_cap and _ep_turn_s in (3, 4, 5) and _slot_target_now not in _filled_s
              and (_lead_s or (_slot_kind in ("observation", "cheer") and _q_now_s))):
            # (2026-11-12 P11b-4) 관찰·응원 슬롯이 들어가는 턴은 [슬롯 1문장 + 질문 1개]만 — 받는 문장·연결 문장 없이. 그 턴의 질문에 쓰인 낱말을 슬롯 문장이
            #   되풀이하지 않게 질문을 렌더에 넘긴다(11/12 p11a: 받기 '쉽지 않은 변화였겠습니다' + 관찰 '쉽지 않은 자리를 지키셨습니다').
            _stmt_slot = _slot_kind in ("observation", "cheer")
            # (2026-11-13 P12b-1) 영역당 1회만 시도한다 — 불합격이면 다시 쓰지 않고 그 문장 없이 내보내며, 이 영역에서는 더 시도하지 않는다
            #   (p12: Michael 응원 문장이 둘째 영역에서 6턴 연속 불합격하며 그때마다 다시 쓰기를 썼다). 시도한 영역은 slot_chapters 에 적는다.
            _tm["slot_tried"] = 1
            _slot_txt, _slot_mode = await _rsl(llm, kind=_slot_kind, persona_name=_pn_s, transcript=_ep_transcript(_bei_ep), used=_slot_texts_s,
                                               rounds=1, avoid_text=(_q_now_s if _stmt_slot else None))
            _tm["slot_render"] = _slot_mode
            if _slot_txt:
                if _slot_kind in ("criterion", "reason", "counterfactual", "other_side"):
                    clean_reply = " ".join(_lead_s + [_slot_txt]).strip()                      # LLM 질문을 슬롯 질문으로 대체
                else:
                    clean_reply = " ".join([_slot_txt] + ([_q_now_s] if _q_now_s else [])).strip()   # (P11b-4) 관찰·응원 문장 + LLM 질문 — 받는 문장은 뺀다
                    _tm["slot_turn"] = "slot+q"
                    if _pn_s == "Michael":
                        _tm["michael_q_pending"] = 1
                _tm["slot"] = _pn_s; _tm["slot_text"] = _slot_txt; _tm["slot_idx"] = len(_slot_used_idx); _tm["slot_kind"] = _slot_kind
                logger.info("🎭 페르소나 슬롯(%s %s, %s): [%s] 사례 %s 턴 %d", _pn_s, _slot_kind, _slot_mode, chapter, _bei_ep.get("idx"), _ep_turn_s)
            else:
                logger.info("🎭 슬롯 문장 불합격(%s %s: %s) — 이번 턴은 넣지 않음", _pn_s, _slot_kind, _slot_mode)
        elif _slot_kind and _ep_turn_s in (3, 4, 5) and not _slot_chapters.get(chapter):
            logger.info("🎭 슬롯 건너뜀(%s): 사례 %s 턴 %d lead=%d target_filled=%s session=%d/%d", _pn_s, _bei_ep.get("idx"), _ep_turn_s, len(_lead_s),
                        _slot_target_now in _filled_s, len(_slot_used_idx), _sl_cap)

    # 8-p. (2026-10-23 6번 보정 → 2026-11-05 P4-2 전면 제거) Michael "좋습니다" 도입: 평가 말투로 금지 — 붙이지 않고 전부 뗀다. 아래 옛 메모는 이력.
    #   고정 문장 턴(안내·확인 템플릿)도 센다 — 재생에서 4·5·6턴 연속 '좋습니다' 가 템플릿 턴에서 났다.
    #   (2026-11-02 p2f) 챕터 누적 상한 3회 — p2c D 세션 83턴 중 39턴이 '좋습니다'(챕터당 6~12). 초과분은 리드 없이
    #   본문부터. 응원 슬롯 턴(그 선택, 응원합니다.)에는 붙이지 않는다.
    #   일시정지 제안 턴(needs_user_decision)도 센다 — 붙이지는 않되(add=False) LLM 이 스스로 쓴 '좋습니다'는 상한·연속 규칙대로 뗀다
    #   (p2f Michael: 성과·사람관리 챕터 4회째가 모두 SUGGEST_PAUSE 턴이었다).
    if (not _llm_error and clean_reply
            and (state.get("coach_persona") or {}).get("name", "").startswith("Michael")):
        # (2026-11-05 P4-2) '좋습니다' 리드는 평가 말투 — 상한이 아니라 전면 제거(붙이지 않고 전부 뗀다). LLM 턴은 8-i 가 재생성까지 한다.
        from diag_project.services.persona_voice import michael_lead_guard as _mlg
        _before_p = clean_reply
        clean_reply, _ = _mlg(clean_reply, False, add=False)
        _tm["good_lead"] = 0
        if clean_reply != _before_p:
            _tm["good_lead_cut"] = 1

    # 8-k. (2026-10-22 P1-3) 모든 코치 턴은 질문 하나로 끝난다 — LLM 출력에 질문이 없으면 그 턴의 고정 질문을 붙인다.
    #   라포(8-0)·INTRO(안내 끝 '시작해볼까요?')·ALIGN/전환(앵커)·프로브(템플릿 앵커·결과 폴백)는 각자 보장하고,
    #   여기서는 정의 질문 턴(DIAGNOSIS_CONFIRM·COMPETENCY_ASK)을 보장한다. 질문을 두지 않는 턴(일시정지 제안·일시중지·
    #   챕터 종료 다리·세션 종료)은 제외.
    if (system_override_text is None and not _llm_error and clean_reply
            and instruction_used in ("DIAGNOSIS_CONFIRM", "COMPETENCY_ASK")):
        # (2026-10-28 P0-4) 정의 턴의 질문은 '고정 정의 질문' 하나뿐 — LLM 이 다른 질문(간접 질문 포함)으로 끝내면
        #   그 질문을 지우고 고정 질문을 붙인다(10/28 재생: 리더가 코치 앵커를 붙여넣자 CONFIRM 이 정의 질문 없이 사례를 청했다).
        from diag_project.services.intro_messages import chapter_scope_line, definition_question, definition_question_variants
        from diag_project.services.output_guard import drop_question_sentences as _dqs_k, split_sentences as _ss_k, strip_praise as _sp_k
        _cn_k = COMPETENCY_FRAMEWORK.get(chapter, {}).get("name", "이 역량")
        _pn_k = (state.get('coach_persona') or {}).get('name')
        _ch_i_k = [k for k in COMPETENCY_FRAMEWORK if k != "supplementary"].index(chapter) if chapter in COMPETENCY_FRAMEWORK else 0
        _defq_k = definition_question(_cn_k, _pn_k, _ch_i_k)   # (2026-11-05 P4-1) 5종 순환 — 챕터 순서 인덱스, 한 세션에 같은 문장 없음
        if not any(v in clean_reply for v in definition_question_variants(_cn_k, _pn_k)):
            _body_k, _nq_k = _dqs_k(clean_reply)
            _body_k, _ = _sp_k(_body_k)
            if re.search(r"(재료|장을\s*어떻게|시간과 자원)", _body_k) and not (chapter == "work_management" and "재료" not in _body_k):
                _body_k = ""                            # (2026-11-10 P9) 가이드 예시(다른 분야 문장)를 베낀 범위 문장은 버린다
            if not [x for x in _ss_k(_body_k) if x.strip()]:
                _body_k = chapter_scope_line(chapter)   # (P4-1) '이 영역에서 무엇을 볼지' 1문장 — LLM 이 안 썼으면 결정론 문장
                _tm["scope_fallback"] = 1
            # (2026-11-10 P9-6) 범위 문장에도 페르소나 어미 — LLM 문장·폴백 문장 모두. 교정 뒤에도 섞이면 폴백 문장(교정본)으로
            #   (승인 조건 1) 어미 강제는 범위 문장(본문의 마지막 평서문)에만 — 앞의 받는 문장은 그대로 둔다
            from diag_project.services.persona_register import apply_register as _areg_k
            _sk = [x.strip() for x in _ss_k(_body_k) if x.strip()]
            # (lb1) 범위 문장 자리에 예고 문장("먼저 여쭤볼게요.")만 온 턴 — 예고는 범위 문장이 아니다. 걷어내고, 남는 게 없으면 영역별 범위 문장으로
            #   (2026-11-13 P12b-4) "이번에는 … 어떻게 바라보고 계신지 들어보고 싶어요." — 듣고 싶다는 꼴도 예고다. 차례를 알리는 머리('이번에는')는 뗀다
            _sk = [x for x in _sk if not re.search(r"(여쭤볼게요|여쭙겠습니다|여쭤보겠습니다|물어볼게요|묻겠습니다|질문드릴게요|질문드리겠습니다|시작할게요|시작하겠습니다|"
                                                   r"(듣고|들어\s?보고|여쭤\s?보고|여쭙고|알고)\s*싶(어요|습니다|네요))[.!…]*$", x)]
            _sk = [re.sub(r"^(이번\s?영역에서는?|이\s?영역에서는?|이번에는|이번엔|다음은|다음으로는?|이어서는?)\s+", "", x) for x in _sk]      # (P12c-6) '이번 영역에서는'도
            # (시뮬 p11b) "그 과정에서 리더님이 어떤 생각으로 판단하셨는지를 중심으로 보겠습니다." — 영역 첫 문장인데 앞의 무엇을 가리키는 말로 시작한다. 영역별 범위 문장으로
            if any(re.match(r"^(그\s?(과정|때|일|자리|장면|부분|가운데|중에서)|이\s?과정|그렇게|그러면서)", x) for x in _sk):
                _sk = [chapter_scope_line(chapter)]
                _tm["scope_fallback"] = 1
            if not _sk:
                _sk = [chapter_scope_line(chapter)]
                _tm["scope_fallback"] = 1
            _first_ch_k = instruction_used == "DIAGNOSIS_CONFIRM"
            if _first_ch_k:
                # (2026-11-11 P10-7) 첫 영역 진입 다리는 고정 문장으로 복원 — LLM 이 쓴 진입 문장('그럼 첫 영역인 …부터')은 걷어내고 범위 문장만 남긴다
                _sk = [x for x in _sk if not re.search(r"(첫\s*(번째\s*)?영역|부터\s*(시작|볼|보겠|가\s*볼|여쭙|들어))", x)] or [chapter_scope_line(chapter)]
            else:
                # (P10 p10a) 전환 영역: 직전 턴의 고정 다리("이제 '성과관리' 쪽으로 …")가 이미 넘어간다고 말했다 — LLM 이 다시 쓴 진입 문장은 걷어낸다
                _mv_k = re.compile(re.escape(_cn_k) + r"['’”\"]?\s*(쪽|영역)?\s*(으로|로|에서|을|를|부터)?\s*[^.?!]{0,12}(가\s*볼|가볼|넘어|이어|옮겨|들어가|바꿔|시작해|시작하|볼게요|보겠)")   # (p10b) '성과관리 쪽에서 이야기를 시작해 볼게요'도
                _sk = [x for x in _sk if not _mv_k.search(x)] or [chapter_scope_line(chapter)]
            _scope_k, _n_reg_k, _left_k = _areg_k(_pn_k, _sk[-1], scope="strict")   # (P10-4) 범위 문장은 코치 어미 강제
            if _left_k:
                _scope_k, _, _ = _areg_k(_pn_k, chapter_scope_line(chapter), scope="strict")
                _tm["scope_fallback"] = 2
            _body_k = " ".join(_sk[:-1] + [_scope_k])
            if _first_ch_k:
                from diag_project.services.intro_messages import first_chapter_bridge as _fcb_k
                _body_k = f"{_fcb_k(_cn_k, _pn_k)} {_scope_k}"
                _tm["first_bridge"] = 1
            if _n_reg_k:
                _tm["register_fix"] = int(_tm.get("register_fix") or 0) + _n_reg_k
            clean_reply = f"{_body_k.rstrip()} {_defq_k}".strip()
            _tm["no_q_fix"] = "definition" if _nq_k == 0 else f"definition(replaced {_nq_k})"
            _tm["def_variant"] = _ch_i_k % 5
            logger.info("❓ 정의 턴 질문 고정(#%d): LLM 질문 %d문장 제거 후 고정 정의 질문 결합", _ch_i_k % 5, _nq_k)

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
        if _ex_cap and chapter:
            # (2026-11-04 P3-4) Michael 느낌표는 챕터당 EXCLAMATION_PER_CHAPTER(2)개까지 — 챕터 누적(excl_by_chapter)이 차면 이번 턴 상한 0
            from diag_project.services.style_tracker import EXCLAMATION_PER_CHAPTER as _epc
            if int(((session.self_assessment_data or {}).get("excl_by_chapter") or {}).get(chapter, 0) or 0) >= _epc:
                _ex_cap = 0
                _tm["excl_chapter_cap"] = 1
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
                _ex_regen = await _timed_regen(why="exclamation", 
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

    if state.get("finish_choice_turn") and not _llm_error:
        # (2026-11-06 P7-3) 그만하겠다는 요청: [수용 1문장(LLM)] + 고정 안내 한 줄. 직전 질문을 pending(user_pause)으로 보관해 '이어서'면 그대로 다시 낸다.
        from diag_project.services.intro_messages import finish_choice_line
        from diag_project.services.input_anomaly import last_question_of as _lqo_f
        from diag_project.services.output_guard import drop_question_sentences as _dqs_f, split_sentences as _ss_f, strip_praise as _sp_f
        _ack_f, _ = _dqs_f(clean_reply or ""); _ack_f, _ = _sp_f(_ack_f)
        _ack_f = " ".join([x.strip() for x in _ss_f(_ack_f) if x.strip()][:1])
        clean_reply = f"{_ack_f}\n\n{finish_choice_line((state.get('coach_persona') or {}).get('name'))}".strip()
        _pst_f = dict(session.self_assessment_data or {})
        _prev_model_f = next((m for m in reversed(history_messages) if (m.role == MessageRole.MODEL or m.role == "model")), None)
        _pst_f["pending_instruction"] = {
            "kind": "user_pause", "instruction": getattr(_prev_model_f, "instruction_used", None), "chapter": chapter, "target": current_target_sub,
            "question": _lqo_f(_prev_coach_text) or "", "user_text": "", "at": datetime.utcnow().isoformat(timespec="seconds"),
        }
        session.self_assessment_data = _pst_f
        from sqlalchemy.orm.attributes import flag_modified as _fm_f
        _fm_f(session, "self_assessment_data")
        _tm["finish_choice"] = 1
        logger.info("⏸️ 중단 요청 안내(선택 대기): chapter=%s question=%r", chapter, (_lqo_f(_prev_coach_text) or "")[:40])

    if needs_user_decision and _backend_pause_suggested and clean_reply:
        # (2026-10-22 P1-1) 제안 턴은 '되받기 한 문장 + 안내'만 — 질문은 삼키되 버리지 않는다:
        #   이 턴의 instruction·타겟·리더 답변을 pending 으로 저장하고, 원장(asked/turns/target)은 스텝 이전으로 되돌린다.
        #   리더가 '계속'이면 다음 턴 decider 가 pending 을 그대로 실행(같은 타겟·같은 탐침), '다음에'면 paused.
        from diag_project.services.intro_messages import pause_suggestion_text
        from diag_project.services.output_guard import receive_sentence as _recv_pause
        _recv_only = _recv_pause(clean_reply, fallback="")
        clean_reply = f"{_recv_only}\n\n{pause_suggestion_text(_sit_elapsed, (state.get('coach_persona') or {}).get('name'))}".strip()
        _pst = dict(session.self_assessment_data or {})
        if _ledger_snapshot is not None:
            _pst = _bei.restore(_pst, _ledger_snapshot)   # (BEI) 이 턴의 리더 턴·슬롯·사례 종료를 되돌린다 — 재개 턴이 같은 답으로 다시 판정한다
            _bei_closed.clear()
            _tm["slot"] = None
        _pst["pending_instruction"] = {
            # (2026-11-10 P9-8) 사례 단계 턴은 재개 때 EPISODE_PROBE 로 다시 들어가 같은 답을 재판정한다(원장을 되돌렸으므로 사례 종료·다음 사례 열기가 그대로 재현)
            "instruction": ("EPISODE_PROBE" if instruction_used in _bei.BEI_INSTRUCTIONS else instruction_used), "chapter": chapter, "target": current_target_sub,
            "user_text": (request.content or "")[:1000], "at": datetime.utcnow().isoformat(timespec="seconds"),
        }
        session.self_assessment_data = _pst
        from sqlalchemy.orm.attributes import flag_modified as _fm_pst
        _fm_pst(session, "self_assessment_data")
        logger.info("⏸️ 일시정지 제안: 질문 보류 → pending=%s target=%s (원장 되돌림=%s)",
                    instruction_used, current_target_sub, _ledger_snapshot is not None)

    # 8-x2. (2026-11-02 p2c) 페르소나 슬롯 문장 복원 — 슬롯은 프로브 스텝에서 본문을 조립하지만 8-n 입버릇 재생성·8-o 한 질문·
    #   8-p Michael 리드 보정이 뒤에서 본문을 바꾸면 고정 문장이 사라진다(p2c 24세션: Michael 16/25·Jessica 5/25 유실 — 린트 슬롯 열은
    #   삽입 플래그만 세어 25/25 로 보였다). 사다리 복원(8-x)과 같은 자리에서 되돌린다.
    if (_tm.get("slot") and _tm.get("slot_text") and system_override_text is None and not _llm_error
            and _align_ctx is None and (clean_reply or "").strip()):
        try:
            from diag_project.services.persona_voice import restore_slot_sentence as _rss
            clean_reply, _sr = _rss(clean_reply, _tm["slot"], _tm["slot_text"])
            if _sr:
                _tm["slot_restored"] = 1
                logger.info("🎭 슬롯 문장 복원(뒤 단계가 덮음): [%s] %s", chapter, _tm["slot"])
        except Exception as _se_x:   # noqa: BLE001
            logger.warning("슬롯 복원 실패 — 건너뜀: %s", _se_x)

    # 8-y0. (2026-11-05 s2b) 출력 규칙 되읊기 제거 — 재생성 출력이 '답변 문장만 드리면 이렇게 됩니다. "…"' 꼴로 나온 턴(Michael SWEEP_FOLLOWUP)
    if system_override_text is None and not _llm_error and (clean_reply or "").strip():
        from diag_project.services.output_guard import strip_meta_echo as _sme
        clean_reply, _n_me = _sme(clean_reply)
        if _n_me:
            _tm["meta_echo"] = _n_me
            logger.info("🧹 출력 규칙 되읊기 %d건 제거", _n_me)

    # 8-x2. (2026-11-06 P7) 허위 귀속 절 삭제 — 사례 턴(LLM 질문 턴)에서 "방금 말씀하신 '피드백'과도 닿아 있는데요," 처럼 리더가 하지 않은 말
    #   (하위역량 이름)을 리더 말로 돌리는 연결 절을 지운다(p7b Ella NO_CASE_REFRAME 7회). 실제 리더 발화에 있는 인용은 보존. 결정론, 재생성 없음.
    if system_override_text is None and not _llm_error and (clean_reply or "").strip() and (_is_probe or _is_open or instruction_used == "COMPETENCY_ASK"):   # (P9) 영역 첫 턴·여는 턴에도
        from diag_project.services.output_guard import strip_false_attribution as _sfa_x
        clean_reply, _fa_removed = _sfa_x(clean_reply, _llm_user_text)
        if _fa_removed:
            _tm["false_attr"] = len(_fa_removed)
            logger.info("🔒 허위 귀속 절 삭제 %s", _fa_removed)

    # 8-y. (2026-10-29) 최종 누설 소거 — 8-i 뒤의 재생성(8-j 전환·8-n 입버릇·8-h 느낌표)이 만든 새 LLM 출력은 8-i 의 누설 검사를
    #   거치지 않았다(s291 Jessica t10: 8-n 재생성 출력이 '되받기 한 문장 + 다리 한 문장으로 답하겠습니다.'로 시작). 엄격 사전 어휘·
    #   상태 보고문이 든 평서문만 지운다(질문 보존). ALIGN 은 조립(8-z) 전의 되받기에 걸리므로 고정 문장은 건드리지 않는다.
    if system_override_text is None and not _llm_error and (clean_reply or "").strip():
        if instruction_used == "COMPETENCY_ALIGN":
            # (2026-11-14 P12c-6) ALIGN 받기 끝의 예고("…그대로 살펴볼게요.") — 그 문장만 지운다. 받기가 비면 조립(8-z)이 리더 정의의 구절로 받는다
            _al_s = [x.strip() for x in split_sentences(clean_reply) if x.strip()]
            _al_k = [x for x in _al_s if not re.search(r"살펴\s?(볼게요|보겠습니다|볼\s?거예요|보려고\s?(해요|합니다))[.!…]*$", x)]
            if len(_al_k) != len(_al_s):
                clean_reply = " ".join(_al_k)
                _tm["align_announce_cut"] = len(_al_s) - len(_al_k)
        try:
            from diag_project.services.leak_lexicon import find_leaks as _fl_y, find_state_report as _fsr_y, strip_leak_sentences as _sls_y
            from diag_project.services.output_guard import strip_state_leak as _ssl_y, rewrite_incident_word as _riw_y
            # (2026-11-10 P10) 사례 번호 금지 — "사례 1에서 …" 는 그 사례에서 리더가 쓴 낱말로("아까 말씀하신 개편 건에서") 바꾼다
            if chapter and re.search(r"(이번|이)\s?사례에서", clean_reply):
                # (2026-11-14 P12d-4) "지금 돌아보면 이 사례에서 …" — 안에서 쓰는 말. 구절만 지운다(문장은 남긴다)
                clean_reply = re.sub(r"[ \t]{2,}", " ", re.sub(r"(이번|이)\s?사례에서(는|도)?\s*", "", clean_reply)).strip()
                _tm["case_word_cut"] = 1
            if chapter and re.search(r"사례", clean_reply):
                from diag_project.services.output_guard import key_noun_phrase as _knp_y, rewrite_case_numbers as _rcn_y
                _labels_y = {}
                for _e_y in _bei.episodes(session.self_assessment_data or {}, chapter):
                    if _e_y.get("kind", "episode") == "episode":
                        _sl_y = _e_y.get("slots") or {}
                        _lb_y = _knp_y((_sl_y.get("context") or {}).get("quote") or (_sl_y.get("action") or {}).get("quote") or "")
                        if _lb_y:
                            _labels_y[int(_e_y.get("idx") or 0)] = _lb_y
                clean_reply, _n_cn_y = _rcn_y(clean_reply, _labels_y)
                if _n_cn_y:
                    _tm["case_number"] = _n_cn_y
            # (2026-11-10 P10) 요청형 받는 문장('…조금 더 듣고 싶습니다.') 뒤에 질문이 있으면 요청 문장을 지운다 — 한 턴에 묻는 것은 하나
            if _is_probe or _is_open:
                # (2026-11-11 P10-6) 여는 턴(EPISODE_OPEN·SWEEP_ANCHOR)도 본다 — 11/11 운영 Olivia: SWEEP 여는 턴 앞의 '조금 더 듣고 싶어요'가 남았다.
                #   종전에는 탐침 턴에만 걸렸고, 닫는 쪽 금지 꼴에도 '듣고 싶' 이 없었다. 시스템 여는 문장(앵커)은 건드리지 않는다.
                from diag_project.services.output_guard import drop_request_statements as _drs_y
                _keep_rq_y = {re.sub(r"\s+", "", x) for x in (split_sentences(_bei_anchor_text or "") + [_tm.get("slot_text") or ""]) if x}
                _c_rq_y, _n_rq_y = _drs_y(clean_reply, keep=_keep_rq_y)
                if _n_rq_y and _c_rq_y.strip():
                    clean_reply = _c_rq_y
                    _tm["request_cut"] = _n_rq_y
            if (_is_probe or _is_open) and _align_ctx is None and not needs_user_decision:
                # (2026-11-12 P11-D·H) 예고 문장('…여쭤보겠습니다', '…듣고 싶습니다', '…이어가겠습니다') · 때 이른 감사('사례를 들려주셔서 감사합니다' — 사례를 닫는 턴에서만) ·
                #   받는 문장 금지 꼴(8-w 재생성이 다시 들여온 것) · 리더가 하지 않은 말 귀속(따옴표 인용, '방금/앞서 말씀하신 ○○' — 이번 세션 리더 발화와 문자열 대조).
                from diag_project.services.intro_messages import all_fixed_sentences as _afs_d, line_register as _lreg_d
                from diag_project.services.turn_checks import (
                    default_slot_question as _dsq_d, drop_announcements as _dan_d, drop_banned_receives as _dbr_d,
                    drop_premature_thanks as _dpt_d, strip_unsaid_attribution as _sua_d,
                )
                _keep_d = {re.sub(r"\s+", "", x) for x in (split_sentences(_bei_anchor_text or "") + [str(_tm.get("slot_text") or "")] + _afs_d()) if x}
                # (2026-11-12 P11b-3) 내용 없는 연결 문구 — "방금 말씀하신 ○○과도 이어지는 부분입니다만," 틀은 인용이 맞든 틀리든 통째로 지운다.
                #   사례를 여는 턴(EPISODE_OPEN·SWEEP_ANCHOR)의 진행 해설("…을 살펴보는 대목입니다", "…살펴보겠습니다")도 지운다 — 여는 문장 안의 것까지.
                from diag_project.services.turn_checks import strip_link_frames as _slf_d, strip_progress_commentary as _spc_d
                _c_d, _n_lk_d = _slf_d(clean_reply, keep={re.sub(r"\s+", "", str(_tm.get("slot_text") or ""))} - {""})
                if _n_lk_d:
                    clean_reply = _c_d; _tm["link_cut"] = _n_lk_d
                if _is_open and instruction_used in ("EPISODE_OPEN", "SWEEP_ANCHOR"):
                    _c_d, _n_cm_d = _spc_d(clean_reply)
                    if _n_cm_d:
                        clean_reply = _c_d; _tm["commentary_cut"] = _n_cm_d
                _c_d, _r_d = _dan_d(clean_reply, keep=_keep_d)
                if _r_d:
                    clean_reply = _c_d; _tm["announce_cut"] = len(_r_d)
                if _is_probe:
                    # (시뮬 p11a) 그 턴의 질문이 예고 꼴 하나뿐이면('…무엇이었는지 여쭙고 싶습니다.') 지울 수 없다 — 묻는 꼴로 바꾼다
                    from diag_project.services.turn_checks import request_to_question as _rtq_d
                    _sents_rq = [x.strip() for x in split_sentences(clean_reply) if x.strip()]
                    if _sents_rq and re.sub(r"\s+", "", _sents_rq[-1]) not in _keep_d:
                        _new_rq = _rtq_d(_sents_rq[-1], formal=(_lreg_d((state.get('coach_persona') or {}).get('name')) == "formal"))
                        if _new_rq:
                            clean_reply = clean_reply.replace(_sents_rq[-1], _new_rq, 1)
                            _tm["request_q"] = 1
                if not _tm.get("closed"):
                    _c_d, _r_d = _dpt_d(clean_reply, keep=_keep_d)
                    if _r_d:
                        clean_reply = _c_d; _tm["thanks_cut"] = len(_r_d)
                _c_d, _r_d = _dbr_d(clean_reply, keep=_keep_d)
                if _r_d:
                    clean_reply = _c_d; _tm["recv_ban"] = list(_tm.get("recv_ban") or []) + _r_d
                _names_d = [v.get("name") for v in COMPETENCY_FRAMEWORK.values() if v.get("name")] + ["네"]
                _c_d, _hits_d, _lost_d = _sua_d(clean_reply, _prev_user_texts + [request.content or "", _llm_user_text or ""], exempt=_names_d, keep=_keep_d)
                if _hits_d:
                    clean_reply = _c_d
                    _tm["unsaid_attr"] = _hits_d[:4]
                    if _lost_d and _is_probe:
                        _slot_d = (_bei.unfilled_slots(_bei_ep) or ["reflection"])[0] if _bei_ep else "action"
                        clean_reply = f"{clean_reply} {_dsq_d(_slot_d, formal=(_lreg_d((state.get('coach_persona') or {}).get('name')) == 'formal'), topic_text=((((_bei_ep or {}).get('slots') or {}).get('context') or {}).get('quote') or ''))}".strip()
                        _tm["q_complete"] = f"default:{_slot_d}(attr)"
                    logger.info("🔒 리더가 하지 않은 말 귀속 삭제 %s", _hits_d)
            if _is_probe:
                # (P10 p10b) 8-i 뒤 재생성(8-w)이 다시 들여온 질문 뒤 권유문('…태도 같은 것도 괜찮아요.')을 한 번 더 걷어낸다
                from diag_project.services.output_guard import strip_suggestion_statements as _sss_y
                _c_sg_y, _n_sg_y = _sss_y(clean_reply)
                if _n_sg_y and _c_sg_y.strip():
                    clean_reply = _c_sg_y
                    _tm["suggestion_cut"] = int(_tm.get("suggestion_cut") or 0) + _n_sg_y
            if "사건" in clean_reply:   # (p2f) 8-i 뒤 재생성 출력(8-j·8-n·8-h)에도 '사건' 치환
                clean_reply, _n_riw_y = _riw_y(clean_reply)
                if _n_riw_y:
                    _tm["incident_word"] = int(_tm.get("incident_word") or 0) + _n_riw_y
            # (2026-11-05 P4-2) 8-i 뒤 재생성(8-n·8-w·8-h)이 들여온 평가 말투는 여기서 문장째 뗀다(질문 보존). 고정 문장(슬롯 응원)은 제외.
            from diag_project.services.output_guard import find_praise as _fp_y, strip_praise as _sp_y
            from diag_project.services.intro_messages import all_fixed_sentences as _afs_y
            _fixed_y = {re.sub(r"\s+", "", x) for x in (_afs_y() + [_tm.get("slot_text") or ""] + list((session.self_assessment_data or {}).get("slot_texts") or [])) if x}
            _pr_y = [x for x in split_sentences(clean_reply) if re.sub(r"\s+", "", x) not in _fixed_y and _fp_y(x)]
            if _pr_y and _align_ctx is None:
                _out_y = clean_reply
                for _x in _pr_y:
                    _sx, _ = _sp_y(_x)
                    _out_y = _out_y.replace(_x, _sx if _sx.strip() and _sx != _x and ("?" in _x) else "", 1)
                _out_y = re.sub(r"[ \t]{2,}", " ", _out_y).strip()
                if _out_y:
                    clean_reply = _out_y
                    _tm["praise_final"] = len(_pr_y)
                    logger.info("🛡️ 최종 평가 말투 %d문장 제거", len(_pr_y))
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

    # 8-q. (2026-11-12 P11c-2·4) 모든 사례 턴은 질문 하나로 끝난다(닫는 턴·안내 턴·휴식 제안 턴 제외). 후처리가 끝난 뒤에 본다.
    #   ① 사례 없음 뒤 재질문(NO_CASE_REFRAME)의 질문이 '그런 일이 있었는지'를 묻는 꼴이 아니거나 사례가 있다고 전제하면 같은 주제의 다른 사전 질문으로 바꾼다.
    #   ② 같은 질문(낱말만 바꾼 것 포함)이 이 사례에서 이미 2번 나갔으면 아직 듣지 못한 다른 한 가지의 기본 질문으로 바꾼다.
    #   ③ 질문이 0개면 붙인다 — 여는 턴은 여는 문장, 재질문 턴은 사전 질문, 탐침 턴은 그 턴에 물을 한 가지의 기본 질문.
    if ((_is_probe or _is_open) and chapter and system_override_text is None and not _llm_error and not needs_user_decision and _align_ctx is None
            and (clean_reply or "").strip()):
        from diag_project.services.intro_messages import line_register as _lreg_q
        from diag_project.services.turn_checks import default_slot_question as _dsq_q, reframe_question_ok as _rqo_q, same_question as _sameq_q
        _formal_q = _lreg_q((state.get('coach_persona') or {}).get('name')) == "formal"
        _qs_q = [x.strip() for x in split_sentences(clean_reply) if x.strip() and is_question_sentence(x)]
        _un_q = (_bei.unfilled_slots(_bei_ep) or ["reflection"]) if _bei_ep else ["action"]
        if _bei_ep and _bei.ask_slot(_bei_ep) in _un_q:
            _un_q = [_bei.ask_slot(_bei_ep)] + [x for x in _un_q if x != _bei.ask_slot(_bei_ep)]      # (P12-2) 이번 턴이 향하는 것부터
        _topic_q = (((_bei_ep or {}).get("slots") or {}).get("context") or {}).get("quote") or ""
        _tgt_q = current_target_sub or (_bei_ep or {}).get("opener_sub")      # 재질문 턴에는 여는 하위역량이 사례에만 적혀 있다
        _drag_q = None
        if instruction_used == "NO_CASE_REFRAME" and _qs_q:
            # (2026-11-12 P11e-1) 재질문이 앞에서 닫힌 사례를 끌어오면('교육 체계 개편처럼 …') 같은 주제의 사전 질문으로 바꾼다
            from diag_project.services.turn_checks import mentions_closed_case as _mcc_q
            _ctx_q = [((e.get("slots") or {}).get("context") or {}).get("quote") or "" for e in _bei.episodes(session.self_assessment_data or {}, chapter)
                      if e.get("status") not in ("open",)]
            _drag_q = _mcc_q(" ".join(_qs_q), [x for x in _ctx_q if x])
            if _drag_q:
                _tm["reframe_drag"] = _drag_q
        if instruction_used == "NO_CASE_REFRAME" and _qs_q and (_drag_q or not _rqo_q(_qs_q[-1])) and _tgt_q:
            _alt_q = _anchor_for_sub(_tgt_q, alt=True)
            if _alt_q:
                clean_reply = clean_reply.replace(_qs_q[-1], _alt_q, 1)
                _tm["q_added"] = "reframe_alt"
                _qs_q[-1] = _alt_q
        if _is_probe and not _reask_kind and instruction_used != "NO_CASE_REFRAME" and _qs_q and _bei_ep:
            _prev_q = []
            for _r_q, _t_q in _ep_transcript(_bei_ep):
                if _r_q == "model":
                    _pq = [x.strip() for x in split_sentences(_t_q or "") if x.strip() and is_question_sentence(x)]
                    if _pq:
                        _prev_q.append(_pq[-1])
            if sum(1 for x in _prev_q if _sameq_q(x, _qs_q[-1])) >= 2:
                _cands_q = [_dsq_q(sl, formal=_formal_q, topic_text=_topic_q) for sl in (_un_q[1:] + ["reflection"])]
                _new_q = next((c for c in _cands_q if not any(_sameq_q(x, c) for x in _prev_q)), "")
                if _new_q:
                    clean_reply = clean_reply.replace(_qs_q[-1], _new_q, 1)
                    _tm["q_added"] = "repeat_cap"
        if not _qs_q:
            if _is_open and _bei_anchor_text:
                _add_q = _bei_anchor_text
            elif instruction_used == "NO_CASE_REFRAME" and _tgt_q:
                _add_q = _anchor_for_sub(_tgt_q, alt=True)
            else:
                _add_q = _dsq_q(_un_q[0], formal=_formal_q, topic_text=_topic_q)
            if _add_q:
                clean_reply = f"{clean_reply.strip()} {_add_q}".strip()
                _tm["q_added"] = "none→" + ("opener" if _is_open else ("reframe" if instruction_used == "NO_CASE_REFRAME" else _un_q[0]))
                _tm["opener_restored"] = 2 if _is_open else _tm.get("opener_restored")

    # 8-z. (2026-10-28 P0-1) ALIGN 최종 조립 — 모든 후처리 뒤. 되받기(가드 통과본) + 고정 정의 + 목록 + 안내 + 다리 + 앵커.
    if _align_ctx is not None and system_override_text is None and not _llm_error and chapter:
        from diag_project.services.align_render import align_shape_ok as _aso_z, render_align as _ra_z
        clean_reply = _ra_z(llm_text=clean_reply, chapter=chapter, **_align_ctx)
        _ok_z, _why_z = _aso_z(clean_reply, _align_ctx["sub_names"])
        _tm["align_shape"] = "ok" if _ok_z else ";".join(_why_z)
        if not _ok_z:
            logger.warning("📐 ALIGN 형식 자가점검 실패: %s", _why_z)

    # 8-yz. (2026-11-12 P11-H) 받기 겹침 측정(기록만) — 받는 문장(첫 평서문)의 어절이 리더 직전 답에서 얼마나 왔는가. 상한값을 정하기 위한 자료다.
    if system_override_text is None and not _llm_error and chapter and (_is_probe or _is_open) and (clean_reply or "").strip() and not _reask_kind:
        try:
            from diag_project.services.turn_checks import receive_overlap as _rov_y
            _fx_ov = {re.sub(r"\s+", "", x) for x in (split_sentences(_bei_anchor_text or "") + [str(_tm.get("slot_text") or "")]) if x}
            _recv_ov = next((x for x in split_sentences(clean_reply) if x.strip() and not is_question_sentence(x) and re.sub(r"\s+", "", x) not in _fx_ov), "")
            if _recv_ov:
                _tm["recv_overlap"] = list(_rov_y(_recv_ov, _llm_user_text))
        except Exception:   # noqa: BLE001
            pass

    # 8-zz. (2026-11-10 P9-7) 입버릇 상한 — '살펴보려고 합니다' 세션 2회, '말씀해 주시겠습니까' 챕터 2회. 넘으면 대체 표현으로(재생성 없음).
    if not _llm_error and (clean_reply or "").strip():
        try:
            from diag_project.services.phrase_caps import enforce_phrase_caps as _epc
            _model_txt_z = [(m.content or "", m.chapter) for m in history_messages if (m.role == MessageRole.MODEL or m.role == "model")]
            from diag_project.services.persona_register import register_of as _rof_z
            clean_reply, _pc_z = _epc(clean_reply, session_texts=[t for t, _ in _model_txt_z],
                                      chapter_texts=[t for t, c in _model_txt_z if chapter and c == chapter],
                                      formal=_rof_z((state.get("coach_persona") or {}).get("name")) == "formal")
            if _pc_z:
                _tm["phrase_cap"] = _pc_z
                logger.info("🗣️ 입버릇 상한 → 대체 표현: %s", _pc_z)
        except Exception as _e_pc:   # noqa: BLE001
            logger.warning("입버릇 상한 처리 실패 — 건너뜀: %s", _e_pc)
        # (2026-11-10 P9-6 → 승인 조건 1) 페르소나 말투 — **질문 문장과 고정 문장에만** 건다(Jessica·Daniel 은 질문을 '~습니까'로, Ella·Olivia·Michael 은
        #   질문을 '~습니까'로 끝내지 않는다). 받는 문장(되받기)은 '~군요/~네요/~셨군요' 그대로 둔다. 시스템 고정 턴(템플릿)과 안내 본문은 전부 본다.
        #   어미표에 있는 꼴만 고치고(재생성 없음) 남은 것은 guard_log register_left 로 남긴다.
        try:
            from diag_project.services.intro_messages import build_intro_anchor_section as _bias_z
            from diag_project.services.persona_register import apply_register as _areg_z
            _fixed_z = ([x for x in split_sentences(_bias_z((state.get("coach_persona") or {}).get("name"))) if x.strip()]
                        if instruction_used == "DIAGNOSIS_INTRO" else [])
            # (2026-11-13 P12-7) 해요체 코치는 평서문도 본다 — '…궁금합니다', 마무리 문장이 합쇼체로 나갔다. 합쇼체 코치는 종전대로 질문 문장만
            #   (받는 문장의 '~군요/~네요'를 그대로 두기 위해서다 — 해요체 코치에게는 그 꼴이 위반이 아니다).
            from diag_project.services.persona_register import register_of as _rof_zz
            _polite_zz = _rof_zz((state.get("coach_persona") or {}).get("name")) == "polite"
            clean_reply, _n_reg_z, _left_z = _areg_z((state.get("coach_persona") or {}).get("name"), clean_reply,
                                                     scope=("all" if system_override_text is not None else ("strict" if _polite_zz else "questions")),
                                                     fixed=_fixed_z)
            if _n_reg_z:
                _tm["register_fix"] = int(_tm.get("register_fix") or 0) + _n_reg_z
            if _left_z:
                _tm["register_left"] = len(_left_z)
            # (2026-11-12 P11b-1) LLM 이 쓴 ㄹ 탈락 오류('교육팀을 이끄고 계시는군요' → '이끌고') — 긴 ㄹ 어간만 표로 고친다
            from diag_project.services.conjugation import repair_l_stem as _rls_z
            clean_reply, _n_cj_z = _rls_z(clean_reply)
            if _n_cj_z:
                _tm["conj_fix"] = _n_cj_z
        except Exception as _e_rg:   # noqa: BLE001
            logger.warning("말투 교정 실패 — 건너뜀: %s", _e_rg)

    if _reask_kind and _reask_final and system_override_text is None and not _llm_error and not needs_user_decision:
        clean_reply = _reask_final          # (P11d-1) 다시 묻기 턴은 사과 1문장 + 질문 1개(또는 질문 1개)로 고정

    # 9. 사례 행(Event) 저장 + AI 메시지 저장
    #   (2026-11-04 BEI) 탐침 종류는 instruction 으로만: 여는 턴·SWEEP 앵커·ALIGN = INCIDENT, 사례 탐침 = SPECIFICATION, META = META.
    _PROBE_TYPE_BY_INSTR = {"EPISODE_OPEN": "INCIDENT", "SWEEP_ANCHOR": "INCIDENT", "COMPETENCY_ALIGN": "INCIDENT",
                            "EPISODE_PROBE": "SPECIFICATION", "NO_CASE_REFRAME": "SPECIFICATION", "SWEEP_FOLLOWUP": "SPECIFICATION",
                            "META_QUESTION_FROM_USER": "META"}
    probe_type_used = None if system_override_text is not None else _PROBE_TYPE_BY_INSTR.get(instruction_used)

    # 사용자가 '계속' 동의(CHAPTER_CONTINUE_CONFIRMED)했을 때만 다음 챕터를
    # '시작됨'으로 표시해, 중간 CONFIRM 턴 없이 바로 다음 영역 합의(ALIGN)로
    # 이어지게 한다. (CHAPTER_READY_TO_END 는 이제 전환하지 않고 대기만 한다.)
    _seamless_next_chapter = None
    if instruction_used == "CHAPTER_READY_TO_END" and is_chapter_completed and is_chapter_starting:
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

    # (2026-11-04 BEI) 이번 턴에 종료된 사례 → Event 행 1건씩(situation/action/result = 슬롯 인용, mapped_subcompetency = strong 라벨).
    #   분석 입력 '[수집된 핵심 사건]' 블록과 이력 압축(완료 사례 → 요약 1줄)이 이 행을 읽는다. 일시정지 제안 턴은 쓰지 않는다(되돌림).
    is_pre_diagnosis = (instruction_used in PRE_DIAGNOSIS_INSTRUCTIONS)
    real_event_id = None
    if chapter and _bei_closed and not needs_user_decision:
        for _ep_c in _bei_closed:
            try:
                _ev_id = await _write_episode_event(db, session.id, chapter, _ep_c, events_all=all_events, messages=history_messages)
                if _ev_id and _ep_c.get("kind", "episode") == "episode":
                    real_event_id = _ev_id
            except Exception as _ee:   # noqa: BLE001 — 사례 행 저장 실패가 턴을 막지 않게
                logger.warning("사례 Event 저장 실패(무시): %s", _ee)

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
        event_id=None,   # (BEI) 사례 종료 시 그 사례의 메시지들에 event_id 를 일괄 태깅한다(_write_episode_event)
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
            if _tm.get("voiced"):
                _vvc = dict(_gl_store.get("voice_variant_count") or {})
                _vvc[chapter] = int(_vvc.get(chapter, 0) or 0) + 1
                _gl_store["voice_variant_count"] = _vvc
            if _tm.get("slot_tried") and not _tm.get("slot"):
                # (P12b-1) 시도했지만 불합격 — 이 영역에서는 다시 시도하지 않는다
                _sc_t = dict(_gl_store.get("slot_chapters") or {}); _sc_t[chapter] = 1; _gl_store["slot_chapters"] = _sc_t
            if _tm.get("slot") and _bei_ep and not needs_user_decision:
                # (BEI) 페르소나 슬롯은 사례당 1회 — 그 사례에 사용 표시
                _ep_g = next((e for e in _bei.episodes(_gl_store, chapter) if e.get("idx") == _bei_ep.get("idx")
                              and e.get("kind", "episode") == _bei_ep.get("kind", "episode")), None)
                if _ep_g is not None:
                    _ep_g = dict(_ep_g); _ep_g["slot_used"] = True
                    _gl_store = _bei.update_episode(_gl_store, chapter, _ep_g)
                if _tm.get("slot") != "Michael_q":
                    # (2026-11-05 P4-1) 슬롯은 챕터당 1회·세션 5회 — 챕터 표시 + 쓴 문구 인덱스(세션 누적)
                    _sc_g = dict(_gl_store.get("slot_chapters") or {}); _sc_g[chapter] = 1; _gl_store["slot_chapters"] = _sc_g
                    if _tm.get("slot_idx") is not None:
                        _gl_store["slot_used_idx"] = list(_gl_store.get("slot_used_idx") or []) + [int(_tm["slot_idx"])]
                else:
                    _gl_store["michael_q_count"] = int(_gl_store.get("michael_q_count") or 0) + 1
                if _tm.get("slot_text"):             # (P10-2) 세션에서 쓴 슬롯 문장(렌더본) — 되풀이 방지·가드의 고정 문장 집합
                    _gl_store["slot_texts"] = (list(_gl_store.get("slot_texts") or []) + [str(_tm["slot_text"])])[-12:]
            if _tm.get("michael_q_pending") or _tm.get("michael_q_done"):
                # (2026-11-04 P3-2) 응원 턴 → 다음 턴에 실행 의지 질문. 질문을 낸 턴에서 대기 해제.
                _mqp = dict(_gl_store.get("michael_q_pending") or {})
                if _tm.get("michael_q_done"):
                    _mqp.pop(chapter, None)
                else:
                    _mqp[chapter] = 1
                _gl_store["michael_q_pending"] = _mqp
            if "!" in (clean_reply or ""):
                # (2026-11-04 P3-4) 느낌표 챕터 누적(Michael 챕터당 2개 상한)
                _exc = dict(_gl_store.get("excl_by_chapter") or {}); _exc[chapter] = int(_exc.get(chapter, 0) or 0) + (clean_reply or "").count("!")
                _gl_store["excl_by_chapter"] = _exc
        if system_override_text is None and not _llm_error:
            # (2026-10-22 P2-1) 이번 턴 되받기 마무리 어구를 세션 카운터에 누적(최근 60개)
            from diag_project.services.output_guard import lead_tails as _lts_g
            _tcg = dict(_gl_store.get("tail_counts") or {})
            for _t in _lts_g(clean_reply):
                _tcg[_t] = int(_tcg.get(_t, 0) or 0) + 1
            if len(_tcg) > 60:
                _tcg = dict(list(_tcg.items())[-60:])
            _gl_store["tail_counts"] = _tcg
        if _tm.get("opener_frame") is not None and str(_tm.get("opener") or "").startswith(("llm", "bare")) and not needs_user_decision:
            # (2026-11-12 P11-F) 이번 턴에 LLM 이 쓴 여는 문장의 틀 번호를 세션 원장에 적는다(사전 앵커 폴백은 틀을 쓰지 않았으니 적지 않는다)
            _gl_store["opener_frames"] = (list(_gl_store.get("opener_frames") or []) + [int(_tm["opener_frame"])])[-40:]
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
            # 라포·ALIGN·일반 가드: echo 라포 되받기 반복(1 재생성/2 대체) · quote ALIGN 외부 인용 · parrot 동일 응답(1 재생성/2 그대로) ·
            #   one_q 제거한 질문 수 · moment 시점 문형 교정 · anchor 앵커 렌더 모드 · work_q 스몰톡 되물음 삭제 · no_q_fix 정의 턴 질문 고정
            "echo": int(_tm.get("echo") or 0), "quote": int(_tm.get("quote") or 0), "parrot": int(_tm.get("parrot") or 0),
            "align_regen": int(_tm.get("align_regen") or 0), "align_receive_miss": int(_tm.get("align_receive_miss") or 0), "obs_idx": _tm.get("obs_idx"),
            # (2026-11-05 P4) opener 여는 문장 모드(llm/llm_regen/fallback) · slot_idx 슬롯 문구 인덱스 · michael_q_n 실행 의지 누적 · sweep_bridge 다리 유무 ·
            #   broken_cut 흉터 삭제 수 · close_summary_mode 종료 요약(llm/llm_regen/bridge_only) · scope_fallback 정의 턴 범위 문장 폴백 · def_variant 정의 질문 번호
            "opener": _tm.get("opener"), "slot_idx": _tm.get("slot_idx"), "michael_q_n": _tm.get("michael_q_n"), "sweep_bridge": _tm.get("sweep_bridge"),
            "sweep_bridge_regen": int(_tm.get("sweep_bridge_regen") or 0), "broken_cut": int(_tm.get("broken_cut") or 0),
            "close_summary_mode": _tm.get("close_summary_mode"), "close_summary_eps": _tm.get("close_summary_eps"),
            "scope_fallback": int(_tm.get("scope_fallback") or 0), "def_variant": _tm.get("def_variant"),
            "one_q": int(_tm.get("one_q") or 0), "moment": int(_tm.get("moment") or 0), "anchor": _tm.get("anchor_render"),
            "work_q": int(_tm.get("work_q") or 0), "no_q_fix": _tm.get("no_q_fix"),
            "resume": int(_tm.get("resume") or 0),   # (2026-10-22 P1-1) 일시정지 제안 뒤 pending 재개 턴
            # 입버릇·호칭·Michael 리드·느낌표
            "tail": _tm.get("tail"), "tail_fix": int(_tm.get("tail_fix") or 0), "honorific": int(_tm.get("honorific") or 0),
            "good_lead": int(_tm.get("good_lead") or 0), "good_lead_cut": int(_tm.get("good_lead_cut") or 0),
            "good_lead_cap": int(_tm.get("good_lead_cap") or 0), "excl_chapter_cap": int(_tm.get("excl_chapter_cap") or 0),
            # 누설·상태 보고문·낱말 치환·깨진 문장·권유문·입력 이상
            "leak_final": _tm.get("leak_final"), "incident_word": _tm.get("incident_word"), "broken_fix": _tm.get("broken_fix"),
            "suggestion_cut": int(_tm.get("suggestion_cut") or 0), "anomaly": _tm.get("anomaly"),
            # 페르소나 슬롯(사례당 1회)·복원
            "slot": _tm.get("slot"), "slot_restored": int(_tm.get("slot_restored") or 0),
            # (2026-11-04 BEI) 사례 단계: bei 결정(open1/probe/retry/episode/sweep/sweep_followup/close) · episode 사례 번호·종류 · ep_turn 사례 리더 턴 ·
            #   slots_filled 찬 슬롯 수 · slot_judge 판정 상태(ok/stub/error) · closed 종료 사례:사유 · mapped 매핑 라벨 · target 여는/SWEEP 하위역량 ·
            #   anchor_attached 시스템 앵커 삽입 · format_regen 턴 형식 재생성 횟수 · format_miss 미해결 사유 · receive_miss 되받기 없이 나감(폴백 없음)
            "bei": _tm.get("bei"), "episode": (_bei_ep or {}).get("idx"), "ep_kind": (_bei_ep or {}).get("kind"),
            "ep_turn": (_bei_ep or {}).get("leader_turns"), "slots_filled": _tm.get("slots_filled"), "slot_judge": _tm.get("slot_judge"),
            "closed": _tm.get("closed"), "closed_turns": _tm.get("closed_turns"), "mapped": _tm.get("mapped"), "target": current_target_sub,
            "meta_echo": _tm.get("meta_echo"),
            # (2026-11-10 P9) close_side_cut 닫는 쪽 삭제 문장 수 · no_referent 대상 없는 질문 교정(regen/attached) · phrase_cap 입버릇 대체 · register_fix/left 말투 교정/잔존
            "close_side_cut": int(_tm.get("close_side_cut") or 0), "close_side_tail": int(_tm.get("close_side_tail") or 0), "no_referent": _tm.get("no_referent"),
            "phrase_cap": _tm.get("phrase_cap"), "register_fix": int(_tm.get("register_fix") or 0), "register_left": int(_tm.get("register_left") or 0),
            "final_receive": _tm.get("final_receive"), "smalltalk_time": int(_tm.get("smalltalk_time") or 0),
            "case_number": int(_tm.get("case_number") or 0), "request_cut": int(_tm.get("request_cut") or 0),   # (P10) 사례 번호 치환 · 요청형 받는 문장 삭제
            # (2026-11-11 P10) smalltalk 스몰톡 처리(fixed LLM 없음 / llm / llm+reserve / reserve 검사 탈락) · regen_skipped 건너뛴 재생성 수 ·
            #   slot_kind·slot_render 슬롯 종류·렌더 모드 · receive_fallback 받기 폴백(quote 리더 절 인용) · first_bridge 첫 영역 다리 · final_receive_mode
            "smalltalk": _tm.get("smalltalk"), "regen_skipped": int(_tm.get("regen_skipped") or 0), "slot_kind": _tm.get("slot_kind"),
            "slot_text": (str(_tm.get("slot_text"))[:120] if _tm.get("slot") and _tm.get("slot_text") else None),
            "slot_render": _tm.get("slot_render"), "receive_fallback": _tm.get("receive_fallback"), "first_bridge": int(_tm.get("first_bridge") or 0),
            "final_receive_mode": _tm.get("final_receive_mode"),
            "two_q_trim": int(_tm.get("two_q_trim") or 0),   # (지연 단축 b) 두 질문을 재생성 없이 잘랐다
            # (재생성 예산·호출 순서) render_regen 집중 호출의 다시 쓰기 수 · recv_revived 질문 꼴 받기를 평서 꼴로 살린 수 · format_repaired 결정론 수선 사유 ·
            #   close_main_skipped 종료 턴 본 호출 생략 · receive_dropped 받을 낱말 없는 받기 삭제
            "render_regen": int(_tm.get("render_regen") or 0), "recv_revived": int(_tm.get("recv_revived") or 0),
            "format_repaired": _tm.get("format_repaired"), "close_main_skipped": int(_tm.get("close_main_skipped") or 0),
            "receive_dropped": int(_tm.get("receive_dropped") or 0),
            "anchor_attached": int(_tm.get("anchor_attached") or 0), "format_regen": int(_tm.get("format_regen") or 0),
            "format_miss": _tm.get("format_miss"), "receive_miss": int(_tm.get("receive_miss") or 0), "receive_phrase": _tm.get("receive_phrase"),
            # (2026-11-06 P7-1) incident 슬롯 판정의 사례 유무 · stall 연속 무진전 턴 수
            "incident": _tm.get("incident"), "stall": _tm.get("stall"),
            # (2026-11-12 P11) reask 다시 묻기 턴(clarify 되묻기/contentless 내용 없는 답) · recv_ban 받는 문장 금지 꼴 삭제 사유 · recv_trim 받기 1문장으로 줄인 수 ·
            #   q_issues 질문 완결성 위반 · q_complete 처리(repaired/regen/default:슬롯) · announce_cut 예고 문장 · thanks_cut 때 이른 감사 · unsaid_attr 리더가 하지 않은 말 ·
            #   opener_frame 여는 문장 틀 번호 · dup_notice 같은 답 안내 세션 누적 · recv_overlap (받기 어절 중 리더 답 비율, 리더 답 중 되풀이 비율, 받기 어절 수)
            "reask": _tm.get("reask"), "recv_ban": _tm.get("recv_ban"), "recv_trim": int(_tm.get("recv_trim") or 0),
            "q_issues": _tm.get("q_issues"), "q_complete": _tm.get("q_complete"), "announce_cut": int(_tm.get("announce_cut") or 0),
            "thanks_cut": int(_tm.get("thanks_cut") or 0), "unsaid_attr": _tm.get("unsaid_attr"), "opener_frame": _tm.get("opener_frame"),
            "dup_notice": _tm.get("dup_notice"), "recv_overlap": _tm.get("recv_overlap"),
            "open_q_kept": int(_tm.get("open_q_kept") or 0), "request_q": int(_tm.get("request_q") or 0),   # 열린 질문을 남긴 수 · 예고 꼴 질문을 묻는 꼴로
            # (2026-11-12 P11b) regen_why 재생성 사유 목록 · conj_fix ㄹ 탈락 수선 · intro_dup 안내 예고 받기 삭제 · link_cut 연결 문구 · commentary_cut 진행 해설 ·
            #   slot_turn 관찰·응원 슬롯 턴(슬롯+질문) · lead_prefix '리더님께서' 머리 뗌(subject/cap) · recv_cap 되풀이 받기 교체 [비율, 어절] ·
            #   q_clause 한 문장 두 질문에서 남긴 슬롯 · reask_unsaid 다시 묻기에 들어온 말하지 않은 낱말 · sweep_promote 보완 사례 승격(promoted/no_budget) ·
            #   pause_block 휴식 제안을 내지 않은 사유 · lean_start 여는 문장 머리 뗌
            "regen_why": _tm.get("regen_why"), "conj_fix": int(_tm.get("conj_fix") or 0), "intro_dup": int(_tm.get("intro_dup") or 0),
            "link_cut": int(_tm.get("link_cut") or 0), "commentary_cut": int(_tm.get("commentary_cut") or 0), "slot_turn": _tm.get("slot_turn"),
            "lead_prefix": _tm.get("lead_prefix"), "recv_cap": _tm.get("recv_cap"), "q_clause": _tm.get("q_clause"),
            "reask_unsaid": _tm.get("reask_unsaid"), "sweep_promote": _tm.get("sweep_promote"), "pause_block": _tm.get("pause_block"),
            "lean_start": int(_tm.get("lean_start") or 0), "opener_restored": int(_tm.get("opener_restored") or 0), "q_added": _tm.get("q_added"), "slot_ctx": _tm.get("slot_ctx"),
            # (2026-11-12 P11e) repeat_case 이미 닫힌 사례를 다시 말한 답(원래 사례·덧붙인 칸) · dup_close 같은 답 두 번째에 사례 닫음 · reframe_drag 재질문이 끌어온 닫힌 사례의 낱말
            "repeat_case": _tm.get("repeat_case"), "dup_close": int(_tm.get("dup_close") or 0), "reframe_drag": _tm.get("reframe_drag"),
            # (2026-11-13 P12) ask_slot 이번 턴 질문이 향한 것 · q_stand 질문 끝맺음 검사(ending)와 처리(regen·left·no_budget)
            "ask_slot": _tm.get("ask_slot"), "q_stand": _tm.get("q_stand"),
            # (P12b) slot_tried 이 영역의 페르소나 슬롯 시도(1회뿐) · repeat_ask 닫힌 사례를 다시 말한 답 뒤 한 번 더 청함
            "slot_tried": _tm.get("slot_tried"), "repeat_ask": _tm.get("repeat_ask"),
            # (P12c) reask_prev 다시 묻기에 넘긴 직전 질문(q)과 그것이 마지막 코치 턴의 마지막 질문인지(is_last) · align_announce_cut ALIGN 받기의 예고 문장 삭제 수
            "reask_prev": _tm.get("reask_prev"), "align_announce_cut": _tm.get("align_announce_cut"),
            # (P12d) scope_fixed 영역 시작 턴을 LLM 없이 조립 · case_word_cut '이 사례에서' 구절 삭제
            "scope_fixed": _tm.get("scope_fixed"), "case_word_cut": _tm.get("case_word_cut"),
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
        "decision_kind": _decision_kind,        # (P7-3) finish_or_continue = 이어서 하기 / 지금 마치기 선택
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
            # (2026-11-04 BEI) 시뮬 리더(tools/sim_leader.py)·린트가 읽는 사례 단계 메타
            "bei": _tm.get("bei"), "bei_state": (_bei.chapter_state(session.self_assessment_data, chapter) if chapter else None),
            "episode": (_bei_ep or {}).get("idx"), "episode_kind": (_bei_ep or {}).get("kind"), "slots_filled": _tm.get("slots_filled"),
            "target": current_target_sub,
        },
    }


def _get_next_chapter(current_chapter: str) -> str | None:
    """다음 챕터 결정 — chapter_translator 의 단일 소스에 위임.

    (순서 리스트 중복 정의가 next_chapter 어긋남 버그의 온상이라 제거함.)
    """
    return get_next_chapter(current_chapter)


async def _write_episode_event(
    db: AsyncSession,
    session_id: UUID,
    chapter: str,
    ep: dict,
    *,
    events_all: list | None = None,
    messages: list | None = None,
) -> UUID | None:
    """(2026-11-04 BEI) 종료된 사례 1건 → Event 행 1건. situation/action/result = 슬롯 인용(리더 원문), mapped_subcompetency = strong 라벨,
    tags = weak 라벨, summary = 상황 인용 앞 60자. 그 사례 구간의 ChatMessage(turn_index ≥ first_turn_index, 이 챕터)에 event_id 를 태깅해
    이력 압축(conversation_compressor)이 완료 사례를 요약 1줄로 접게 한다. no_case 사례는 행을 만들지 않는다."""
    if (ep or {}).get("status") in ("no_case", "repeat"):
        return None
    slots = ep.get("slots") or {}

    def _q(k: str) -> str | None:
        v = (slots.get(k) or {}).get("quote") or ""
        return v[:500] or None

    labels = ep.get("labels") or []
    strong = [x["sub"] for x in labels if x.get("strength") == "strong"]
    weak = [x["sub"] for x in labels if x.get("strength") != "strong"]
    existing = [e for e in (events_all or []) if e.chapter == chapter]
    ev = await create_event(db=db, session_id=session_id, chapter=chapter, sequence_num=len(existing) + 1, commit=False)
    await update_event_star(db=db, event_id=ev.id, situation=_q("context"), action=_q("action"), result=_q("result"), commit=False)
    _ctx = _q("context") or _q("action") or ""
    await complete_event(db=db, event_id=ev.id, metadata={
        "summary": (f"사례 {ep.get('idx')}: " if ep.get("kind", "episode") == "episode" else "보완: ") + _ctx[:60],
        "core_action": _q("action"), "mapped_subcompetency": ", ".join(strong) or ep.get("opener_sub"), "tags": weak,
    }, commit=False)
    ev.is_complete = ep.get("status") in ("done", "sweep_done") and len(_filled := [k for k in slots if (slots.get(k) or {}).get("status") == "filled"]) >= 6
    ev.probe_count = int(ep.get("leader_turns") or 0)
    db.add(ev)
    if events_all is not None:
        events_all.append(ev)
    _first = ep.get("first_turn_index")
    if _first is not None:
        for m in (messages or []):
            if m.chapter == chapter and (getattr(m, "turn_index", None) or 0) >= int(_first) and getattr(m, "event_id", None) is None:
                m.event_id = ev.id
                db.add(m)
    return ev.id


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
    db: AsyncSession = Depends(get_db), caller: Caller = Depends(get_caller)):
    await assert_can_access_session(caller, session_id, db)
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
    # (2026-11-06 P7-3) 그만하겠다 안내 뒤 선택 대기(새로고침 복원): pending(kind=user_pause)이 남아 있으면 이어서/마치기 버튼
    _decision_kind_state = None
    if (_last_model_msg is not None and _last_model_msg.instruction_used == "USER_REQUESTS_PAUSE" and not _is_completed
            and session.status == "in_progress" and ((session.self_assessment_data or {}).get("pending_instruction") or {}).get("kind") == "user_pause"):
        _needs_user_decision = True
        _decision_kind_state = "finish_or_continue"

    return {
        "session_id": session.id,
        "current_topic": session.current_topic,
        "completed_topics": completed_topics,
        "status": session.status,
        "is_paused": session.status == "paused",
        "is_completed": _is_completed,
        "needs_user_decision": _needs_user_decision,
        "decision_kind": _decision_kind_state,
        "has_next_chapter": _next_chapter is not None,
        "next_topic": _next_topic,
        "messages": formatted_messages
    }