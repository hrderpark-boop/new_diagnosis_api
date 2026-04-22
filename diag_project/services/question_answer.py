# diag_project/services/question_answer.py

import logging
from typing import List, Optional
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlmodel import delete
from sqlalchemy.exc import IntegrityError

# ⚠️ (핵심 수정) 잘못된 'Question', 'Answer' 임포트를 제거하고
# 'QuestionAnswer' 관련 모델을 임포트합니다.
from diag_project.models.question_answer import (
    QuestionAnswer,
    QuestionAnswerCreate,
    QuestionAnswerUpdate
)

logger = logging.getLogger(__name__)

async def create_question_answer(db: AsyncSession, answer: QuestionAnswerCreate) -> QuestionAnswer:
    """
    QuestionAnswer 레코드를 생성합니다.
    """
    db_answer = QuestionAnswer.model_validate(answer)
    try:
        db.add(db_answer)
        await db.commit()
        await db.refresh(db_answer)
        return db_answer
    except IntegrityError as e:
        await db.rollback()
        logger.error(f"Integrity Error creating question answer: {e}", exc_info=True)
        raise e

async def get_question_answer(db: AsyncSession, answer_id: UUID) -> Optional[QuestionAnswer]:
    """ ID로 특정 QuestionAnswer를 조회합니다. """
    return await db.get(QuestionAnswer, answer_id)

async def get_question_answers_by_session(db: AsyncSession, session_id: UUID) -> List[QuestionAnswer]:
    """ 특정 세션의 모든 QuestionAnswer를 조회합니다. """
    result = await db.execute(
        select(QuestionAnswer).where(QuestionAnswer.session_id == str(session_id))
    )
    return result.scalars().all()

async def update_question_answer(
    db: AsyncSession, answer_id: UUID, answer_update: QuestionAnswerUpdate
) -> Optional[QuestionAnswer]:
    """ ID로 특정 QuestionAnswer를 업데이트합니다. """
    db_answer = await db.get(QuestionAnswer, answer_id)
    if not db_answer:
        return None
        
    update_data = answer_update.model_dump(exclude_unset=True)
    db_answer.sqlmodel_update(update_data)
    
    try:
        db.add(db_answer)
        await db.commit()
        await db.refresh(db_answer)
        return db_answer
    except IntegrityError as e:
        await db.rollback()
        raise e

async def delete_question_answer(db: AsyncSession, answer_id: UUID) -> Optional[UUID]:
    """ ID로 특정 QuestionAnswer를 삭제합니다. """
    db_answer = await db.get(QuestionAnswer, answer_id)
    if db_answer:
        await db.delete(db_answer)
        await db.commit()
        return answer_id
    return None