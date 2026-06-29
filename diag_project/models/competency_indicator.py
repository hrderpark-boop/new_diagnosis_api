# diag_project/models/competency_indicator.py

from typing import Optional, Dict, List, TYPE_CHECKING
from uuid import UUID, uuid4
from datetime import datetime, timezone
from sqlmodel import Field, SQLModel, Relationship
from sqlalchemy import func, Column, DateTime, text, ForeignKey, JSON
from diag_project.models.uuid_type import GUID

if TYPE_CHECKING:
    from diag_project.models.evaluation_result import EvaluationResult

class CompetencyBase(SQLModel):
    name: str = Field(max_length=255)
    description: Optional[str] = Field(default=None, max_length=1000)
    competency_id: Optional[str] = Field(default=None, index=True) 
    is_active: bool = Field(default=True)

class Competency(CompetencyBase, table=True):
    __tablename__ = "competencies"
    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(GUID(), primary_key=True, index=True),
    )
    created_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, default=func.now()),
    )
    updated_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now()),
    )

    # 역방향: EvaluationResult.competency 와 매칭 (1:N)
    evaluation_results: List["EvaluationResult"] = Relationship(back_populates="competency")

class IndicatorBase(SQLModel):
    name: str = Field(max_length=255)
    description: Optional[str] = Field(default=None, max_length=1000)
    indicator_id: Optional[str] = Field(default=None, index=True)
    question: Optional[str] = Field(default=None)
    is_active: bool = Field(default=True)
    levels: Optional[Dict] = Field(default=None, sa_column=Column(JSON))
    examples: Optional[Dict] = Field(default=None, sa_column=Column(JSON))

class Indicator(IndicatorBase, table=True):
    __tablename__ = "indicators"
    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(GUID(), primary_key=True, index=True),
    )
    competency_id: UUID = Field(sa_column=Column(GUID(), ForeignKey("competencies.id"), index=True))
    created_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, default=func.now()),
    )
    updated_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now()),
    )

    # 역방향: EvaluationResult.indicator 와 매칭 (1:N)
    evaluation_results: List["EvaluationResult"] = Relationship(back_populates="indicator")