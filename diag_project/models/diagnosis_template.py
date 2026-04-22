# diag_project/models/diagnosis_template.py

from typing import Optional
from uuid import UUID, uuid4
from datetime import datetime, timezone
from sqlmodel import Field, SQLModel
from sqlalchemy import func, Column, DateTime, text, ForeignKey
from diag_project.models.uuid_type import GUID

class DiagnosisTemplateBase(SQLModel):
    name: str = Field(max_length=255)
    description: Optional[str] = Field(default=None, max_length=1000)
    version: str = Field(default="1.0", max_length=50)
    is_active: bool = Field(default=True)

class DiagnosisTemplate(DiagnosisTemplateBase, table=True):
    __tablename__ = "diagnosis_templates"
    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(GUID(), primary_key=True, index=True, server_default=text("LOWER(HEX(RANDOMBLOB(16)))"))
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