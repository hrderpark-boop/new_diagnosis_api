# diag_project/services/diagnosis_templates.py

import logging
from typing import List, Optional, Tuple
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

from diag_project.schemas.diagnosis_template import DiagnosisTemplateCreate, DiagnosisTemplateUpdate
from diag_project.models.diagnosis_template import DiagnosisTemplate
from diag_project.models.coach import Coach

logger = logging.getLogger(__name__)

async def create_template(db: AsyncSession, template: DiagnosisTemplateCreate) -> DiagnosisTemplate:
    coach = await db.get(Coach, template.coach_id)
    if not coach:
        raise ValueError(f"Coach with id {template.coach_id} not found")

    db_template = DiagnosisTemplate.model_validate(template)
    try:
        db.add(db_template)
        await db.commit()
        await db.refresh(db_template)
        return db_template
    except IntegrityError as e:
        await db.rollback()
        logger.error(f"Error creating template: {e}", exc_info=True)
        raise e

async def get_templates(db: AsyncSession, skip: int = 0, limit: int = 100) -> Tuple[List[DiagnosisTemplate], int]:
    # [THE FIX] scalars().all() 사용 확인
    query = select(DiagnosisTemplate).offset(skip).limit(limit)
    result = await db.execute(query)
    templates = result.scalars().all()

    total_query = select(func.count(DiagnosisTemplate.id))
    total_result = await db.execute(total_query)
    total = total_result.scalar_one_or_none() or 0
    
    return templates, total

async def get_template(db: AsyncSession, template_id: UUID) -> Optional[DiagnosisTemplate]:
    return await db.get(DiagnosisTemplate, template_id)

async def update_template(db: AsyncSession, template_id: UUID, template_update: DiagnosisTemplateUpdate) -> Optional[DiagnosisTemplate]:
    db_template = await db.get(DiagnosisTemplate, template_id)
    if not db_template:
        return None
        
    update_data = template_update.model_dump(exclude_unset=True)
    db_template.sqlmodel_update(update_data)
    
    try:
        db.add(db_template)
        await db.commit()
        await db.refresh(db_template)
        return db_template
    except Exception as e:
        await db.rollback()
        raise e

async def delete_template(db: AsyncSession, template_id: UUID) -> Optional[UUID]:
    db_template = await db.get(DiagnosisTemplate, template_id)
    if db_template:
        await db.delete(db_template)
        await db.commit()
        return template_id
    return None