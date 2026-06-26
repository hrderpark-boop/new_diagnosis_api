# diag_project/models/coach.py

from typing import Optional
from uuid import UUID, uuid4
from datetime import datetime, timezone
from sqlmodel import Field, SQLModel
from sqlalchemy import func, Column, DateTime, text, ForeignKey
from diag_project.models.uuid_type import GUID

class CoachBase(SQLModel):
    name: str = Field(max_length=100)
    email: str = Field(max_length=255, index=True)
    description: Optional[str] = Field(default=None, max_length=500)
    avatar_url: Optional[str] = Field(default=None, max_length=500)
    character_tags: Optional[str] = Field(default=None, max_length=500)

class Coach(CoachBase, table=True):
    __tablename__ = "coaches"
    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(GUID(), primary_key=True, index=True)
    )
    user_id: UUID = Field(sa_column=Column(GUID(), ForeignKey("participants.id"), index=True))
    created_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, default=func.now())
    )
    updated_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now())
    )