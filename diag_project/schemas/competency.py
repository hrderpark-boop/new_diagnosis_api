# diag_project/schemas/competency.py

from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime

class CompetencyBase(BaseModel):
    name: str = Field(..., max_length=255, description="역량 이름")
    description: Optional[str] = Field(None, max_length=1000)
    competency_id: Optional[str] = Field(None, description="역량 식별자 (예: organization_management)")
    is_active: bool = Field(True, description="활성화 여부")

    model_config = ConfigDict(from_attributes=True)

class CompetencyCreate(CompetencyBase):
    pass

class CompetencyUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    is_active: Optional[bool] = None
    
    model_config = ConfigDict(from_attributes=True)

class CompetencyResponse(CompetencyBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

class CompetencyListResponse(BaseModel):
    items: List[CompetencyResponse]
    total: int
    skip: int
    limit: int