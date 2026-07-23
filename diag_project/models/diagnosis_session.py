# diag_project/models/diagnosis_session.py

from typing import Any, Dict, List, Optional, TYPE_CHECKING
from uuid import UUID, uuid4
from datetime import datetime
from sqlmodel import Field, SQLModel, Relationship, Column
from sqlalchemy import ForeignKey, JSON
from sqlalchemy.dialects import postgresql

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

    # ✅ [자가진단] 대화 시작 직전 대상자가 입력한 자기 평가.
    # 구조: {
    #   "scores": {"organization_management": 4.0, ... 5개 역량 (1.0~5.0)},
    #   "strength_weakness_text": "주관식 강점·약점 서술",
    #   "submitted_at": "ISO8601"
    # }
    # 키는 AI 채점 결과(radar_chart)와 동일한 영문 역량 키를 쓴다.
    # 그래야 '자가 인식 vs AI 분석' 갭을 역량 단위로 정렬해 비교할 수 있다.
    # PostgreSQL 에서는 JSONB(색인·연산 유리), 그 외 방언에서는 JSON 으로 매핑.
    self_assessment_data: Optional[Dict[str, Any]] = Field(
        default=None,
        sa_column=Column(JSON().with_variant(postgresql.JSONB, "postgresql"), nullable=True),
    )

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
    probe_type_used: Optional[str] = Field(default=None)
    instruction_used: Optional[str] = Field(default=None)

    # ML 학습(Fine-Tuning/RAG) 대비 메타데이터:
    # 세션 내 누적 user 턴 번호. user/model 메시지 쌍이 같은 값을 가져
    # (turn_index, chapter, instruction_used) 만으로 학습 레코드 페어링 가능.
    turn_index: Optional[int] = Field(default=None, index=True)

    # 관계 설정
    session: DiagnosisSession = Relationship(back_populates="messages")