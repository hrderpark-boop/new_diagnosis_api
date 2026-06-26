# diag_project/models/question_answer.py

from typing import Optional, List
from uuid import UUID, uuid4
from datetime import datetime, timezone

from sqlmodel import Field, Relationship, SQLModel
from sqlalchemy import func, Column, DateTime, text, ForeignKey
# ⚠️ 'uuid_type' 임포트 경로 수정 (models 폴더 내)
from .uuid_type import GUID 
import uuid 

# --- QuestionAnswer (질문-답변) 모델 ---
# (참고: ParticipantAnswer와는 다른 모델일 수 있습니다.
#  ImportError를 해결하기 위해 이 모델을 정의합니다.)

class QuestionAnswerBase(SQLModel):
    answer_text: str = Field(max_length=4000, description="AI 또는 관리자가 생성한 답변 내용")
    
    # FK (Create 스키마용)
    session_id: str = Field(max_length=36)
    diagnosis_question_id: str = Field(max_length=36)
    

class QuestionAnswer(QuestionAnswerBase, table=True):
    __tablename__ = "question_answers" 

    id: str = Field(
        default_factory=lambda: str(uuid4()),
        max_length=36,
        sa_column=Column(GUID(), primary_key=True, index=True),
    )

    # Foreign Keys (Table)
    session_id: str = Field(
        sa_column=Column(GUID(), ForeignKey("sessions.id"), index=True)
    )
    diagnosis_question_id: str = Field(
        sa_column=Column(GUID(), ForeignKey("diagnosis_questions.id"), index=True)
    )

    created_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, default=func.now()),
    )
    
    # ⚠️ 'session.py'의 'Session' 모델에
    #    'question_answers: List["QuestionAnswer"] = Relationship(back_populates="session")'
    #    가 필요합니다.
    session: "Session" = Relationship(back_populates="question_answers")
                                                 
    # ⚠️ 'diagnosis_question.py'의 'DiagnosisQuestion' 모델에
    #    'question_answers_ref: List["QuestionAnswer"] = Relationship(back_populates="diagnosis_question")'
    #    (또는 다른 이름)이 필요합니다.
    diagnosis_question: "DiagnosisQuestion" = Relationship(back_populates="question_answers_ref")


# ==========================================================
# Pydantic 스키마 (서비스 레이어가 임포트할 대상)
# ==========================================================

class QuestionAnswerCreate(QuestionAnswerBase):
    pass

class QuestionAnswerResponse(QuestionAnswerBase):
    id: UUID
    session_id: UUID
    diagnosis_question_id: UUID
    created_at: datetime

class QuestionAnswerUpdate(SQLModel):
    answer_text: Optional[str] = Field(default=None, max_length=4000)