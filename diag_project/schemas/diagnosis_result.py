# diag_project/schemas/diagnosis_result.py 

from typing import Optional, List, Dict, Any
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict

# --- 기본 스키마 ---
class DiagnosisResultBase(BaseModel):
    score: float = Field(..., description="진단 결과 점수")
    feedback_summary: Optional[str] = Field(None, max_length=4000)
    diagnosis_id: UUID
    participant_id: UUID
    competency_id: UUID
    indicator_id: Optional[UUID] = None
    
    model_config = ConfigDict(from_attributes=True)

class DiagnosisResultCreate(DiagnosisResultBase):
    pass

class DiagnosisResultUpdate(BaseModel):
    score: Optional[float] = None
    feedback_summary: Optional[str] = None
    
    model_config = ConfigDict(from_attributes=True)

class DiagnosisResultResponse(DiagnosisResultBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

class DiagnosisResultListResponse(BaseModel):
    items: List[DiagnosisResultResponse]
    total: int
    skip: int
    limit: int
    
    model_config = ConfigDict(from_attributes=True)