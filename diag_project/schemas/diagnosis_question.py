#diag_project/schemas/diagnosis_question.py

from typing import Optional, List
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict

# 순환 참조 방지를 위해 모델에서 Enum만 가져옵니다.
from diag_project.models.diagnosis_question import QuestionType

# --- Pydantic 스키마 정의 ---

class DiagnosisQuestionBase(BaseModel):
    # [주의] DB 모델의 컬럼명과 일치해야 합니다 (content -> question_text)
    question_text: str = Field(..., description="질문 내용")
    question_type: QuestionType = Field(default=QuestionType.TEXT, description="질문 유형")
    order: int = Field(default=0, description="정렬 순서")
    is_active: bool = Field(default=True, description="활성화 여부")
    
    model_config = ConfigDict(from_attributes=True)

# 생성 요청 스키마
class DiagnosisQuestionCreate(DiagnosisQuestionBase):
    diagnosis_template_id: UUID
    question_category_id: UUID
    indicator_id: Optional[UUID] = None

# 업데이트 요청 스키마
class DiagnosisQuestionUpdate(BaseModel):
    question_text: Optional[str] = None
    question_type: Optional[QuestionType] = None
    order: Optional[int] = None
    is_active: Optional[bool] = None
    
    model_config = ConfigDict(from_attributes=True)

# 응답 스키마
class DiagnosisQuestionResponse(DiagnosisQuestionBase):
    id: UUID
    diagnosis_template_id: UUID
    question_category_id: UUID
    indicator_id: Optional[UUID] = None
    created_at: datetime
    updated_at: datetime

# 리스트 응답 스키마
class DiagnosisQuestionListResponse(BaseModel):
    items: List[DiagnosisQuestionResponse]
    total: int
    skip: int
    limit: int
    
    model_config = ConfigDict(from_attributes=True)