# diag_project/models/evaluation_result.py

from typing import Optional, List
from uuid import UUID, uuid4
from datetime import datetime, timezone

from sqlmodel import Field, Relationship, SQLModel
from sqlalchemy import func, Column, DateTime, text, ForeignKey
from .uuid_type import GUID 
import uuid 

# 💡 (ImportError 및 순환 참조 해결)
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from .diagnosis import Diagnosis
    from .participant import Participant
    from .competency import Competency
    # 💡 'Indicator' 모델을 임포트합니다. (ForeignKey("indicators.id") 기반)
    from .competency_indicator import CompetencyIndicator as Indicator 
    from .session import Session
# ----------------------------------------------------

class EvaluationResultBase(SQLModel):
    score: float = Field(description="진단 결과 점수")
    feedback_summary: Optional[str] = Field(default=None, max_length=4000)
    diagnosis_id: str = Field(max_length=36)
    participant_id: str = Field(max_length=36)
    competency_id: str = Field(max_length=36)
    indicator_id: Optional[str] = Field(default=None, max_length=36)
    session_id: str = Field(max_length=36)

class EvaluationResult(EvaluationResultBase, table=True):
    __tablename__ = "evaluation_results"

    id: str = Field(
        default_factory=lambda: str(uuid4()),
        max_length=36,
        sa_column=Column(GUID(), primary_key=True, index=True),
    )

    diagnosis_id: str = Field(sa_column=Column(GUID(), ForeignKey("diagnosis.id"), index=True)) 
    participant_id: str = Field(sa_column=Column(GUID(), ForeignKey("participants.id"), index=True))
    competency_id: str = Field(sa_column=Column(GUID(), ForeignKey("competencies.id"), index=True))
    
    # ⚠️ 참고: ForeignKey가 'indicators.id'를 참조하고 있습니다. 
    # 모델 파일 'competency_indicator.py'의 __tablename__이 'indicators'가 맞는지 확인이 필요할 수 있습니다.
    indicator_id: Optional[str] = Field(default=None, sa_column=Column(GUID(), ForeignKey("indicators.id"), index=True, nullable=True))
    session_id: str = Field(sa_column=Column(GUID(), ForeignKey("sessions.id"), index=True))

    created_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, default=func.now()),
    )
    updated_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now()),
    )
    
    diagnosis: "Diagnosis" = Relationship(back_populates="evaluation_results")
    participant: "Participant" = Relationship(back_populates="evaluation_results")
    competency: "Competency" = Relationship(back_populates="evaluation_results")
    indicator: Optional["Indicator"] = Relationship(back_populates="evaluation_results")
    
    # 💡 (오류 수정) 
    # session.py가 'evaluation_results'(복수형)를 사용하므로
    # 여기에서도 'evaluation_results' (복수형)로 일치시킵니다.
    session: "Session" = Relationship(back_populates="evaluation_results")

# (Pydantic 스키마...)
class EvaluationResultCreate(EvaluationResultBase):
    pass

class EvaluationResultResponse(EvaluationResultBase):
    id: UUID
    diagnosis_id: UUID
    participant_id: UUID
    competency_id: UUID
    indicator_id: Optional[UUID] = None
    session_id: UUID 
    created_at: datetime
    updated_at: datetime

class EvaluationResultUpdate(SQLModel):
    score: Optional[float] = Field(default=None)
    feedback_summary: Optional[str] = Field(default=None, max_length=4000)