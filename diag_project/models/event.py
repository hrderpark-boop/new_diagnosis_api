from typing import List, Optional
from uuid import UUID, uuid4
from datetime import datetime
from sqlmodel import Field, SQLModel, Column
from sqlalchemy import String, JSON, ForeignKey

from diag_project.models.uuid_type import GUID


class Event(SQLModel, table=True):
    __tablename__ = "events"

    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(GUID(), primary_key=True, index=True),
    )
    session_id: UUID = Field(
        sa_column=Column(GUID(), ForeignKey("diagnosis_sessions.id"), index=True),
    )
    chapter: str = Field(sa_column=Column(String(50), index=True))
    sequence_num: int

    situation: Optional[str] = None
    task: Optional[str] = None
    action: Optional[str] = None
    result: Optional[str] = None

    star_coverage: float = Field(default=0.0)
    probe_count: int = Field(default=0)
    is_complete: bool = Field(default=False)

    summary: Optional[str] = None
    key_person: Optional[str] = None
    time_context: Optional[str] = None
    core_action: Optional[str] = None

    tags: List[str] = Field(default_factory=list, sa_column=Column(JSON))

    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
