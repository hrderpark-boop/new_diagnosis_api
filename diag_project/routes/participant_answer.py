# diag_project/routes/participant_answer.py (수정 반영)

from typing import Optional, TYPE_CHECKING
from uuid import UUID, uuid4
from datetime import datetime, timezone

from sqlmodel import Field, Relationship, SQLModel
from sqlalchemy import Column, DateTime, func, text, ForeignKey
from diag_project.models.uuid_type import GUID

# [THE FIX] TYPE_CHECKING 제거

# Base 스키마
class ParticipantAnswerBase(SQLModel):
    answer_text: str = Field(description="사용자 답변 내용")
    selected_choice_id: Optional[str] = Field(default=None, max_length=36)
    # 외래키는 아래 클래스에서 UUID로 정의

class ParticipantAnswer(ParticipantAnswerBase, table=True):
    __tablename__ = "participant_answers"

    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(GUID(), primary_key=True, index=True)
    )

    # 외래 키
    session_id: UUID = Field(sa_column=Column(GUID(), ForeignKey("sessions.id"), index=True))
    diagnosis_id: UUID = Field(sa_column=Column(GUID(), ForeignKey("diagnosis.id"), index=True))
    participant_id: UUID = Field(sa_column=Column(GUID(), ForeignKey("participants.id"), index=True))
    question_id: UUID = Field(sa_column=Column(GUID(), ForeignKey("diagnosis_questions.id"), index=True))
    
    created_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, default=func.now())
    )
    updated_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now())
    )

    # [THE FIX] 모든 Relationship 주석 처리
    # session: "Session" = Relationship(back_populates="participant_answers")
    # diagnosis: "Diagnosis" = Relationship(back_populates="participant_answers")
    # participant: "Participant" = Relationship(back_populates="participant_answers")
    # question: "DiagnosisQuestion" = Relationship(back_populates="participant_answers")

# Pydantic 스키마 (이 파일에 함께 두거나 schemas로 분리 가능, 일단 여기에 유지)
class ParticipantAnswerCreate(ParticipantAnswerBase):
    pass

class ParticipantAnswerResponse(ParticipantAnswerBase):
    id: UUID
    session_id: UUID
    diagnosis_id: UUID
    participant_id: UUID
    question_id: UUID
    created_at: datetime
    updated_at: datetime