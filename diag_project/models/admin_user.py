# diag_project/models/admin_user.py
#
# 관리자 계정 모델. 진단 대상자(participants)와 테이블을 분리해
# '어드민 인증'과 '진단 참여자 로그인'의 보안 경계를 명확히 나눈다.
#
# 권한(Role) 체계
#   - super_admin  : 운영자. 전 고객사 데이터·시스템 통계 접근 (company_id = None)
#   - client_admin : 고객사 HR 담당자. 자사 데이터만 접근 (company_id 필수)
#   - user         : 일반 진단 대상자. 어드민 접근 불가 (participants 테이블 사용)

from typing import Optional
from uuid import UUID, uuid4
from datetime import datetime, timezone
from enum import Enum

from sqlmodel import Field, SQLModel
from sqlalchemy import Column, DateTime, ForeignKey, func

from diag_project.models.uuid_type import GUID


class UserRole(str, Enum):
    SUPER_ADMIN = "super_admin"
    CLIENT_ADMIN = "client_admin"
    USER = "user"


class AdminUserBase(SQLModel):
    email: str = Field(unique=True, index=True, max_length=255)
    name: Optional[str] = Field(default=None, max_length=100)
    role: str = Field(default=UserRole.CLIENT_ADMIN.value, max_length=30, index=True)
    is_active: bool = Field(default=True)


class AdminUser(AdminUserBase, table=True):
    __tablename__ = "admin_users"

    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(GUID(), primary_key=True, index=True),
    )

    # bcrypt 해시. 평문 비밀번호는 어떤 경우에도 저장하지 않는다.
    password_hash: str = Field(max_length=255)

    # super_admin 은 특정 고객사에 종속되지 않으므로 NULL 을 허용한다.
    company_id: Optional[UUID] = Field(
        default=None,
        sa_column=Column(GUID(), ForeignKey("companies.id"), nullable=True, index=True),
    )

    last_login_at: Optional[datetime] = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    created_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, default=func.now()),
    )
    updated_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now()),
    )

    @property
    def is_super_admin(self) -> bool:
        return self.role == UserRole.SUPER_ADMIN.value
