#diag_project/services/question_category.py

import logging
from typing import List, Optional, Tuple
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlmodel import delete
from sqlalchemy.exc import IntegrityError

# 모델 및 스키마 임포트
from diag_project.models.question_category import (
    QuestionCategory,
    QuestionCategoryCreate,
    QuestionCategoryUpdate
)

logger = logging.getLogger(__name__)

# --- QuestionCategory (질문 카테고리) 서비스 ---

async def create_category(db: AsyncSession, category: QuestionCategoryCreate) -> QuestionCategory:
    db_category = QuestionCategory.model_validate(category)
    try:
        db.add(db_category)
        await db.commit()
        await db.refresh(db_category)
        return db_category
    except IntegrityError as e:
        await db.rollback()
        logger.error(f"Integrity Error creating category: {e}", exc_info=True)
        raise e

async def get_categories(db: AsyncSession, skip: int = 0, limit: int = 100) -> Tuple[List[QuestionCategory], int]:
    query = select(QuestionCategory).offset(skip).limit(limit)
    result = await db.execute(query)
    categories = result.scalars().all()
    
    total_result = await db.execute(select(func.count(QuestionCategory.id)))
    total_count = total_result.scalar_one_or_none() or 0
    
    return categories, total_count

async def get_category(db: AsyncSession, category_id: UUID) -> Optional[QuestionCategory]:
    return await db.get(QuestionCategory, category_id)

async def update_category(db: AsyncSession, category_id: UUID, category_update: QuestionCategoryUpdate) -> Optional[QuestionCategory]:
    db_category = await db.get(QuestionCategory, category_id)
    if not db_category:
        return None
        
    update_data = category_update.model_dump(exclude_unset=True)
    db_category.sqlmodel_update(update_data)
    
    try:
        db.add(db_category)
        await db.commit()
        await db.refresh(db_category)
        return db_category
    except IntegrityError as e:
        await db.rollback()
        raise e

async def delete_category(db: AsyncSession, category_id: UUID) -> Optional[UUID]:
    db_category = await db.get(QuestionCategory, category_id)
    if db_category:
        await db.delete(db_category)
        await db.commit()
        return category_id
    return None