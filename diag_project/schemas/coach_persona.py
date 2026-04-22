# diag_project/schemas/coach_persona.py

from typing import Optional, List
from datetime import datetime
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict

from diag_project.schemas.base import BaseSchema

# --- 기본 속성 ---
class CoachPersonaBase(BaseModel):
    name: str = Field(..., examples=["친절한 상담사"], description="페르소나 이름")
    description: Optional[str] = Field(None, examples=["따뜻하고 공감 능력이 뛰어난 코칭 스타일"], description="페르소나 상세 설명")
    system_prompt: str = Field(..., description="LLM 시스템 프롬프트")
    is_default: bool = Field(False, description="기본 페르소나 여부")
    
    # 추가 필드 (routes에 있던 내용 반영)
    gender: Optional[str] = Field(None, examples=["여성"])
    age_range: Optional[str] = Field(None, examples=["30대"])
    coaching_style: Optional[str] = Field(None, examples=["긍정적 강화, 경청, 공감"])
    is_active: bool = Field(True, description="페르소나 활성화 여부")

    model_config = ConfigDict(from_attributes=True)

# --- 생성 요청 ---
class CoachPersonaCreate(CoachPersonaBase):
    coach_id: UUID = Field(..., description="연결된 코치 ID")

# --- 업데이트 요청 ---
class CoachPersonaUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    is_default: Optional[bool] = None
    gender: Optional[str] = None
    age_range: Optional[str] = None
    coaching_style: Optional[str] = None
    is_active: Optional[bool] = None
    
    model_config = ConfigDict(from_attributes=True)

# --- 응답 스키마 ---
class CoachPersonaResponse(CoachPersonaBase):
    id: UUID
    coach_id: UUID
    created_at: datetime
    updated_at: datetime

# --- 리스트 응답 ---
class CoachPersonaListResponse(BaseModel):
    items: List[CoachPersonaResponse]
    total: int = 0
    skip: int = 0
    limit: int = 100
    
    model_config = ConfigDict(from_attributes=True)