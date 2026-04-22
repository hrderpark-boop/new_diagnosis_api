# diag_project/services/diagnosis_question.py

import logging
from typing import List, Optional, Tuple
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

# [THE FIX] 스키마는 schemas 패키지에서 가져옵니다.
from diag_project.schemas.diagnosis_question import (
    DiagnosisQuestionCreate, 
    DiagnosisQuestionUpdate
)
from diag_project.models.diagnosis_question import DiagnosisQuestion
from diag_project.models.diagnosis_template import DiagnosisTemplate

logger = logging.getLogger(__name__)

# [THE FIX] 함수 이름 확인 (create_question)
async def create_question(db: AsyncSession, question: DiagnosisQuestionCreate) -> DiagnosisQuestion:
    # 템플릿 존재 확인
    template = await db.get(DiagnosisTemplate, question.diagnosis_template_id)
    if not template:
        raise ValueError(f"Template with id {question.diagnosis_template_id} not found")

    db_question = DiagnosisQuestion.model_validate(question)
    try:
        db.add(db_question)
        await db.commit()
        await db.refresh(db_question)
        return db_question
    except IntegrityError as e:
        await db.rollback()
        logger.error(f"Integrity Error creating question: {e}", exc_info=True)
        raise e

async def get_questions(db: AsyncSession, skip: int = 0, limit: int = 100) -> Tuple[List[DiagnosisQuestion], int]:
    query = select(DiagnosisQuestion).offset(skip).limit(limit)
    result = await db.execute(query)
    questions = result.scalars().all()
    
    total_result = await db.execute(select(func.count(DiagnosisQuestion.id)))
    total_count = total_result.scalar_one_or_none() or 0
    
    return questions, total_count

async def get_question(db: AsyncSession, question_id: UUID) -> Optional[DiagnosisQuestion]:
    return await db.get(DiagnosisQuestion, question_id)

async def get_questions_by_template(db: AsyncSession, template_id: UUID) -> List[DiagnosisQuestion]:
    query = select(DiagnosisQuestion).where(DiagnosisQuestion.diagnosis_template_id == template_id).order_by(DiagnosisQuestion.order)
    result = await db.execute(query)
    return result.scalars().all()

async def update_question(db: AsyncSession, question_id: UUID, question_update: DiagnosisQuestionUpdate) -> Optional[DiagnosisQuestion]:
    db_question = await db.get(DiagnosisQuestion, question_id)
    if not db_question:
        return None
        
    update_data = question_update.model_dump(exclude_unset=True)
    db_question.sqlmodel_update(update_data)
    
    try:
        db.add(db_question)
        await db.commit()
        await db.refresh(db_question)
        return db_question
    except Exception as e:
        await db.rollback()
        raise e

async def delete_question(db: AsyncSession, question_id: UUID) -> Optional[UUID]:
    db_question = await db.get(DiagnosisQuestion, question_id)
    if db_question:
        await db.delete(db_question)
        await db.commit()
        return question_id
    return None