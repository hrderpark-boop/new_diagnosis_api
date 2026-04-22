# diag_project/schemas/user.py (새로 생성)

from pydantic import BaseModel, Field, EmailStr, ConfigDict
from typing import Optional, List
from datetime import datetime
import uuid

from diag_project.schemas.base import BaseSchema

# --- User (사용자) 스키마 ---
class UserBase(BaseModel):
    email: EmailStr = Field(..., example="user@example.com", description="사용자 이메일 (고유)")
    password: str = Field(..., min_length=8, example="StrongPassword123!", description="사용자 비밀번호")
    name: Optional[str] = Field(None, example="홍길동", description="사용자 이름")
    is_active: Optional[bool] = Field(True, example=True, description="계정 활성화 여부")
    is_superuser: Optional[bool] = Field(False, example=False, description="관리자 권한 여부")

    model_config = ConfigDict(from_attributes=True)

class UserCreate(UserBase):
    pass

class UserUpdate(BaseModel):
    email: Optional[EmailStr] = Field(None, example="new_user@example.com", description="사용자 이메일")
    password: Optional[str] = Field(None, min_length=8, example="NewStrongPassword456!", description="사용자 비밀번호")
    name: Optional[str] = Field(None, example="김철수", description="사용자 이름")
    is_active: Optional[bool] = Field(None, example=False, description="계정 활성화 여부")
    is_superuser: Optional[bool] = Field(None, example=True, description="관리자 권한 여부")

    model_config = ConfigDict(from_attributes=True)

class UserResponse(BaseSchema[str]): # ID는 UUID (str)
    email: EmailStr
    name: Optional[str] = None
    is_active: bool
    is_superuser: bool

    model_config = ConfigDict(from_attributes=True)

class UserListResponse(BaseModel):
    items: List[UserResponse]
    total: int = 0
    skip: int = 0
    limit: int = 100

    model_config = ConfigDict(from_attributes=True)