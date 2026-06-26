#diag_project/models/question_category.py

from typing import Optional, List
from uuid import UUID, uuid4
from datetime import datetime, timezone

from sqlmodel import Field, Relationship, SQLModel
from sqlalchemy import Column, DateTime, func, text
from diag_project.models.uuid_type import GUID

class QuestionCategoryBase(SQLModel):
    name: str = Field(max_length=100, unique=True)
    description: Optional[str] = Field(default=None, max_length=500)

class QuestionCategory(QuestionCategoryBase, table=True):
    __tablename__ = "question_categories"

    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(GUID(), primary_key=True, index=True)
    )

    created_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, default=func.now())
    )
    updated_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now())
    )

    # [THE FIX] 관계 주석 처리 (매핑 에러 방지)
    # questions: List["DiagnosisQuestion"] = Relationship(back_populates="question_category")