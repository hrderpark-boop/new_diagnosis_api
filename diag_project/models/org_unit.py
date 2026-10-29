# diag_project/models/org_unit.py
#
# 고객사 안의 조직 단위(본부·팀). 단위마다 참여 코드를 하나씩 발급한다.
#   코드 규칙: 회사 접두어 + 본부 코드 + 팀 번호. 예) A회사 영업본부(S) 영업1팀 → "AS1"
#   - 본부 단위 코드: 접두어 + 본부 코드  (예: "AS")
#   - 팀 단위 코드  : 본부 코드 + 번호     (예: "AS1", "AS10")
# 참여자가 로그인 화면의 그룹 코드 칸에 이 코드를 넣으면 회사와 소속이 함께 정해진다
# (routes/participants.py 로그인 게이트). 코드 생성·검증 규칙은 services/org_codes.py.

from typing import Optional
from uuid import UUID, uuid4
from datetime import datetime, timezone

from sqlmodel import Field, SQLModel
from sqlalchemy import Column, DateTime, ForeignKey, func

from diag_project.models.uuid_type import GUID


class OrgUnit(SQLModel, table=True):
    __tablename__ = "org_units"

    id: UUID = Field(
        default_factory=uuid4,
        sa_column=Column(GUID(), primary_key=True, index=True),
    )
    company_id: UUID = Field(
        sa_column=Column(GUID(), ForeignKey("companies.id"), nullable=False, index=True),
    )
    # 상위 단위(팀 → 본부). 본부는 None.
    parent_id: Optional[UUID] = Field(
        default=None,
        sa_column=Column(GUID(), ForeignKey("org_units.id"), nullable=True, index=True),
    )
    level: str = Field(max_length=20, description="division(본부) | team(팀)")
    name: str = Field(max_length=100, description="표시 이름 (예: 영업본부, 영업1팀)")
    # 이 단위만의 짧은 코드. 본부는 영문 1~2자(S), 팀은 번호('1')
    short_code: str = Field(max_length=10)
    # 참여 코드 전체(대문자, 전 고객사에서 유일). 로그인 입력과 같은 정규화(strip+upper)로 저장한다.
    code: str = Field(unique=True, index=True, max_length=20)
    sort_order: int = Field(default=0)
    is_active: bool = Field(default=True)

    created_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, default=func.now()),
    )
    updated_at: Optional[datetime] = Field(
        default_factory=lambda: datetime.now(timezone.utc),
        sa_column=Column(DateTime(timezone=True), nullable=False, default=func.now(), onupdate=func.now()),
    )
