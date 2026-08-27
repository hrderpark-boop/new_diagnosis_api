# diag_project/models/session.py

from typing import Optional, List, TYPE_CHECKING
from uuid import UUID, uuid4
from datetime import datetime, timezone
from enum import Enum
from sqlmodel import Field, SQLModel, Relationship
from sqlalchemy import Column, DateTime, func, text, ForeignKey
from diag_project.models.uuid_type import GUID

if TYPE_CHECKING:
    from diag_project.models.evaluation_result import EvaluationResult
    from diag_project.models.question_answer import QuestionAnswer

class SessionStatus(str, Enum):
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    ERROR = "error"

class SessionBase(SQLModel):
    status: SessionStatus = Field(default=SessionStatus.IN_PROGRESS)

class Session(SessionBase, table=True):
    # ⚠️ [비활성/병렬] 진단 대화 흐름의 세션이 아니다. 그건
    #   models/diagnosis_session.py 의 DiagnosisSession(diagnosis_sessions).
    #   이 Session(table="sessions")은 별도 서비스용 — 진단 세션을 여기서
    #   고치지 말 것. (파일럿 이후 정리 대상.)
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

    # 역방향: EvaluationResult.session 와 매칭 (1:N)
    evaluation_results: List["EvaluationResult"] = Relationship(back_populates="session")

    # 역방향: QuestionAnswer.session 와 매칭 (1:N)
    question_answers: List["QuestionAnswer"] = Relationship(back_populates="session")