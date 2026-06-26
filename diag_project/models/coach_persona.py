# diag_project/models/coach_persona.py

from typing import Optional
from uuid import UUID, uuid4
from datetime import datetime, timezone
from sqlmodel import Field, SQLModel
from sqlalchemy import Column, DateTime, func, text, ForeignKey
from diag_project.models.uuid_type import GUID

class CoachPersonaBase(SQLModel):
    name: str = Field(max_length=100)
    description: Optional[str] = Field(default=None, max_length=500)
    system_prompt: str = Field()
    is_default: bool = Field(default=False)
    gender: Optional[str] = Field(default=None, max_length=50)
    age_range: Optional[str] = Field(default=None, max_length=50)
    coaching_style: Optional[str] = Field(default=None, max_length=255)
    is_active: bool = Field(default=True)

class CoachPersona(CoachPersonaBase, table=True):
    __tablename__ = "coach_personas"
    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(GUID(), primary_key=True, index=True)
    )
    coach_id: UUID = Field(sa_column=Column(GUID(), ForeignKey("coaches.id"), index=True))
    created_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, default=func.now())
    )
    updated_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now())
    )