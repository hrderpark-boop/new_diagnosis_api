# diag_project/models/diagnosis_question.py

from typing import Optional
from uuid import UUID, uuid4
from datetime import datetime, timezone
from enum import Enum
from sqlmodel import Field, SQLModel
from sqlalchemy import Column, DateTime, func, text, ForeignKey
from diag_project.models.uuid_type import GUID

class QuestionType(str, Enum):
    SINGLE_CHOICE = "single_choice"
    MULTIPLE_CHOICE = "multiple_choice"
    TEXT = "text"
    SITUATION_CHOICE = "situation_choice"
    OPEN = "open" 

class DiagnosisQuestionBase(SQLModel):
    question_text: str = Field()
    question_type: QuestionType = Field(default=QuestionType.TEXT)
    order: int = Field(default=0)
    is_active: bool = Field(default=True)

class DiagnosisQuestion(DiagnosisQuestionBase, table=True):
    __tablename__ = "diagnosis_questions"
    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(GUID(), primary_key=True, index=True)
    )
    diagnosis_template_id: UUID = Field(sa_column=Column(GUID(), ForeignKey("diagnosis_templates.id"), index=True))
    question_category_id: UUID = Field(sa_column=Column(GUID(), ForeignKey("question_categories.id"), index=True))
    competency_id: Optional[UUID] = Field(default=None, sa_column=Column(GUID(), ForeignKey("competencies.id"), nullable=True))
    indicator_id: Optional[UUID] = Field(default=None, sa_column=Column(GUID(), ForeignKey("indicators.id"), nullable=True))
    created_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, default=func.now())
    )
    updated_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now())
    )

class QuestionChoiceBase(SQLModel):
    choice_text: str = Field()
    score: Optional[int] = Field(default=None)
    order: int = Field(default=0)
    is_active: bool = Field(default=True)

class QuestionChoice(QuestionChoiceBase, table=True):
    __tablename__ = "question_choices"
    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(GUID(), primary_key=True, index=True)
    )
    diagnosis_question_id: UUID = Field(sa_column=Column(GUID(), ForeignKey("diagnosis_questions.id"), index=True))
    created_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, default=func.now())
    )
    updated_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now())
    )