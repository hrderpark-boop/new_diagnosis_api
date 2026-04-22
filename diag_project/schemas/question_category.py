# diag_project/schemas/question_category.py (수정 반영)

from typing import Optional, List
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict

# --- 기본 속성 ---
class QuestionCategoryBase(BaseModel):
    name: str = Field(..., max_length=100, description="카테고리 이름")
    description: Optional[str] = Field(None, max_length=500, description="카테고리 설명")
    
    model_config = ConfigDict(from_attributes=True)

# --- 생성 요청 ---
class QuestionCategoryCreate(QuestionCategoryBase):
    pass

# --- 업데이트 요청 ---
class QuestionCategoryUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)

# --- 응답 스키마 ---
class QuestionCategoryResponse(QuestionCategoryBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

# --- [THE FIX] 리스트 응답 스키마 (이게 없어서 에러 발생) ---
class QuestionCategoryListResponse(BaseModel):
    items: List[QuestionCategoryResponse]
    total: int
    skip: int
    limit: int
    
    model_config = ConfigDict(from_attributes=True)