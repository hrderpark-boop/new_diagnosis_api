#diag_project/models/diagnosis.py

from typing import Optional, List, TYPE_CHECKING
from uuid import UUID, uuid4
from datetime import datetime, timezone
from enum import Enum
from sqlmodel import Field, SQLModel, Relationship
from sqlalchemy import func, Column, DateTime, text, ForeignKey
from .uuid_type import GUID

if TYPE_CHECKING:
    from .evaluation_result import EvaluationResult

class DiagnosisStatus(str, Enum):
    NOT_STARTED = "not_started"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ERROR = "error"

class DiagnosisBase(SQLModel):
    status: DiagnosisStatus = Field(default=DiagnosisStatus.NOT_STARTED, max_length=50)
    participant_id: str = Field(max_length=36)
    diagnosis_template_id: str = Field(max_length=36)
    coach_persona_id: str = Field(max_length=36) 

class Diagnosis(DiagnosisBase, table=True):
    __tablename__ = "diagnosis" 
    id: UUID = Field(  
        default_factory=uuid4,
        sa_column=Column(GUID(), primary_key=True),
    )
    participant_id: UUID = Field(sa_column=Column(GUID(), ForeignKey("participants.id"), index=True))
    diagnosis_template_id: UUID = Field(sa_column=Column(GUID(), ForeignKey("diagnosis_templates.id"), index=True))
    coach_persona_id: UUID = Field(sa_column=Column(GUID(), ForeignKey("coach_personas.id"), index=True))
    started_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, default=func.now()),
    )
    completed_at: Optional[datetime] = Field(default=None, sa_column=Column(DateTime(timezone=True), nullable=True))

    # 역방향: EvaluationResult.diagnosis 와 매칭 (1:N)
    evaluation_results: List["EvaluationResult"] = Relationship(back_populates="diagnosis")