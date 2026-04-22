# diag_project/services/session.py

import logging
from typing import List, Optional, Tuple
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from datetime import datetime, timezone

# [THE FIX] 스키마는 schemas 패키지에서 가져옵니다.
from diag_project.schemas.session import SessionCreate, SessionUpdate
# [THE FIX] DB 모델은 models 패키지에서 가져옵니다.
from diag_project.models.session import Session, SessionStatus

logger = logging.getLogger(__name__)

# --- Session (진단 세션) 서비스 ---

async def create_session(db: AsyncSession, session: SessionCreate) -> Session:
    # Pydantic -> DB 모델 변환
    db_session = Session.model_validate(session)
    try:
        db.add(db_session)
        await db.flush() 
        await db.commit() 
        await db.refresh(db_session)
        return db_session
    except IntegrityError as e:
        await db.rollback()
        logger.error(f"Integrity Error creating session: {e}", exc_info=True)
        raise e
    except Exception as e: 
        await db.rollback()
        logger.error(f"Error creating/flushing session: {e}", exc_info=True)
        raise e


async def get_sessions(db: AsyncSession, skip: int = 0, limit: int = 100) -> Tuple[List[Session], int]:
    query = select(Session).offset(skip).limit(limit)
    result = await db.execute(query)
    sessions = result.scalars().all()
    
    total_result = await db.execute(select(func.count(Session.id)))
    total_count = total_result.scalar_one_or_none() or 0
    return sessions, total_count

async def get_session(db: AsyncSession, session_id: UUID) -> Optional[Session]:
    # [THE FIX] UUID 객체 사용
    return await db.get(Session, session_id)

async def update_session(db: AsyncSession, session_id: UUID, session_update: SessionUpdate) -> Optional[Session]:
    db_session = await db.get(Session, session_id)
    if not db_session:
        return None
    
    update_data = session_update.model_dump(exclude_unset=True)
    db_session.sqlmodel_update(update_data)
    
    try:
        db.add(db_session)
        await db.commit()
        await db.refresh(db_session)
        return db_session
    except IntegrityError as e:
        await db.rollback()
        raise e

async def delete_session(db: AsyncSession, session_id: UUID) -> Optional[UUID]:
    db_session = await db.get(Session, session_id)
    if db_session:
        await db.delete(db_session)
        await db.commit()
        return session_id
    return None

async def update_session_status(db: AsyncSession, session_id: UUID, status: SessionStatus) -> Optional[Session]:
    db_session = await db.get(Session, session_id)
    if not db_session:
        return None
        
    db_session.status = status
    if status == SessionStatus.COMPLETED:
        # models.session에 completed_at 필드가 있다면 추가해야 함 (현재는 없음)
        pass
        
    db.add(db_session)
    await db.commit()
    await db.refresh(db_session)
    return db_session