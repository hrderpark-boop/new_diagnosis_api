# diag_project/models/session.py

from typing import Optional
from uuid import UUID, uuid4
from datetime import datetime, timezone
from enum import Enum
from sqlmodel import Field, SQLModel
from sqlalchemy import Column, DateTime, func, text, ForeignKey
from diag_project.models.uuid_type import GUID

class SessionStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ERROR = "error"

class SessionBase(SQLModel):
    status: SessionStatus = Field(default=SessionStatus.IN_PROGRESS)

class Session(SessionBase, table=True):
    __tablename__ = "sessions"
    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(GUID(), primary_key=True, index=True)
    )
    diagnosis_id: UUID = Field(sa_column=Column(GUID(), ForeignKey("diagnosis.id"), index=True))
    participant_id: UUID = Field(sa_column=Column(GUID(), ForeignKey("participants.id"), index=True))
    coach_persona_id: UUID = Field(sa_column=Column(GUID(), ForeignKey("coach_personas.id"), index=True))
    diagnosis_template_id: Optional[UUID] = Field(default=None, sa_column=Column(GUID(), ForeignKey("diagnosis_templates.id"), nullable=True))
    created_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, default=func.now())
    )
    updated_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now())
    )