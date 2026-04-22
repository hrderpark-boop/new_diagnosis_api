import uuid
from datetime import datetime
from typing import Optional, Dict, Any
from sqlmodel import SQLModel, Field
from sqlalchemy import JSON, Text  # ✅ Text, JSON을 여기서 직접 가져옵니다.

class DiagnosisReport(SQLModel, table=True):
    __tablename__ = "diagnosis_reports"

    id: uuid.UUID = Field(default_factory=uuid.uuid4, primary_key=True)
    session_id: uuid.UUID = Field(index=True)
    user_id: uuid.UUID
    coach_id: uuid.UUID
    
    # 종합 점수
    total_score: float = 0.0
    
    # JSON 필드
    scores: Dict[str, Any] = Field(default={}, sa_type=JSON) 
    
    # ✅ [수정 핵심] sa_type="TEXT" 대신 sa_type=Text 사용
    summary: str = Field(sa_type=Text) 
    
    top_competency: Optional[str] = None
    bottom_competency: Optional[str] = None
    
    # ✅ [수정 핵심] sa_type=Text 사용
    feedback: str = Field(sa_type=Text) 
    recommended_action: str = Field(sa_type=Text) 
    
    created_at: datetime = Field(default_factory=datetime.now)