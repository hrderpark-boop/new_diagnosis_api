# diag_project/services/message.py

import logging
from typing import List
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

# [THE FIX] 스키마는 schemas 패키지에서 가져옵니다.
from diag_project.schemas.message import MessageCreate
# [THE FIX] DB 모델은 models 패키지에서 가져옵니다.
from diag_project.models.message import Message

logger = logging.getLogger(__name__)

async def create_message(db: AsyncSession, message: MessageCreate) -> Message:
    """
    새로운 메시지를 생성합니다.
    """
    # Pydantic 모델 -> DB 모델 변환
    db_message = Message.model_validate(message)
    
    try:
        db.add(db_message)
        await db.commit()
        await db.refresh(db_message)
        return db_message
    except IntegrityError as e:
        await db.rollback()
        logger.error(f"Error creating message: {e}", exc_info=True)
        raise e

async def get_messages_by_session(db: AsyncSession, session_id: UUID) -> List[Message]:
    """
    특정 세션의 모든 메시지를 생성 시간 순으로 조회합니다.
    """
    query = select(Message).where(Message.session_id == session_id).order_by(Message.created_at.asc())
    result = await db.execute(query)
    return result.scalars().all()