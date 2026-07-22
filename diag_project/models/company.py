# diag_project/models/company.py
#
# B2B SaaS 멀티테넌시의 최상위 격리 단위인 '고객사(Company)' 엔티티.
# - Client Admin 은 자신의 company_id 에 속한 데이터만 조회할 수 있다.
# - Super Admin 은 company_id 제약 없이 전 고객사 데이터를 조회한다.

from typing import Optional
from uuid import UUID, uuid4
from datetime import datetime, timezone

from sqlmodel import Field, SQLModel
from sqlalchemy import Column, DateTime, func

from diag_project.models.uuid_type import GUID


class CompanyBase(SQLModel):
    name: str = Field(max_length=255, description="고객사 명 (예: 커넥트앤컴퍼니)")
    # 기존 participants.group_code 와 연결되는 고객사 식별 코드.
    # 진단 대상자가 로그인 시 입력한 group_code 로 소속사를 자동 매핑한다.
    code: str = Field(unique=True, index=True, max_length=50, description="고객사 코드")
    contact_email: Optional[str] = Field(default=None, max_length=255)
    is_active: bool = Field(default=True)


class Company(CompanyBase, table=True):
    __tablename__ = "companies"

    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(GUID(), primary_key=True, index=True),
    )

    created_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, default=func.now()),
    )
    updated_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now()),
    )
