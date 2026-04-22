# diag_project/services/participant_answer.py (제박사 최종 수정본)

import logging
from typing import List
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

# [THE FIX] 스키마는 schemas 패키지에서 가져옵니다.
from diag_project.schemas.participant_answer import (
    ParticipantAnswerCreate, 
    ParticipantAnswerResponse
)
# [THE FIX] DB 모델은 models 패키지에서 가져옵니다.
from diag_project.models.participant_answer import ParticipantAnswer

logger = logging.getLogger(__name__)

async def create_answer(db: AsyncSession, answer: ParticipantAnswerCreate) -> ParticipantAnswer:
    db_answer = ParticipantAnswer.model_validate(answer)
    try:
        db.add(db_answer)
        await db.commit()
        await db.refresh(db_answer)
        return db_answer
    except IntegrityError as e:
        await db.rollback()
        logger.error(f"Error creating participant answer: {e}", exc_info=True)
        raise e

async def get_answers_by_session(db: AsyncSession, session_id: UUID) -> List[ParticipantAnswer]:
    query = select(ParticipantAnswer).where(ParticipantAnswer.session_id == session_id)
    result = await db.execute(query)
    return result.scalars().all()