# diag_project/services/question_choice.py (수정 반영)

import logging
from typing import List, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlmodel import delete
from sqlalchemy.exc import IntegrityError

from diag_project.models.question_choice import (
    QuestionChoice,
    QuestionChoiceCreate,
    QuestionChoiceUpdate
)

logger = logging.getLogger(__name__)

# --- QuestionChoice (문항 선택지) 서비스 ---

async def create_choice(db: AsyncSession, choice: QuestionChoiceCreate) -> QuestionChoice:
    db_choice = QuestionChoice.model_validate(choice)
    try:
        db.add(db_choice)
        await db.commit()
        await db.refresh(db_choice)
        return db_choice
    except IntegrityError as e:
        await db.rollback()
        logger.error(f"Integrity Error creating choice: {e}", exc_info=True)
        raise e

async def get_choices_by_question(db: AsyncSession, question_id: UUID, skip: int = 0, limit: int = 100) -> List[QuestionChoice]:
    result = await db.execute(
        select(QuestionChoice)
        .where(QuestionChoice.diagnosis_question_id == str(question_id)) # 👈 str() 변환 추가
        .offset(skip)
        .limit(limit)
    )
    return result.scalars().all()

async def get_all_choices(db: AsyncSession, skip: int = 0, limit: int = 100) -> List[QuestionChoice]:
    """(참고용) 모든 선택지 조회"""
    result = await db.execute(select(QuestionChoice).offset(skip).limit(limit))
    return result.scalars().all()

async def get_choice(db: AsyncSession, choice_id: UUID) -> Optional[QuestionChoice]:
    return await db.get(QuestionChoice, choice_id)

async def update_choice(db: AsyncSession, choice_id: UUID, choice_update: QuestionChoiceUpdate) -> Optional[QuestionChoice]:
    db_choice = await db.get(QuestionChoice, choice_id)
    if not db_choice:
        return None
        
    update_data = choice_update.model_dump(exclude_unset=True)
    db_choice.sqlmodel_update(update_data)
    
    try:
        db.add(db_choice)
        await db.commit()
        await db.refresh(db_choice)
        return db_choice
    except IntegrityError as e:
        await db.rollback()
        raise e

async def delete_choice(db: AsyncSession, choice_id: UUID) -> Optional[UUID]:
    db_choice = await db.get(QuestionChoice, choice_id)
    if db_choice:
        await db.delete(db_choice)
        await db.commit()
        return choice_id
    return None