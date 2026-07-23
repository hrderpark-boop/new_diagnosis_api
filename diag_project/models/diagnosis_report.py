import uuid
from datetime import datetime
from typing import Optional, Dict, Any
from sqlmodel import SQLModel, Field
from sqlalchemy import JSON, Text, Column  # ✅ Text, JSON을 여기서 직접 가져옵니다.

from diag_project.models.uuid_type import GUID


class DiagnosisReport(SQLModel, table=True):
    __tablename__ = "diagnosis_reports"

    # ⚠️ UUID 컬럼은 반드시 GUID() 를 써야 한다.
    # SQLModel 기본 매핑은 SQLite 에서 하이픈 없는 32자로 저장하는데,
    # participants.id 등 다른 테이블은 GUID(=CHAR(36), 하이픈 포함)로 저장한다.
    # 두 형식이 섞이면 user_id ↔ participants.id 조인이 한 건도 매칭되지 않는다.
    # (PostgreSQL 은 양쪽 다 native uuid 라 증상이 드러나지 않아 더 위험하다)
    id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        sa_column=Column(GUID(), primary_key=True),
    )
    session_id: uuid.UUID = Field(sa_column=Column(GUID(), index=True))
    user_id: uuid.UUID = Field(sa_column=Column(GUID(), index=True))
    coach_id: uuid.UUID = Field(sa_column=Column(GUID()))
    
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

    # ------------------------------------------------------------------
    # Human-in-the-Loop (골든 데이터셋 구축용)
    # ------------------------------------------------------------------
    # 관리자가 AI 산출물을 교정했는지 여부. Fine-tuning/RAG 학습 시
    # '사람이 검수·확정한 고품질 샘플'만 선별하는 필터로 사용한다.
    is_human_edited: bool = Field(default=False, index=True)

    # 최초 교정 직전의 AI 원본 스냅샷.
    # 학습 신호는 (AI 원본 → 사람 교정본) '쌍'에서 나오므로, 덮어쓰기 전에
    # 원본을 보존하지 않으면 데이터셋으로서의 가치가 사라진다.
    # 두 번째 이후 교정에서는 덮어쓰지 않는다(항상 최초 AI 출력을 유지).
    ai_original: Optional[Dict[str, Any]] = Field(default=None, sa_type=JSON)

    edited_at: Optional[datetime] = Field(default=None)
    # 교정 책임 추적용. 관리자 이메일을 그대로 남긴다.
    edited_by: Optional[str] = Field(default=None, max_length=255)