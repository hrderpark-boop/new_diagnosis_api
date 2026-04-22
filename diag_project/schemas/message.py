# diag_project/schemas/message.py

from typing import Optional, List, Dict, Any
from uuid import UUID
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict
from enum import Enum

class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"

class MessageBase(BaseModel):
    content: Optional[str] = Field(None, max_length=5000)
    role: MessageRole
    coach_response: Optional[Dict[str, Any]] = None
    
    session_id: UUID
    diagnosis_id: UUID
    participant_id: UUID
    
    coach_persona_id: Optional[UUID] = None
    coach_id: Optional[UUID] = None
    question_id: Optional[UUID] = None
    
    competency_id: Optional[str] = None
    indicator_id: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)

class MessageCreate(MessageBase):
    pass

class MessageResponse(MessageBase):
    id: UUID
    created_at: datetime
    updated_at: datetime

class MessageListResponse(BaseModel):
    items: List[MessageResponse]
    total: int
    skip: int
    limit: int
    
    model_config = ConfigDict(from_attributes=True)