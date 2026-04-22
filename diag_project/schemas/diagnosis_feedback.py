# diag_project/schemas/diagnosis_feedback.py (수정 반영)

from typing import Optional, List
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict

# --- 공통 속성 ---
class DiagnosisFeedbackBase(BaseModel):
    feedback_text: Optional[str] = Field(None, max_length=2000, description="피드백 내용")
    rating: Optional[int] = Field(None, description="평점 (1-5)")
    diagnosis_id: UUID
    diagnosis_question_id: UUID
    coach_persona_id: Optional[UUID] = None
    
    model_config = ConfigDict(from_attributes=True)

# --- 생성 요청 ---
class DiagnosisFeedbackCreate(DiagnosisFeedbackBase):
    pass

# --- 업데이트 요청 ---
class DiagnosisFeedbackUpdate(BaseModel):
    feedback_text: Optional[str] = None
    rating: Optional[int] = None
    
    model_config = ConfigDict(from_attributes=True)

# --- 응답 스키마 ---
class DiagnosisFeedbackResponse(DiagnosisFeedbackBase):
    id: UUID
    created_at: datetime

# --- 리스트 응답 ---
class DiagnosisFeedbackListResponse(BaseModel):
    items: List[DiagnosisFeedbackResponse]
    total: int
    skip: int
    limit: int
    
    model_config = ConfigDict(from_attributes=True)