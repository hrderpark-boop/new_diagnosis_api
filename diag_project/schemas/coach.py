# diag_project/schemas/coach.py

from uuid import UUID
from typing import Optional, List
from pydantic import BaseModel

class CoachSchema(BaseModel):
    id: UUID
    name: str
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    is_default: bool = False
    
    # 이미지 관련 (이건 유지)
    avatar_url: Optional[str] = None  
    image: Optional[str] = None       
    imageUrl: Optional[str] = None    
    coaching_style: Optional[str] = None

    # [✅ 추가됨] 태그 정보 필수!
    tags: Optional[List[str]] = []       # 예: ["#따뜻함", "#공감"]
    character_tags: Optional[str] = None # 원본 문자열도 혹시 몰라 보냄

    class Config:
        from_attributes = True
