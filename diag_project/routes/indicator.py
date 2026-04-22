#diag_project/routes/indicator.py

from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from diag_project.database import get_db
# [THE FIX] schemas에서 임포트
from diag_project.schemas.indicator import (
    IndicatorCreate, 
    IndicatorUpdate, 
    IndicatorResponse
)
# 모델 임포트
from diag_project.models.competency_indicator import Indicator, Competency

router = APIRouter(
    prefix="/api/v1/indicators",
    tags=["Indicators"],
    responses={404: {"description": "Not found"}},
)

@router.post("/", response_model=IndicatorResponse, status_code=status.HTTP_201_CREATED)
async def create_indicator(indicator: IndicatorCreate, db: AsyncSession = Depends(get_db)):
    # 부모 역량 확인
    competency = await db.get(Competency, indicator.competency_id)
    if not competency:
        raise HTTPException(status_code=404, detail="Competency not found")

    # DB 모델로 변환
    db_indicator = Indicator.model_validate(indicator)
    
    db.add(db_indicator)
    await db.commit()
    await db.refresh(db_indicator)
    return db_indicator

@router.get("/", response_model=List[IndicatorResponse])
async def read_indicators(skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Indicator).offset(skip).limit(limit))
    return result.scalars().all()

@router.get("/{indicator_id}", response_model=IndicatorResponse)
async def read_indicator(indicator_id: str, db: AsyncSession = Depends(get_db)):
    try:
        uuid_id = UUID(indicator_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")
        
    db_indicator = await db.get(Indicator, uuid_id)
    if not db_indicator:
        raise HTTPException(status_code=404, detail="Indicator not found")
    return db_indicator

@router.patch("/{indicator_id}", response_model=IndicatorResponse)
async def update_indicator(indicator_id: str, indicator_update: IndicatorUpdate, db: AsyncSession = Depends(get_db)):
    try:
        uuid_id = UUID(indicator_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")

    db_indicator = await db.get(Indicator, uuid_id)
    if not db_indicator:
        raise HTTPException(status_code=404, detail="Indicator not found")

    update_data = indicator_update.model_dump(exclude_unset=True)
    db_indicator.sqlmodel_update(update_data)

    db.add(db_indicator)
    await db.commit()
    await db.refresh(db_indicator)
    return db_indicator

@router.delete("/{indicator_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_indicator(indicator_id: str, db: AsyncSession = Depends(get_db)):
    try:
        uuid_id = UUID(indicator_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")

    db_indicator = await db.get(Indicator, uuid_id)
    if not db_indicator:
        raise HTTPException(status_code=404, detail="Indicator not found")

    await db.delete(db_indicator)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)