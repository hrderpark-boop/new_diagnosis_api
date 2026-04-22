# diag_project/services/competency.py

import logging
from typing import List, Optional, Tuple
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

# [THE FIX] 스키마는 schemas 패키지에서 가져옵니다.
from diag_project.schemas.competency import CompetencyCreate, CompetencyUpdate
from diag_project.schemas.indicator import IndicatorCreate, IndicatorUpdate

# [THE FIX] DB 모델은 models 패키지에서 가져옵니다.
from diag_project.models.competency_indicator import Competency, Indicator

logger = logging.getLogger(__name__)

# --- Competency (역량) 서비스 ---

async def create_competency(db: AsyncSession, competency: CompetencyCreate) -> Competency:
    db_competency = Competency.model_validate(competency)
    try:
        db.add(db_competency)
        await db.commit()
        await db.refresh(db_competency)
        return db_competency
    except IntegrityError as e:
        await db.rollback()
        logger.error(f"Error creating competency: {e}", exc_info=True)
        raise e

async def get_competencies(db: AsyncSession, skip: int = 0, limit: int = 100) -> Tuple[List[Competency], int]:
    query = select(Competency).offset(skip).limit(limit)
    result = await db.execute(query)
    competencies = result.scalars().all()
    
    total_result = await db.execute(select(func.count(Competency.id)))
    total_count = total_result.scalar_one_or_none() or 0
    
    return competencies, total_count

async def get_competency(db: AsyncSession, competency_id: UUID) -> Optional[Competency]:
    return await db.get(Competency, competency_id)

async def update_competency(db: AsyncSession, competency_id: UUID, competency_update: CompetencyUpdate) -> Optional[Competency]:
    db_competency = await db.get(Competency, competency_id)
    if not db_competency:
        return None
        
    update_data = competency_update.model_dump(exclude_unset=True)
    db_competency.sqlmodel_update(update_data)
    
    try:
        db.add(db_competency)
        await db.commit()
        await db.refresh(db_competency)
        return db_competency
    except Exception as e:
        await db.rollback()
        raise e

async def delete_competency(db: AsyncSession, competency_id: UUID) -> Optional[UUID]:
    db_competency = await db.get(Competency, competency_id)
    if db_competency:
        await db.delete(db_competency)
        await db.commit()
        return competency_id
    return None

# --- Indicator 관련 서비스 함수가 필요하다면 여기에 추가 ---
# (현재는 indicator.py 서비스 파일이 따로 없으므로 여기에 포함될 수도 있고 분리될 수도 있음)