# diag_project/schemas/group.py

from typing import Optional, List
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime

# 공통 속성 (Base)
class GroupBase(BaseModel):
    name: str = Field(..., examples=["테스트 그룹 A"], description="그룹 이름")
    group_code: str = Field(..., examples=["G1001"], description="그룹 고유 코드")
    
    model_config = ConfigDict(from_attributes=True)

# 생성 요청 스키마 (Create)
class GroupCreate(GroupBase):
    pass

# 업데이트 요청 스키마 (Update)
class GroupUpdate(BaseModel):
    name: Optional[str] = Field(None, examples=["테스트 그룹 B"])
    group_code: Optional[str] = Field(None, examples=["G1002"])
    
    model_config = ConfigDict(from_attributes=True)

# 응답 스키마 (Read/Response)
class GroupResponse(GroupBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)

# 리스트 응답 스키마
class GroupListResponse(BaseModel):
    items: List[GroupResponse]
    total: int = 0
    skip: int = 0
    limit: int = 100

    model_config = ConfigDict(from_attributes=True)