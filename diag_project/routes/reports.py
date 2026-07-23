import copy
import uuid
import json
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from pydantic import BaseModel

from diag_project.database import get_db
from diag_project.models.diagnosis_report import DiagnosisReport
from diag_project.models.diagnosis_session import DiagnosisSession, ChatMessage
from diag_project.models.participant import Participant
from diag_project.models.coach_persona import CoachPersona
from diag_project.models.event import Event
from diag_project.data.competencies import COMPETENCY_FRAMEWORK
from diag_project.llm_service import GeminiService
from diag_project.services.auth import AdminContext, get_current_admin

logger = logging.getLogger(__name__)


def _build_chapter_transcripts(
    messages: list, events: list
) -> Dict[str, str]:
    """역량(챕터)별로 대화·사건을 결정론적으로 분리 (Map-Reduce 의 Map 입력).

    - ChatMessage.chapter 가 None 인 메시지(라포·INTRO 등 첫 START_CHAPTER
      이전 사담)는 자동 제외 → 채점 노이즈 차단.
    - LLM 분류(환각 위험) 대신, DB 의 chapter 태그로 100% 정확히 필터링.
    - 각 챕터에 수집된 Event(STAR·mapped_subcompetency)도 함께 묶어 근거 강화.
    """
    transcripts: Dict[str, str] = {}
    for key in COMPETENCY_FRAMEWORK.keys():
        if key == "supplementary":
            continue
        chap_msgs = [m for m in messages if getattr(m, "chapter", None) == key]
        lines = [
            f"{'리더' if m.role == 'user' else '코치'}: {m.content}"
            for m in chap_msgs
            if m.content
        ]

        chap_events = [e for e in events if getattr(e, "chapter", None) == key]
        ev_lines = []
        for e in chap_events:
            parts = []
            if e.mapped_subcompetency:
                parts.append(f"하위역량={e.mapped_subcompetency}")
            if e.summary:
                parts.append(f"요약={e.summary}")
            if e.core_action:
                parts.append(f"핵심행동={e.core_action}")
            if e.result:
                parts.append(f"결과={e.result}")
            if parts:
                ev_lines.append("  - " + " | ".join(parts))

        body = "\n".join(lines)
        if ev_lines:
            body += "\n\n[수집된 핵심 사건]\n" + "\n".join(ev_lines)
        transcripts[key] = body.strip() or "이 영역에 대한 대화 기록이 없습니다."
    return transcripts

router = APIRouter(
    tags=["Reports"],
)


# ==========================================================================
# Human-in-the-Loop: 관리자 교정 스키마
# ==========================================================================
class ReasoningStepEdit(BaseModel):
    """STAR 단계별 교정. description 만 수정 대상이며,
    evidence(원문 발췌)는 '리더의 실제 발화'이므로 교정 대상에서 제외한다."""
    description: Optional[str] = None


class CompetencyEdit(BaseModel):
    comment: Optional[str] = None            # 코치 피드백
    strength_point: Optional[str] = None
    growth_point: Optional[str] = None
    gap_analysis: Optional[str] = None
    # 키: "1_situation" | "2_action" | "3_result"
    reasoning_process: Optional[Dict[str, ReasoningStepEdit]] = None


class ReportUpdateRequest(BaseModel):
    """부분 갱신(PATCH 시맨틱)을 따른다.

    None 인 필드는 '변경 없음'으로 간주하고 기존 값을 유지한다.
    전체 치환이 아니므로 관리자가 특정 문단만 고쳐도 나머지가 날아가지 않는다.
    """
    summary: Optional[str] = None
    blind_spot: Optional[str] = None
    details: Optional[Dict[str, CompetencyEdit]] = None


# --------------------------------------------------------------------------
# [신규] 관리자용 전체 리포트 목록 조회 (GET /)
# --------------------------------------------------------------------------
@router.get("/")
async def get_all_reports(db: AsyncSession = Depends(get_db)):
    # 1. 전체 리포트 최신순 조회
    report_query = select(DiagnosisReport).order_by(DiagnosisReport.created_at.desc())
    report_res = await db.execute(report_query)
    reports = report_res.scalars().all()

    # 2. 매핑을 위한 사용자 정보 전체 조회
    user_query = select(Participant)
    user_res = await db.execute(user_query)
    users = {str(u.id): u.name for u in user_res.scalars().all()}

    response_data = []
    for r in reports:
        response_data.append({
            "id": str(r.id),
            "session_id": str(r.session_id),
            "user_name": users.get(str(r.user_id), "알 수 없음"),
            "total_score": round(r.total_score, 2),
            "summary": r.summary,
            "created_at": r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else ""
        })
    return response_data

# --------------------------------------------------------------------------
# [1] 개별 결과 조회 (GET /{session_id}) - 프론트엔드 호출용
# --------------------------------------------------------------------------
@router.get("/{session_id}")
async def get_report(session_id: str, db: AsyncSession = Depends(get_db)):
    try:
        target_uuid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")

    query = select(DiagnosisReport).where(DiagnosisReport.session_id == target_uuid)
    result = await db.execute(query)
    report = result.scalars().first()

    if not report:
        raise HTTPException(status_code=404, detail="Report not ready (Analyzing...)")

    coach_name = "AI Coach"
    user_name = "Leader"
    
    session_res = await db.get(DiagnosisSession, target_uuid)
    if session_res:
        user = await db.get(Participant, session_res.user_id)
        if user: user_name = user.name
        if session_res.coach_id:
            persona_res = await db.execute(select(CoachPersona).where(CoachPersona.coach_id == session_res.coach_id))
            persona = persona_res.scalars().first()
            if persona: coach_name = persona.name
            
    # 🚨 프론트엔드가 요구하는 새로운 JSON 포맷을 그대로 살려서 반환
    saved_scores = report.scores or {}
    return {
        "user_name": user_name,
        "coach_name": coach_name,
        "total_score": report.total_score,
        "summary": report.summary,
        "radar_chart": saved_scores.get("radar_chart", saved_scores),
        "details": saved_scores.get("details", {}),
        "top_keywords": saved_scores.get("top_keywords", []),
        "created_at": report.created_at.strftime("%Y-%m-%d") if report.created_at else datetime.now().strftime("%Y-%m-%d")
    }

# --------------------------------------------------------------------------
# [1-b] 관리자 교정 (PUT /{report_id}) — Human-in-the-Loop
# --------------------------------------------------------------------------
def _apply_competency_edit(target: Dict[str, Any], edit: CompetencyEdit) -> List[str]:
    """단일 역량 블록에 교정 내용을 적용하고, 변경된 필드명을 반환한다."""
    changed: List[str] = []

    for field in ("comment", "strength_point", "growth_point", "gap_analysis"):
        value = getattr(edit, field)
        if value is None:
            continue
        new_value = value.strip()
        if target.get(field) != new_value:
            target[field] = new_value
            changed.append(field)

    if edit.reasoning_process:
        rp = target.setdefault("reasoning_process", {})
        for step_key, step_edit in edit.reasoning_process.items():
            if step_key not in ("1_situation", "2_action", "3_result"):
                raise HTTPException(
                    status_code=400,
                    detail=f"알 수 없는 STAR 단계입니다: {step_key}",
                )
            if step_edit.description is None:
                continue
            # 구버전 리포트는 이 값이 문자열일 수 있다 → 객체로 승격
            step = rp.get(step_key)
            if not isinstance(step, dict):
                step = {"description": step or "", "evidence": []}
            new_desc = step_edit.description.strip()
            if step.get("description") != new_desc:
                step["description"] = new_desc
                changed.append(f"reasoning_process.{step_key}")
            rp[step_key] = step

    return changed


@router.put("/{report_id}")
async def update_report(
    report_id: str,
    body: ReportUpdateRequest,
    ctx: AdminContext = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """관리자가 교정한 AI 피드백을 DB 에 덮어쓴다 (골든 데이터셋 구축).

    - 관리자 인증 필수. Client Admin 은 자사 소속 대상자의 리포트만 교정 가능.
    - 최초 교정 시 AI 원본(scores)을 ai_original 에 스냅샷으로 보존한다.
      학습 데이터는 (AI 원본 → 사람 교정본) 쌍에서 나오므로, 원본 없이
      덮어쓰기만 하면 데이터셋으로서의 가치가 사라진다.
    - is_human_edited 를 True 로 올려 '사람이 검수·확정한 샘플'을 식별한다.
    """
    try:
        target_uuid = uuid.UUID(report_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")

    report = (
        await db.execute(select(DiagnosisReport).where(DiagnosisReport.id == target_uuid))
    ).scalars().first()
    if not report:
        raise HTTPException(status_code=404, detail="리포트를 찾을 수 없습니다.")

    # 회사 격리: 리포트에는 company 컬럼이 없으므로 대상자를 통해 확인한다.
    participant = await db.get(Participant, report.user_id)
    ctx.assert_can_access_company(participant.company_id if participant else None)

    # SQLAlchemy 는 JSON 컬럼 '내부' 변경을 자동 감지하지 못한다.
    # 깊은 복사본을 수정한 뒤 통째로 재할당해야 UPDATE 가 발생한다.
    scores: Dict[str, Any] = copy.deepcopy(report.scores or {})
    details: Dict[str, Any] = scores.setdefault("details", {})
    changed_fields: List[str] = []

    if body.details:
        for comp_key, edit in body.details.items():
            if comp_key not in details:
                raise HTTPException(
                    status_code=400,
                    detail=f"리포트에 존재하지 않는 역량입니다: {comp_key}",
                )
            block = details[comp_key]
            if not isinstance(block, dict):
                raise HTTPException(
                    status_code=400,
                    detail=f"교정할 수 없는 역량 데이터 구조입니다: {comp_key}",
                )
            for field in _apply_competency_edit(block, edit):
                changed_fields.append(f"details.{comp_key}.{field}")

    if body.blind_spot is not None:
        new_blind = body.blind_spot.strip()
        if scores.get("blind_spot") != new_blind:
            scores["blind_spot"] = new_blind
            changed_fields.append("blind_spot")

    new_summary = report.summary
    if body.summary is not None:
        new_summary = body.summary.strip()
        if new_summary != report.summary:
            changed_fields.append("summary")

    if not changed_fields:
        return {
            "success": True,
            "message": "변경된 내용이 없습니다.",
            "is_human_edited": report.is_human_edited,
            "changed_fields": [],
        }

    # 최초 교정에 한해 AI 원본 스냅샷 보존 (이후 교정에서는 덮어쓰지 않는다)
    if not report.is_human_edited and report.ai_original is None:
        report.ai_original = {
            "scores": copy.deepcopy(report.scores or {}),
            "summary": report.summary,
            "snapshot_at": datetime.now().isoformat(),
        }

    report.scores = scores
    report.summary = new_summary
    report.is_human_edited = True
    report.edited_at = datetime.now()
    report.edited_by = ctx.admin.email

    db.add(report)
    await db.commit()
    await db.refresh(report)

    logger.info(
        "리포트 교정: report_id=%s, by=%s, fields=%s",
        report_id, ctx.admin.email, changed_fields,
    )

    return {
        "success": True,
        "message": "교정 내용이 저장되었습니다.",
        "is_human_edited": report.is_human_edited,
        "edited_at": report.edited_at,
        "edited_by": report.edited_by,
        "changed_fields": changed_fields,
    }


# --------------------------------------------------------------------------
# [2] 결과 분석 요청 (POST) - 진단 종료 시 호출
# --------------------------------------------------------------------------
@router.post("/{session_id}/analyze", status_code=status.HTTP_201_CREATED)
async def analyze_session(
    session_id: str, 
    db: AsyncSession = Depends(get_db),
    llm: GeminiService = Depends(GeminiService)
):
    logger.info(f"🧠 리포트 분석 요청: {session_id}")
    
    try:
        session_uuid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")

    session = await db.get(DiagnosisSession, session_uuid)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # 기존 리포트가 있으면 스킵하지 않고 삭제 → 무조건 처음부터 재분석(Overwrite).
    existing_query = select(DiagnosisReport).where(DiagnosisReport.session_id == session_uuid)
    result = await db.execute(existing_query)
    existing_reports = result.scalars().all()
    if existing_reports:
        for _r in existing_reports:
            await db.delete(_r)
        await db.commit()
        logger.info(
            f"♻️ 기존 리포트 {len(existing_reports)}건 삭제 → 강제 재생성: {session_id}"
        )

    user = await db.get(Participant, session.user_id)
    user_name = user.name if user else "리더"

    history_query = select(ChatMessage).where(ChatMessage.session_id == session_uuid).order_by(ChatMessage.created_at.asc())
    history_res = await db.execute(history_query)
    messages = history_res.scalars().all()

    events_res = await db.execute(
        select(Event).where(Event.session_id == session_uuid).order_by(Event.sequence_num.asc())
    )
    events = events_res.scalars().all()

    formatted_history = [{"role": msg.role, "parts": msg.content} for msg in messages]

    # Map-Reduce: 역량별로 대화·사건을 결정론적으로 분리해 주입.
    #  - 통짜 컨텍스트 주입(절단/날조) 방지, 라포 사담(chapter=None) 제외.
    chapter_transcripts = _build_chapter_transcripts(messages, events)

    # AI 분석 실행 (chapter_transcripts 제공 시 챕터별 Map 호출 → Reduce)
    analysis_result = await llm.generate_diagnosis_result(
        history=formatted_history,
        user_name=user_name,
        chapter_transcripts=chapter_transcripts,
    )
    if not analysis_result:
        raise HTTPException(status_code=500, detail="AI 분석 결과를 생성하지 못했습니다.")

    # 🚨 [수정] 새로운 LLM JSON 구조에 맞춰 안전하게 점수 파싱
    total_score = analysis_result.get("total_score", 0.0)
    radar_chart = analysis_result.get("radar_chart", {})
    if not total_score and radar_chart:
        total_score = sum(radar_chart.values()) / len(radar_chart)

    # 🚨 [수정] DB 스키마 충돌 방지를 위해 전체 JSON을 scores에 캡슐화하여 저장
    new_report = DiagnosisReport(
        id=uuid.uuid4(),
        session_id=session_uuid,
        user_id=session.user_id,
        coach_id=session.coach_id,
        summary=analysis_result.get("feedback_summary", "종합 피드백이 생성되지 않았습니다."),
        scores=analysis_result, # 모든 디테일(reasoning) 보존
        total_score=total_score,
        top_competency="-",
        bottom_competency="-",
        feedback="-",
        recommended_action="-",
        created_at=datetime.now()
    )
    
    db.add(new_report)
    session.status = "completed"
    session.current_topic = "Completed"
    db.add(session)
    await db.commit()
    
    logger.info(f"✅ 리포트 생성 완료: {new_report.id}")
    return {"status": "success", "message": "Analysis completed", "report_id": str(new_report.id)}