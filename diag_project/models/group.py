# diag_project/models/group.py

from typing import Optional, List, TYPE_CHECKING
from uuid import UUID, uuid4
from datetime import datetime, timezone
from sqlmodel import Field, SQLModel, Relationship
from sqlalchemy import Column, DateTime, func, text
from diag_project.models.uuid_type import GUID

# [THE FIX] TYPE_CHECKING 제거

class GroupBase(SQLModel):
    name: str = Field(max_length=255, description="그룹 이름")
    group_code: str = Field(unique=True, index=True, max_length=50, description="그룹 고유 코드")

class Group(GroupBase, table=True):
    __tablename__ = "groups"

    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(GUID(), primary_key=True, index=True, server_default=text("LOWER(HEX(RANDOMBLOB(16)))")),
        description="그룹 고유 ID (UUID)"
    )

    created_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, default=func.now()),
    )
    updated_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now()),
    )

    # [THE FIX] 관계 주석 처리
    # participants: List["Participant"] = Relationship(
    #     back_populates="group",
    #     sa_relationship_kwargs={"cascade": "all, delete-orphan"}
    # )