# diag_project/services/indicator.py

import logging
from typing import List, Optional, Tuple
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

# 스키마 임포트
from diag_project.schemas.indicator import IndicatorCreate, IndicatorUpdate
# 모델 임포트
from diag_project.models.competency_indicator import Indicator, Competency

logger = logging.getLogger(__name__)

# --- Indicator (지표) 서비스 ---

async def create_indicator(db: AsyncSession, indicator: IndicatorCreate) -> Indicator:
    # 부모 역량 확인
    competency = await db.get(Competency, indicator.competency_id)
    if not competency:
        raise ValueError(f"Competency with id {indicator.competency_id} not found")

    db_indicator = Indicator.model_validate(indicator)
    try:
        db.add(db_indicator)
        await db.commit()
        await db.refresh(db_indicator)
        return db_indicator
    except IntegrityError as e:
        await db.rollback()
        logger.error(f"Error creating indicator: {e}", exc_info=True)
        raise e

async def get_indicators(db: AsyncSession, skip: int = 0, limit: int = 100) -> Tuple[List[Indicator], int]:
    query = select(Indicator).offset(skip).limit(limit)
    result = await db.execute(query)
    indicators = result.scalars().all()
    
    total_result = await db.execute(select(func.count(Indicator.id)))
    total_count = total_result.scalar_one_or_none() or 0
    
    return indicators, total_count

async def get_indicator(db: AsyncSession, indicator_id: UUID) -> Optional[Indicator]:
    return await db.get(Indicator, indicator_id)

# [THE FIX] 누락되었던 함수 추가
async def get_indicators_by_competency(db: AsyncSession, competency_id: UUID) -> List[Indicator]:
    query = select(Indicator).where(Indicator.competency_id == competency_id)
    result = await db.execute(query)
    return result.scalars().all()

async def update_indicator(db: AsyncSession, indicator_id: UUID, indicator_update: IndicatorUpdate) -> Optional[Indicator]:
    db_indicator = await db.get(Indicator, indicator_id)
    if not db_indicator:
        return None
        
    update_data = indicator_update.model_dump(exclude_unset=True)
    db_indicator.sqlmodel_update(update_data)
    
    try:
        db.add(db_indicator)
        await db.commit()
        await db.refresh(db_indicator)
        return db_indicator
    except Exception as e:
        await db.rollback()
        logger.error(f"Error updating indicator: {e}", exc_info=True)
        raise e

async def delete_indicator(db: AsyncSession, indicator_id: UUID) -> Optional[UUID]:
    db_indicator = await db.get(Indicator, indicator_id)
    if db_indicator:
        await db.delete(db_indicator)
        await db.commit()
        return indicator_id
    return None