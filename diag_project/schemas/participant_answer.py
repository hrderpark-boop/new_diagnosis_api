# diag_project/schemas/participant_answer.py (수정본)

from typing import Optional
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict

# --- 기본 속성 ---
class ParticipantAnswerBase(BaseModel):
    answer_text: str = Field(..., description="사용자 답변 내용")
    selected_choice_id: Optional[str] = Field(None, max_length=36)
    
    model_config = ConfigDict(from_attributes=True)

# --- 생성 요청 ---
class ParticipantAnswerCreate(ParticipantAnswerBase):
    session_id: UUID
    diagnosis_id: UUID
    participant_id: UUID
    question_id: UUID

# --- 응답 스키마 ---
class ParticipantAnswerResponse(ParticipantAnswerBase):
    id: UUID
    session_id: UUID
    diagnosis_id: UUID
    participant_id: UUID
    question_id: UUID
    created_at: datetime
    updated_at: datetime