# diag_project/models/diagnosis_session.py

from typing import List, Optional, TYPE_CHECKING
from uuid import UUID, uuid4
from datetime import datetime
from sqlmodel import Field, SQLModel, Relationship, Column
from sqlalchemy import ForeignKey

from diag_project.models.uuid_type import GUID

# 순환 참조 방지 (Participant가 필요한 경우)
if TYPE_CHECKING:
    from diag_project.models.participant import Participant

# -----------------------------------------------------------------------------
# 진단 세션 모델 (채팅방)
# -----------------------------------------------------------------------------
class DiagnosisSession(SQLModel, table=True):
    __tablename__ = "diagnosis_sessions"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    
    # 참여자 (User) FK
    user_id: UUID = Field(foreign_key="participants.id")
    
    # 담당 코치 FK
    coach_id: UUID = Field(foreign_key="coaches.id")
    
    # 어떤 템플릿으로 진단 중인지
    diagnosis_template_id: Optional[UUID] = Field(default=None, foreign_key="diagnosis_templates.id")
    
    # 상태 (예: in_progress, completed)
    status: str = Field(default="in_progress")
    
    # ✅ [핵심 추가] 현재 진행 중인 대화 주제 (기본값: General)
    # 이 필드가 있어야 "조직관리"로 넘어갔다는 사실을 DB가 기억합니다.
    current_topic: str = Field(default="General")

    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    # 관계 설정 (User N:1)
    user: Optional["Participant"] = Relationship(back_populates="sessions")

    # 관계 설정 (Message 1:N)
    messages: List["ChatMessage"] = Relationship(back_populates="session", sa_relationship_kwargs={"cascade": "all, delete-orphan"})


# -----------------------------------------------------------------------------
# 채팅 메시지 모델 (말풍선)
# -----------------------------------------------------------------------------
class ChatMessage(SQLModel, table=True):
    __tablename__ = "chat_messages"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    
    # 어느 세션(채팅방)에 속해 있는지
    session_id: UUID = Field(foreign_key="diagnosis_sessions.id")
    
    # 화자 (user 또는 model)
    role: str 
    
    # 내용
    content: str
    
    created_at: datetime = Field(default_factory=datetime.now)

    # Phase 3-A: Event 연결 및 분류 메타
    event_id: Optional[UUID] = Field(
        default=None,
        sa_column=Column(GUID(), ForeignKey("events.id"), nullable=True, index=True),
    )
    chapter: Optional[str] = Field(default=None)
    competency_key: Optional[str] = Field(default=None)
    msg_type: Optional[str] = Field(default=None)

    # 관계 설정
    session: DiagnosisSession = Relationship(back_populates="messages")