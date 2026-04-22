# diag_project/routes/question_category.py

from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from diag_project.database import get_db
# [THE FIX] schemas에서 임포트
from diag_project.schemas.question_category import (
    QuestionCategoryCreate, 
    QuestionCategoryUpdate, 
    QuestionCategoryResponse,
    QuestionCategoryListResponse
)
# 모델 임포트
from diag_project.models.question_category import QuestionCategory

router = APIRouter(
    prefix="/api/v1/question-categories",
    tags=["Question Categories"],
    responses={404: {"description": "Not found"}},
)

@router.post("/", response_model=QuestionCategoryResponse, status_code=status.HTTP_201_CREATED)
async def create_category(category: QuestionCategoryCreate, db: AsyncSession = Depends(get_db)):
    db_category = QuestionCategory.model_validate(category)
    db.add(db_category)
    await db.commit()
    await db.refresh(db_category)
    return db_category

@router.get("/", response_model=QuestionCategoryListResponse)
async def read_categories(skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db)):
    # (간단하게 구현, 실제로는 count 쿼리 필요)
    result = await db.execute(select(QuestionCategory).offset(skip).limit(limit))
    categories = result.scalars().all()
    return QuestionCategoryListResponse(items=categories, total=len(categories), skip=skip, limit=limit)

# ... (나머지 CRUD는 필요시 구현)