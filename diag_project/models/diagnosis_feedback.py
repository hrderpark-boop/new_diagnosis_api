# diag_project/models/diagnosis_feedback.py

from typing import Optional
from uuid import UUID, uuid4
from datetime import datetime, timezone
from sqlmodel import Field, SQLModel
from sqlalchemy import Column, DateTime, func, text, ForeignKey
from diag_project.models.uuid_type import GUID

class DiagnosisFeedbackBase(SQLModel):
    feedback_text: Optional[str] = Field(default=None, max_length=2000)
    rating: Optional[int] = Field(default=None)

class DiagnosisFeedback(DiagnosisFeedbackBase, table=True):
    __tablename__ = "diagnosis_feedbacks"
    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(GUID(), primary_key=True, index=True, server_default=text("LOWER(HEX(RANDOMBLOB(16)))"))
    )
    diagnosis_id: UUID = Field(sa_column=Column(GUID(), ForeignKey("diagnosis.id"), index=True))
    diagnosis_question_id: UUID = Field(sa_column=Column(GUID(), ForeignKey("diagnosis_questions.id"), index=True))
    coach_persona_id: Optional[UUID] = Field(default=None, sa_column=Column(GUID(), ForeignKey("coach_personas.id"), index=True, nullable=True))
    created_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, default=func.now())
    )
    updated_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now())
    )
    # Relationship 제거됨