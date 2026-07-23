# diag_project/services/auth.py
#
# 어드민 인증(Authentication) & 권한(Authorization) 공통 레이어.
#
# 설계 원칙
#   1. 비밀번호는 bcrypt 해시로만 저장/검증한다. (평문 저장 절대 금지)
#   2. 토큰은 JWT(HS256). payload 에 sub(관리자 ID)·role·company_id 를 담아
#      매 요청마다 DB 조회 없이 1차 권한 판별이 가능하게 한다.
#      단, 실제 접근 허용은 항상 DB 의 최신 계정 상태(is_active)를 확인한다.
#      (탈퇴·비활성 계정의 잔여 토큰 무력화)
#   3. 데이터 격리는 '엔드포인트가 직접 회사 필터를 붙이는 방식'이 아니라
#      AdminContext.company_filter 를 통해 강제한다. Client Admin 은 자신의
#      company_id 를 벗어난 질의를 만들 수 없다.

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import UUID

import bcrypt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from diag_project.config import settings
from diag_project.database import get_db
from diag_project.models.admin_user import AdminUser, UserRole

logger = logging.getLogger(__name__)

# auto_error=False: 토큰이 없을 때 FastAPI 기본 403 대신
# 우리가 정의한 401 + 한글 메시지를 반환하기 위함.
_bearer = HTTPBearer(auto_error=False)

# bcrypt 는 72바이트를 초과하는 입력을 처리하지 못한다(라이브러리에 따라 예외).
_BCRYPT_MAX_BYTES = 72


# ---------------------------------------------------------------------------
# 비밀번호 해싱
# ---------------------------------------------------------------------------
def _truncate(password: str) -> bytes:
    return password.encode("utf-8")[:_BCRYPT_MAX_BYTES]


def hash_password(password: str) -> str:
    """평문 비밀번호를 bcrypt 해시 문자열로 변환한다."""
    return bcrypt.hashpw(_truncate(password), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: Optional[str]) -> bool:
    """평문 비밀번호와 저장된 해시를 비교한다. 형식이 깨진 해시는 False."""
    if not hashed:
        return False
    try:
        return bcrypt.checkpw(_truncate(plain), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# 임시 비밀번호 문자 집합.
# 사람이 눈으로 읽고 옮겨 적는 값이므로 혼동하기 쉬운 문자(0/O, 1/l/I)는 제외한다.
_TEMP_PW_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz23456789"
_TEMP_PW_SYMBOLS = "!@#$%^&*"


def generate_temp_password(length: int = 14) -> str:
    """계정 발급용 임시 비밀번호를 생성한다.

    난수는 반드시 secrets(CSPRNG)를 사용한다. random 모듈은 예측 가능해
    자격증명 생성에 쓰면 안 된다.
    """
    length = max(12, length)
    chars = [
        secrets.choice(_TEMP_PW_ALPHABET) for _ in range(length - 2)
    ]
    # 기호와 숫자를 각각 최소 1개 보장한 뒤 위치를 섞는다.
    chars.append(secrets.choice(_TEMP_PW_SYMBOLS))
    chars.append(secrets.choice("23456789"))
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


# ---------------------------------------------------------------------------
# JWT 발급 / 검증
# ---------------------------------------------------------------------------
def create_access_token(admin: AdminUser) -> str:
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
    )
    payload = {
        "sub": str(admin.id),
        "email": admin.email,
        "role": admin.role,
        "company_id": str(admin.company_id) if admin.company_id else None,
        "exp": expire,
        "typ": "admin",
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
    except JWTError as exc:
        logger.info("JWT 검증 실패: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="인증 토큰이 유효하지 않거나 만료되었습니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ---------------------------------------------------------------------------
# 요청 컨텍스트 — 권한과 데이터 격리 범위를 함께 들고 다닌다
# ---------------------------------------------------------------------------
@dataclass
class AdminContext:
    admin: AdminUser

    @property
    def role(self) -> str:
        return self.admin.role

    @property
    def is_super_admin(self) -> bool:
        return self.admin.role == UserRole.SUPER_ADMIN.value

    @property
    def company_id(self) -> Optional[UUID]:
        return self.admin.company_id

    def scope_query(self, query, company_column):
        """질의에 회사 격리 조건을 강제 적용한다.

        Super Admin  : 필터 없음 (전 고객사 조회)
        Client Admin : 자신의 company_id 로 고정 (요청 파라미터로 우회 불가)
        """
        if self.is_super_admin:
            return query
        return query.where(company_column == self.admin.company_id)

    def assert_can_access_company(self, company_id: Optional[UUID]) -> None:
        """특정 고객사 리소스 접근 가능 여부. 위반 시 403."""
        if self.is_super_admin:
            return
        if company_id is None or company_id != self.admin.company_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="해당 고객사의 데이터에 접근할 권한이 없습니다.",
            )


# ---------------------------------------------------------------------------
# FastAPI 의존성
# ---------------------------------------------------------------------------
async def get_current_admin(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
) -> AdminContext:
    """유효한 어드민 토큰을 요구한다. 모든 /admin 엔드포인트의 기본 관문."""
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="관리자 인증이 필요합니다.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_token(credentials.credentials)
    admin_id = payload.get("sub")
    if not admin_id or payload.get("typ") != "admin":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="관리자 토큰이 아닙니다.",
        )

    try:
        admin_uuid = UUID(str(admin_id))
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="토큰의 사용자 식별자가 올바르지 않습니다.",
        )

    # 토큰이 유효해도 계정이 비활성화됐으면 즉시 차단한다.
    result = await db.execute(select(AdminUser).where(AdminUser.id == admin_uuid))
    admin = result.scalars().first()
    if not admin or not admin.is_active:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="비활성화되었거나 존재하지 않는 계정입니다.",
        )

    return AdminContext(admin=admin)


async def require_super_admin(
    ctx: AdminContext = Depends(get_current_admin),
) -> AdminContext:
    """운영자(Super Admin) 전용 엔드포인트 가드."""
    if not ctx.is_super_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="운영자(Super Admin) 권한이 필요합니다.",
        )
    return ctx
