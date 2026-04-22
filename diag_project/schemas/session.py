# diag_project/schemas/session.py

from typing import List, Optional, Dict, Any
from uuid import UUID
from pydantic import BaseModel, Field, ConfigDict
from datetime import datetime
from enum import Enum

# 순환 참조 방지를 위해 Enum은 models에서 가져오거나 재정의
# 여기서는 models에 있는 것을 사용한다고 가정
from diag_project.models.session import SessionStatus 

# --- 기본 속성 ---
class SessionBase(BaseModel):
    status: SessionStatus = Field(default=SessionStatus.IN_PROGRESS)
    diagnosis_id: UUID
    participant_id: UUID
    coach_persona_id: UUID
    
    # 템플릿 ID 추가
    diagnosis_template_id: Optional[UUID] = None

    model_config = ConfigDict(from_attributes=True)

# --- 생성 요청 ---
class SessionCreate(SessionBase):
    pass

# --- 업데이트 요청 ---
class SessionUpdate(BaseModel):
    status: Optional[SessionStatus] = None
    
    model_config = ConfigDict(from_attributes=True)

# --- 응답 스키마 ---
class SessionResponse(SessionBase):
    id: UUID
    created_at: datetime
    updated_at: datetime


# --- (routes/diagnoses.py용 추가 스키마 - 필요하다면 여기에 정의) ---
class AnswerSubmit(BaseModel):
    question_id: str = Field(description="답변 대상 질문의 ID")
    answer_text: str = Field(description="사용자의 텍스트 답변")

class NextInteractionResponse(BaseModel):
    session_id: str
    coach_response_message: str
    coach_response_question_id: Optional[str] = None
    feedback_text: Optional[str] = None
    score: Optional[int] = None
    next_action: str
    current_competency_id: Optional[str] = None
    current_indicator_id: Optional[str] = None
    answered_indicator_ids_for_current_competency: List[str] = []
    is_session_completed: bool

class SessionSummaryResponse(BaseModel):
    session_id: str
    final_feedback: str
    overall_score: Optional[float] = None
    competency_scores: Dict[str, Optional[float]]

class SessionListResponse(BaseModel):
    items: List[SessionResponse]
    total: int
    skip: int
    limit: int
    
    model_config = ConfigDict(from_attributes=True)