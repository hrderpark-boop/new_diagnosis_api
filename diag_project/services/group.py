# diag_project/services/group.py 

import logging
from typing import List, Optional, Tuple
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError

# [THE FIX] 스키마는 schemas 패키지에서 가져옵니다.
from diag_project.schemas.group import GroupCreate, GroupUpdate
# [THE FIX] DB 모델은 models 패키지에서 가져옵니다.
from diag_project.models.group import Group

logger = logging.getLogger(__name__)

# --- Group (그룹) 서비스 ---

async def create_group(db: AsyncSession, group: GroupCreate) -> Group:
    db_group = Group.model_validate(group)
    try:
        db.add(db_group)
        await db.commit()
        await db.refresh(db_group)
        return db_group
    except IntegrityError as e:
        await db.rollback()
        logger.error(f"Integrity Error creating group: {e}", exc_info=True)
        raise e

async def get_groups(db: AsyncSession, skip: int = 0, limit: int = 100) -> Tuple[List[Group], int]:
    query = select(Group).offset(skip).limit(limit)
    result = await db.execute(query)
    groups = result.scalars().all()
    
    total_result = await db.execute(select(func.count(Group.id)))
    total_count = total_result.scalar_one_or_none() or 0
    
    return groups, total_count

async def get_group(db: AsyncSession, group_id: UUID) -> Optional[Group]:
    return await db.get(Group, group_id)

async def get_group_by_code(db: AsyncSession, group_code: str) -> Optional[Group]:
    result = await db.execute(select(Group).where(Group.group_code == group_code))
    return result.scalars().first()

async def update_group(db: AsyncSession, group_id: UUID, group_update: GroupUpdate) -> Optional[Group]:
    db_group = await db.get(Group, group_id)
    if not db_group:
        return None
        
    update_data = group_update.model_dump(exclude_unset=True)
    db_group.sqlmodel_update(update_data)
    
    try:
        db.add(db_group)
        await db.commit()
        await db.refresh(db_group)
        return db_group
    except IntegrityError as e:
        await db.rollback()
        raise e

async def delete_group(db: AsyncSession, group_id: UUID) -> Optional[UUID]:
    db_group = await db.get(Group, group_id)
    if db_group:
        await db.delete(db_group)
        await db.commit()
        return group_id
    return None