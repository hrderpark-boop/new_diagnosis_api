# diag_project/schemas/participant.py

from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict, EmailStr
from datetime import datetime

class ParticipantBase(BaseModel):
    email: EmailStr = Field(..., examples=["test@example.com"])
    name: str = Field(..., examples=["홍길동"])
    gender: Optional[str] = Field(None, examples=["남성"])
    age_group: Optional[str] = Field(None, examples=["20대"])
    is_active: bool = Field(True, examples=[True])
    
    model_config = ConfigDict(from_attributes=True)

class ParticipantCreate(ParticipantBase):
    password: str = Field(..., examples=["secure_password_123!"])
    group_code: Optional[str] = Field(None, description="가입할 그룹 코드")
    group_id: Optional[UUID] = Field(None, description="참가자가 속할 그룹의 ID (내부용)")

class ParticipantUpdate(BaseModel):
    name: Optional[str] = None
    # [THE FIX] email 필드 추가 (이메일 변경 허용)
    email: Optional[EmailStr] = None 
    gender: Optional[str] = None
    age_group: Optional[str] = None
    password: Optional[str] = None
    is_active: Optional[bool] = None
    group_id: Optional[UUID] = None 

    model_config = ConfigDict(from_attributes=True)

class ParticipantResponse(ParticipantBase):
    id: UUID
    created_at: datetime
    updated_at: datetime
    group_id: Optional[UUID] = None

    model_config = ConfigDict(from_attributes=True)

class ParticipantListResponse(BaseModel):
    items: List[ParticipantResponse]
    total: int
    skip: int
    limit: int
    
    model_config = ConfigDict(from_attributes=True)

class ParticipantLogin(BaseModel):
    email: EmailStr = Field(..., examples=["test@example.com"])
    password: str = Field(..., examples=["secure_password_123!"])
    group_code: str = Field(..., examples=["G1001"], description="로그인할 진단 그룹의 코드")

    model_config = ConfigDict(from_attributes=True)