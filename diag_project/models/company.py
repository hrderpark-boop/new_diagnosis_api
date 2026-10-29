# diag_project/models/company.py
#
# B2B SaaS 멀티테넌시의 최상위 격리 단위인 '고객사(Company)' 엔티티.
# - Client Admin 은 자신의 company_id 에 속한 데이터만 조회할 수 있다.
# - Super Admin 은 company_id 제약 없이 전 고객사 데이터를 조회한다.

from typing import Optional
from uuid import UUID, uuid4
from datetime import date, datetime, timezone

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
    # (2026-10-15) 고객사별 LLM provider('gemini'|'claude'). null 이면 환경변수(LLM_PROVIDER) 기본값.
    #   세션 생성 시 diagnosis_sessions.llm_provider 에 복사·고정된다(세션 중간에 바뀌지 않음).
    # (2026-10-29) 새 레코드 기본값 claude. 기존 null 레코드는 환경 기본값(claude)으로 풀린다.
    llm_provider: Optional[str] = Field(default="claude", max_length=20)
    # (2026-10-29) 조직 참여 코드 접두어(영문 1~3자, 예: A → 영업1팀 AS1). null 이면 조직 코드 미사용.
    #   조직 단위가 생긴 뒤에는 바꿀 수 없다(이미 배포한 코드가 깨지므로). 규칙: services/org_codes.py
    org_prefix: Optional[str] = Field(default=None, max_length=10)
    # (2026-10-29) 진단 기간(시작·종료일, 포함). HR 관리자·마스터가 정한다. 진단 현황의 '기간 내 추이' 기준.
    diagnosis_start: Optional[date] = Field(default=None)
    diagnosis_end: Optional[date] = Field(default=None)


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
