# diag_project/routes/admin.py

import io
import pandas as pd
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from diag_project.database import get_db
from diag_project.models.participant import Participant
from diag_project.models.diagnosis_session import DiagnosisSession

router = APIRouter(
    prefix="/admin",
    tags=["Admin Dashboard"],
)

# 1. [View] 전체 참여자 및 진단 현황 조회 (JSON)
@router.get("/participants")
async def get_all_participants(db: AsyncSession = Depends(get_db)):
    # 참여자와 그들의 세션 정보를 함께 가져옴
    query = select(Participant).options(selectinload(Participant.sessions))
    result = await db.execute(query)
    participants = result.scalars().all()

    data = []
    for p in participants:
        # 가장 최근 세션 상태 확인
        last_session = p.sessions[-1] if p.sessions else None
        status = last_session.status if last_session else "No Session"
        
        data.append({
            "id": str(p.id),
            "name": p.name,
            "email": p.email,
            # [수정] 모델에 없는 organization 대신 group_code 사용
            "group_code": p.group_code if p.group_code else "-",
            "gender": p.gender if p.gender else "-",
            "age_group": p.age_group if p.age_group else "-",
            "total_sessions": len(p.sessions),
            "last_status": status,
            "joined_at": p.created_at
        })
    
    return data

# 2. [Export] 진단 데이터 엑셀 다운로드
@router.get("/export_excel")
async def export_diagnosis_data(db: AsyncSession = Depends(get_db)):
    # 1) DB에서 필요한 데이터 조회 (참여자 + 세션 + 코치정보 등)
    query = select(DiagnosisSession).options(
        selectinload(DiagnosisSession.user)
    ).order_by(DiagnosisSession.created_at.desc())
    
    result = await db.execute(query)
    sessions = result.scalars().all()

    # 2) 데이터프레임 생성을 위한 리스트 변환
    export_list = []
    for s in sessions:
        user = s.user
        export_list.append({
            "Session ID": str(s.id),
            "Date": s.created_at.strftime("%Y-%m-%d %H:%M"),
            "User Name": user.name if user else "Unknown",
            "Email": user.email if user else "-",
            "Group Code": user.group_code if user and user.group_code else "-",
            "Coach ID": str(s.coach_id),
            "Status": s.status,
        })

    # 3) Pandas DataFrame 생성
    df = pd.DataFrame(export_list)

    # 4) 엑셀 파일로 변환 (메모리 상에서 처리)
    stream = io.BytesIO()
    with pd.ExcelWriter(stream, engine='openpyxl') as writer:
        df.to_excel(writer, index=False, sheet_name='Diagnosis_Logs')
    
    stream.seek(0)

    # 5) 파일 다운로드 응답 반환
    filename = f"diagnosis_export_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )