# diag_project/services/participant.py

import logging
from typing import List, Optional, Tuple
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy import func

from diag_project.schemas.participant import ParticipantCreate, ParticipantUpdate
from diag_project.models.participant import Participant
from diag_project.models.group import Group
from diag_project.security import get_password_hash, verify_password

logger = logging.getLogger(__name__)

async def create_participant(db: AsyncSession, participant: ParticipantCreate) -> Participant:
    db_group = None
    if participant.group_id:
        db_group = await db.get(Group, participant.group_id)
        if not db_group:
            if participant.group_code:
                result = await db.execute(select(Group).where(Group.group_code == participant.group_code))
                db_group = result.scalar_one_or_none()
            if not db_group:
                raise ValueError(f"Group with id {participant.group_id} not found")
    elif participant.group_code:
        result = await db.execute(select(Group).where(Group.group_code == participant.group_code))
        db_group = result.scalar_one_or_none()
        if not db_group:
            raise ValueError(f"Group with code {participant.group_code} not found")
        participant.group_id = db_group.id
    
    if db_group:
        participant.group_id = db_group.id

    result = await db.execute(select(Participant).where(Participant.email == participant.email))
    existing_participant = result.scalar_one_or_none()
    if existing_participant:
        raise ValueError(f"Email {participant.email} already registered")

    hashed_password = get_password_hash(participant.password)
    
    db_participant = Participant(
        name=participant.name,
        email=participant.email,
        password_hash=hashed_password, 
        group_id=participant.group_id,
        gender=participant.gender,
        age_group=participant.age_group,
        is_active=participant.is_active
    )
    
    try:
        db.add(db_participant)
        await db.commit()
        await db.refresh(db_participant)
        return db_participant
    except Exception as e:
        await db.rollback()
        logger.error(f"Error creating participant: {e}", exc_info=True)
        raise

async def get_participants(db: AsyncSession, skip: int = 0, limit: int = 100) -> Tuple[List[Participant], int]:
    query = select(Participant).offset(skip).limit(limit)
    result = await db.execute(query)
    participants = result.scalars().all()
    total_result = await db.execute(select(func.count(Participant.id)))
    total_count = total_result.scalar_one_or_none() or 0
    return participants, total_count

async def get_participant(db: AsyncSession, participant_id: UUID) -> Optional[Participant]:
    if isinstance(participant_id, str):
        try:
            participant_id = UUID(participant_id)
        except ValueError:
            return None
    return await db.get(Participant, participant_id)

async def get_participant_by_email(db: AsyncSession, email: str) -> Optional[Participant]:
    result = await db.execute(select(Participant).where(Participant.email == email))
    return result.scalar_one_or_none()

# [THE FIX] 업데이트 로직 강화
async def update_participant(db: AsyncSession, participant_id: str, participant_update: ParticipantUpdate) -> Optional[Participant]:
    try:
        p_uuid = UUID(participant_id)
    except ValueError:
        return None

    db_participant = await db.get(Participant, p_uuid)
    if not db_participant:
        return None
        
    update_data = participant_update.model_dump(exclude_unset=True)
    
    # 비밀번호 처리
    if "password" in update_data and update_data["password"]:
        update_data["password_hash"] = get_password_hash(update_data["password"])
        del update_data["password"]

    # group_id 처리 (스키마에 추가되어 있다면)
    # 주의: Pydantic v2에서는 model_dump에 포함되지만, SQLModel 업데이트 시 누락될 수 있음
    if "group_id" in update_data:
        db_participant.group_id = update_data["group_id"]

    # 나머지 필드 업데이트
    for key, value in update_data.items():
        if key != "group_id": # group_id는 위에서 처리함
            setattr(db_participant, key, value)
    
    try:
        db.add(db_participant)
        await db.commit()
        await db.refresh(db_participant)
        return db_participant
    except Exception as e:
        await db.rollback()
        logger.error(f"Error updating participant: {e}", exc_info=True)
        raise

async def delete_participant(db: AsyncSession, participant_id: str) -> Optional[str]:
    try:
        p_uuid = UUID(participant_id)
    except ValueError:
        return None

    db_participant = await db.get(Participant, p_uuid)
    if db_participant:
        await db.delete(db_participant)
        await db.commit()
        return participant_id
    return None

async def authenticate_participant(db: AsyncSession, email: str, password: str, group_code: str) -> Optional[Participant]:
    # 1. 그룹 코드 확인
    result = await db.execute(select(Group).where(Group.group_code == group_code))
    db_group = result.scalar_one_or_none()
    
    if not db_group:
        logger.warning(f"Authentication failed: Invalid group code {group_code}")
        return None
        
    # [THE FIX] 쿼리 최적화 및 로깅 강화
    # 참가자 조회 시 그룹 ID도 함께 확인
    stmt = select(Participant).where(Participant.email == email)
    result = await db.execute(stmt)
    db_participant = result.scalar_one_or_none()

    if not db_participant:
        logger.warning(f"Authentication failed: Email {email} not found")
        return None

    # 그룹 일치 여부 확인 (DB 값 vs 입력된 그룹 코드의 ID)
    if db_participant.group_id != db_group.id:
        logger.warning(f"Authentication failed: Participant group mismatch. (User Group: {db_participant.group_id}, Input Group: {db_group.id})")
        return None

    # 비밀번호 검증
    if not verify_password(password, db_participant.password_hash):
        logger.warning(f"Authentication failed: Invalid password for {email}")
        return None

    return db_participant