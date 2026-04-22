# diag_project/services/coach_persona.py

import logging
from typing import List, Optional, Tuple
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

# [THE FIX] 스키마는 schemas 패키지에서 가져옵니다.
from diag_project.schemas.coach_persona import CoachPersonaCreate, CoachPersonaUpdate
# [THE FIX] DB 모델은 models 패키지에서 가져옵니다.
from diag_project.models.coach_persona import CoachPersona
from diag_project.models.coach import Coach

logger = logging.getLogger(__name__)

async def create_persona(db: AsyncSession, persona: CoachPersonaCreate) -> CoachPersona:
    # 코치 존재 확인
    coach = await db.get(Coach, persona.coach_id)
    if not coach:
        raise ValueError(f"Coach with id {persona.coach_id} not found")

    db_persona = CoachPersona.model_validate(persona)
    try:
        db.add(db_persona)
        await db.commit()
        await db.refresh(db_persona)
        return db_persona
    except IntegrityError as e:
        await db.rollback()
        logger.error(f"Error creating persona: {e}", exc_info=True)
        raise e

async def get_personas(db: AsyncSession, skip: int = 0, limit: int = 100) -> Tuple[List[CoachPersona], int]:
    query = select(CoachPersona).offset(skip).limit(limit)
    result = await db.execute(query)
    personas = result.scalars().all()
    
    total_result = await db.execute(select(func.count(CoachPersona.id)))
    total_count = total_result.scalar_one_or_none() or 0
    
    return personas, total_count

async def get_persona(db: AsyncSession, persona_id: UUID) -> Optional[CoachPersona]:
    return await db.get(CoachPersona, persona_id)

async def update_persona(db: AsyncSession, persona_id: UUID, persona_update: CoachPersonaUpdate) -> Optional[CoachPersona]:
    db_persona = await db.get(CoachPersona, persona_id)
    if not db_persona:
        return None
        
    update_data = persona_update.model_dump(exclude_unset=True)
    db_persona.sqlmodel_update(update_data)
    
    try:
        db.add(db_persona)
        await db.commit()
        await db.refresh(db_persona)
        return db_persona
    except Exception as e:
        await db.rollback()
        raise e

async def delete_persona(db: AsyncSession, persona_id: UUID) -> Optional[UUID]:
    db_persona = await db.get(CoachPersona, persona_id)
    if db_persona:
        await db.delete(db_persona)
        await db.commit()
        return persona_id
    return None