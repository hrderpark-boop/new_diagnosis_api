# diag_project/routes/competency.py

from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Response
from sqlalchemy.ext.asyncio import AsyncSession

from diag_project.database import get_db
from diag_project.services import competency as competency_service
from diag_project.models.competency_indicator import Indicator
from diag_project.schemas.indicator import IndicatorResponse

# [THE FIX] 스키마는 schemas 패키지에서 임포트
from diag_project.schemas.competency import (
    CompetencyCreate, 
    CompetencyUpdate, 
    CompetencyResponse,
    CompetencyListResponse
)

# 모델(DB 테이블)은 models 패키지에서 임포트
# (Competency 모델만 필요함)
# from diag_project.models.competency_indicator import Competency 
# -> 서비스 계층에서 처리하므로 라우터에서는 직접 모델을 import하지 않아도 되는 경우가 많지만, 
#    혹시 필요하다면 아래 주석을 해제하세요. 지금은 스키마만 있으면 됩니다.

router = APIRouter(
    prefix="/api/v1/competencies",
    tags=["Competencies"],
    responses={404: {"description": "Not found"}},
)

@router.post("/", response_model=CompetencyResponse, status_code=status.HTTP_201_CREATED)
async def create_competency(competency: CompetencyCreate, db: AsyncSession = Depends(get_db)):
    return await competency_service.create_competency(db=db, competency=competency)

@router.get("/", response_model=CompetencyListResponse)
async def read_competencies(skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db)):
    competencies, total = await competency_service.get_competencies(db=db, skip=skip, limit=limit)
    return CompetencyListResponse(items=competencies, total=total, skip=skip, limit=limit)

@router.get("/{competency_id}", response_model=CompetencyResponse)
async def read_competency(competency_id: str, db: AsyncSession = Depends(get_db)):
    try:
        uuid_id = UUID(competency_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")
        
    db_competency = await competency_service.get_competency(db=db, competency_id=uuid_id)
    if not db_competency:
        raise HTTPException(status_code=404, detail="Competency not found")
    return db_competency

@router.get("/{competency_id}/indicators/", response_model=List[IndicatorResponse])
async def read_indicators_by_competency(competency_id: str, db: AsyncSession = Depends(get_db)):
    try:
        uuid_id = UUID(competency_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")
        
    # 해당 역량이 존재하는지 확인
    competency = await competency_service.get_competency(db, uuid_id)
    if not competency:
        raise HTTPException(status_code=404, detail="Competency not found")

    # 지표 조회 (Service 함수 호출 권장, 여기서는 직접 구현 예시)
    from sqlalchemy import select
    result = await db.execute(select(Indicator).where(Indicator.competency_id == uuid_id))
    return result.scalars().all()

@router.patch("/{competency_id}", response_model=CompetencyResponse)
async def update_competency(competency_id: str, competency_update: CompetencyUpdate, db: AsyncSession = Depends(get_db)):
    try:
        uuid_id = UUID(competency_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")

    db_competency = await competency_service.update_competency(db=db, competency_id=uuid_id, competency_update=competency_update)
    if not db_competency:
        raise HTTPException(status_code=404, detail="Competency not found")
    return db_competency

@router.delete("/{competency_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_competency(competency_id: str, db: AsyncSession = Depends(get_db)):
    try:
        uuid_id = UUID(competency_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")

    deleted_id = await competency_service.delete_competency(db=db, competency_id=uuid_id)
    if not deleted_id:
        raise HTTPException(status_code=404, detail="Competency not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)