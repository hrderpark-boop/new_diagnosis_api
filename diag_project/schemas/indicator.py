#diag_project/schemas/indicator.py

from typing import Optional, List, Dict
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime

class IndicatorBase(BaseModel):
    name: str = Field(..., max_length=255, description="지표 이름")
    description: Optional[str] = Field(None, max_length=1000)
    indicator_id: Optional[str] = Field(None, description="지표 식별자 (예: vision_sharing)")
    question: Optional[str] = Field(None, description="진단 질문")
    is_active: bool = Field(True, description="활성화 여부")
    
    # JSON 필드 대응
    levels: Optional[Dict[str, str]] = None # 키가 숫자일 수 있으나 JSON은 문자열 키 권장
    examples: Optional[Dict[str, str]] = None

    model_config = ConfigDict(from_attributes=True)

class IndicatorCreate(IndicatorBase):
    competency_id: UUID

class IndicatorUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    question: Optional[str] = None
    is_active: Optional[bool] = None
    levels: Optional[Dict[str, str]] = None
    examples: Optional[Dict[str, str]] = None
    
    model_config = ConfigDict(from_attributes=True)

class IndicatorResponse(IndicatorBase):
    id: UUID
    competency_id: UUID
    created_at: datetime
    updated_at: datetime

class IndicatorListResponse(BaseModel):
    items: List[IndicatorResponse]
    total: int
    skip: int
    limit: int