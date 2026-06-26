# diag_project/models/message.py

from typing import Optional, Dict, Any 
from uuid import UUID, uuid4
from datetime import datetime, timezone
from enum import Enum

from sqlmodel import Field, Relationship, SQLModel
from sqlalchemy import Column, DateTime, func, text, ForeignKey, JSON, String
from diag_project.models.uuid_type import GUID 

# Enum 재정의 (또는 schemas와 공유)
class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"

class MessageBase(SQLModel):
    content: Optional[str] = Field(default=None, max_length=5000)
    role: MessageRole = Field(max_length=10)
    coach_response: Optional[Dict[str, Any]] = Field(default=None, sa_column=Column(JSON))
    
    competency_id: Optional[str] = Field(default=None, max_length=255, sa_column=Column(String(255), index=True))
    indicator_id: Optional[str] = Field(default=None, max_length=255, sa_column=Column(String(255), index=True))

class Message(MessageBase, table=True):
    __tablename__ = "messages"
    
    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(GUID(), primary_key=True, index=True)
    )
    
    # [THE FIX] 외래 키 타입을 UUID로 변경
    session_id: UUID = Field(sa_column=Column(GUID(), ForeignKey("sessions.id"), index=True))
    diagnosis_id: UUID = Field(sa_column=Column(GUID(), ForeignKey("diagnosis.id"), index=True))
    participant_id: UUID = Field(sa_column=Column(GUID(), ForeignKey("participants.id"), index=True))
    coach_persona_id: Optional[UUID] = Field(default=None, sa_column=Column(GUID(), ForeignKey("coach_personas.id"), index=True))
    coach_id: Optional[UUID] = Field(default=None, sa_column=Column(GUID(), ForeignKey("coaches.id"), index=True))
    question_id: Optional[UUID] = Field(default=None, sa_column=Column(GUID(), ForeignKey("diagnosis_questions.id"), index=True))

    created_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, default=func.now())
    )
    updated_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now())
    )
    
    # [THE FIX] 모든 Relationship 주석 처리
    # session: "Session" = Relationship(back_populates="messages")
    # diagnosis: "Diagnosis" = Relationship(back_populates="messages")
    # participant: "Participant" = Relationship(back_populates="messages")
    # coach_persona: "CoachPersona" = Relationship(back_populates="messages")
    # coach: "Coach" = Relationship(back_populates="messages")
    # question: "DiagnosisQuestion" = Relationship(back_populates="messages")