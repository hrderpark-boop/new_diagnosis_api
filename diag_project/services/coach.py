import logging
from typing import List, Optional, Tuple
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

# [THE FIX] 스키마는 schemas 패키지에서 가져옵니다.
from diag_project.schemas.coach import CoachCreate, CoachUpdate
# [THE FIX] DB 모델은 models 패키지에서 가져옵니다.
from diag_project.models.coach import Coach
from diag_project.models.participant import Participant

logger = logging.getLogger(__name__)

async def create_coach(db: AsyncSession, coach: CoachCreate) -> Coach:
    # 사용자(Participant) 존재 확인
    user = await db.get(Participant, coach.user_id)
    if not user:
        raise ValueError(f"User with id {coach.user_id} not found")

    db_coach = Coach.model_validate(coach)
    try:
        db.add(db_coach)
        await db.commit()
        await db.refresh(db_coach)
        return db_coach
    except IntegrityError as e:
        await db.rollback()
        logger.error(f"Error creating coach: {e}", exc_info=True)
        raise e

async def get_coaches(db: AsyncSession, skip: int = 0, limit: int = 100) -> Tuple[List[Coach], int]:
    query = select(Coach).offset(skip).limit(limit)
    result = await db.execute(query)
    coaches = result.scalars().all()
    
    total_result = await db.execute(select(func.count(Coach.id)))
    total_count = total_result.scalar_one_or_none() or 0
    
    return coaches, total_count

async def get_coach(db: AsyncSession, coach_id: UUID) -> Optional[Coach]:
    return await db.get(Coach, coach_id)

async def update_coach(db: AsyncSession, coach_id: UUID, coach_update: CoachUpdate) -> Optional[Coach]:
    db_coach = await db.get(Coach, coach_id)
    if not db_coach:
        return None
        
    update_data = coach_update.model_dump(exclude_unset=True)
    db_coach.sqlmodel_update(update_data)
    
    try:
        db.add(db_coach)
        await db.commit()
        await db.refresh(db_coach)
        return db_coach
    except Exception as e:
        await db.rollback()
        raise e

async def delete_coach(db: AsyncSession, coach_id: UUID) -> Optional[UUID]:
    db_coach = await db.get(Coach, coach_id)
    if db_coach:
        await db.delete(db_coach)
        await db.commit()
        return coach_id
    return None