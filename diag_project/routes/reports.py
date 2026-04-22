import uuid
import json
import logging
from datetime import datetime
from typing import List, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from pydantic import BaseModel

from diag_project.database import get_db
from diag_project.models.diagnosis_report import DiagnosisReport
from diag_project.models.diagnosis_session import DiagnosisSession, ChatMessage
from diag_project.models.participant import Participant
from diag_project.models.coach_persona import CoachPersona
from diag_project.llm_service import GeminiService

logger = logging.getLogger(__name__)

router = APIRouter(
    tags=["Reports"],
)

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

    existing_query = select(DiagnosisReport).where(DiagnosisReport.session_id == session_uuid)
    result = await db.execute(existing_query)
    existing_report = result.scalars().first()
    
    if existing_report:
        return {"status": "success", "message": "Report already exists", "report_id": str(existing_report.id)}

    user = await db.get(Participant, session.user_id)
    user_name = user.name if user else "리더"

    history_query = select(ChatMessage).where(ChatMessage.session_id == session_uuid).order_by(ChatMessage.created_at.asc())
    history_res = await db.execute(history_query)
    messages = history_res.scalars().all()
    
    formatted_history = [{"role": msg.role, "parts": msg.content} for msg in messages]

    # AI 분석 실행
    analysis_result = await llm.generate_diagnosis_result(history=formatted_history, user_name=user_name)
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