# diag_project/models/participant.py

from typing import Optional, List, TYPE_CHECKING # [수정] List 추가
from uuid import UUID, uuid4
from sqlmodel import Field, SQLModel, Relationship # [수정] Relationship 추가
from sqlalchemy import text, Column, DateTime, ForeignKey, func
from datetime import datetime, timezone
from diag_project.models.uuid_type import GUID

if TYPE_CHECKING:
    from diag_project.models.evaluation_result import EvaluationResult

# ✅ 기본 속성 정의 (Base)
class ParticipantBase(SQLModel):
    # 이메일은 필수 (Unique)
    email: str = Field(unique=True, index=True, max_length=255)
    
    name: Optional[str] = Field(default=None, max_length=100)
    group_code: Optional[str] = Field(default=None, max_length=100)
    
    gender: Optional[str] = Field(default=None, max_length=10)
    age_group: Optional[str] = Field(default=None, max_length=20)

# ✅ 실제 테이블 정의 (Table)
class Participant(ParticipantBase, table=True):
    __tablename__ = "participants"

    # UUID Primary Key 설정
    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(GUID(), primary_key=True, index=True)
    )

    password_hash: Optional[str] = Field(default=None)
    
    is_active: bool = Field(default=True)
    
    # 그룹 ID (나중에 관계형으로 쓸 때 대비)
    group_id: Optional[UUID] = Field(default=None, sa_column=Column(GUID(), ForeignKey("groups.id"), nullable=True))
    
    # 생성/수정 시간 자동 기록
    created_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, default=func.now())
    )
    updated_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now())
    )

    # ✅ [NEW] 세션과의 관계 설정 (1:N)
    # DiagnosisSession 모델의 'user' 필드와 연결됩니다.
    sessions: List["DiagnosisSession"] = Relationship(back_populates="user")

    # 역방향: EvaluationResult.participant 와 매칭 (1:N)
    evaluation_results: List["EvaluationResult"] = Relationship(back_populates="participant")