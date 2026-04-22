from typing import Optional, Dict, Any
from uuid import UUID, uuid4
from datetime import datetime
from sqlmodel import Field, SQLModel, Column, JSON

class DiagnosisResult(SQLModel, table=True):
    __tablename__ = "diagnosis_results"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    
    # 어떤 채팅 세션의 결과인지 연결
    session_id: UUID = Field(foreign_key="diagnosis_sessions.id", index=True)
    
    # 누구의 결과인지
    participant_id: UUID = Field(foreign_key="participants.id", index=True)
    
    # 종합 점수 (예: 85.5)
    total_score: float = Field(default=0.0)
    
    # [핵심] 역량별 점수 저장 (JSON)
    # 예: {"organization": 4.5, "people": 3.2, ...}
    scores: Dict = Field(default={}, sa_column=Column(JSON))
    
    # [핵심] AI 분석 텍스트 저장 (JSON)
    # 예: {"strengths": ["추진력", "소통"], "weaknesses": ["위임"], "feedback": "..."}
    summary: Dict = Field(default={}, sa_column=Column(JSON))
    
    # [핵심] 프론트엔드 그래프용 데이터 (JSON)
    chart_data: Dict = Field(default={}, sa_column=Column(JSON))
    
    created_at: datetime = Field(default_factory=datetime.utcnow)