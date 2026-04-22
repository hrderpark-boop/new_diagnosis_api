# diag_project/schemas/diagnosis.py 

from typing import Optional, Any, Dict
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from enum import Enum

# 순환 참조 방지를 위해 models에서 Enum만 가져옵니다.
from diag_project.models.diagnosis import DiagnosisStatus

# --- 기본 CRUD 스키마 ---

class DiagnosisBase(BaseModel):
    status: DiagnosisStatus = DiagnosisStatus.NOT_STARTED
    participant_id: UUID
    diagnosis_template_id: UUID
    coach_persona_id: UUID
    
    model_config = ConfigDict(from_attributes=True)

class DiagnosisCreate(DiagnosisBase):
    pass

class DiagnosisUpdate(BaseModel):
    status: Optional[DiagnosisStatus] = None

class DiagnosisResponse(DiagnosisBase):
    id: UUID
    # [THE FIX] Optional로 변경하여 ResponseValidationError 방지
    created_at: Optional[datetime] = None 
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

# (호환성을 위해 DiagnosisRead도 남겨둘 경우)
DiagnosisRead = DiagnosisResponse


# --- 진단 프로세스(Flow) 전용 API 스키마 ---

class StartDiagnosisRequest(BaseModel):
    participant_id: str
    template_id: str
    coach_persona_id: str 

class StartDiagnosisResponse(BaseModel):
    session_id: str
    diagnosis_id: str
    # 순환 참조 방지를 위해 구체적인 MessageResponse 대신 Dict/Any 사용
    first_message: Dict[str, Any] 
    
    model_config = ConfigDict(arbitrary_types_allowed=True)

class SubmitMessageRequest(BaseModel):
    session_id: str
    diagnosis_id: str
    content: str 

class SubmitMessageResponse(BaseModel):
    user_message: Dict[str, Any] 
    ai_message: Dict[str, Any]   
    
    model_config = ConfigDict(arbitrary_types_allowed=True)