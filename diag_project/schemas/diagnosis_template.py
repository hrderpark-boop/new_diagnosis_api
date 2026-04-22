# diag_project/schemas/diagnosis_template.py

from typing import Optional, List
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict

from diag_project.schemas.diagnosis_question import DiagnosisQuestionResponse

# --- 공통 속성 ---
class DiagnosisTemplateBase(BaseModel):
    name: str = Field(..., max_length=255, description="템플릿 이름")
    description: Optional[str] = Field(None, max_length=1000)
    version: str = Field("1.0", max_length=50)
    is_active: bool = Field(True)
    coach_id: UUID = Field(..., description="연결된 코치 ID")
    
    model_config = ConfigDict(from_attributes=True)

# --- 생성 요청 스키마 ---
class DiagnosisTemplateCreate(DiagnosisTemplateBase):
    pass

# --- 수정 요청 스키마 ---
class DiagnosisTemplateUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    version: Optional[str] = None
    is_active: Optional[bool] = None
    coach_id: Optional[UUID] = None
    
    model_config = ConfigDict(from_attributes=True)

# --- 응답 스키마 ---
class DiagnosisTemplateResponse(DiagnosisTemplateBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

# 질문이 포함된 상세 응답 스키마 (필요 시 사용)
class DiagnosisTemplateDetailResponse(DiagnosisTemplateResponse):
    questions: List[DiagnosisQuestionResponse] = []

class DiagnosisTemplateListResponse(BaseModel):
    items: List[DiagnosisTemplateResponse]
    total: int
    skip: int
    limit: int
    
    model_config = ConfigDict(from_attributes=True)