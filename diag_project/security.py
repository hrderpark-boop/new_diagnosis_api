# diag_project/security.py

import bcrypt  # passlib 대신 bcrypt 직접 사용
from datetime import datetime, timedelta, timezone
from typing import Optional, Any, Union
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.ext.asyncio import AsyncSession 

from diag_project.config import settings
from diag_project.database import get_db 

# --- OAuth2 스킴 정의 ---
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/participants/token")

# --- 비밀번호 유틸리티 (passlib 제거 -> bcrypt 직접 구현) ---
def verify_password(plain_password: str, hashed_password: str) -> bool:
    """일반 비밀번호와 해시된 비밀번호가 일치하는지 확인합니다."""
    try:
        # DB에 저장된 해시가 문자열(str)이라면 bytes로 인코딩 필요
        if isinstance(hashed_password, str):
            hashed_password_bytes = hashed_password.encode('utf-8')
        else:
            hashed_password_bytes = hashed_password
            
        # 입력된 비밀번호도 bytes로 인코딩
        plain_password_bytes = plain_password.encode('utf-8')

        return bcrypt.checkpw(plain_password_bytes, hashed_password_bytes)
    except Exception as e:
        print(f"Password verification failed: {e}")
        return False

def get_password_hash(password: str) -> str:
    """일반 비밀번호를 해시합니다."""
    pwd_bytes = password.encode('utf-8')
    salt = bcrypt.gensalt()
    hashed_bytes = bcrypt.hashpw(pwd_bytes, salt)
    return hashed_bytes.decode('utf-8')  # DB 저장을 위해 문자열로 변환


# --- JWT 토큰 유틸리티 (기존 로직 유지) ---
def create_access_token(data: dict, expires_delta: Optional[timedelta] = None):
    """JWT 액세스 토큰을 생성합니다."""
    to_encode = data.copy()
    if expires_delta:
        expire = datetime.now(timezone.utc) + expires_delta
    else:
        expire = datetime.now(timezone.utc) + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )
    to_encode.update({"exp": expire})
    encoded_jwt = jwt.encode(
        to_encode, settings.SECRET_KEY, algorithm=settings.ALGORITHM
    )
    return encoded_jwt

def decode_token(token: str) -> Optional[dict]:
    """JWT 토큰을 디코딩하고 페이로드를 반환합니다."""
    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        return payload
    except JWTError:
        return None

async def get_current_participant(
    token: str = Depends(oauth2_scheme), 
    db: AsyncSession = Depends(get_db)
): # Type hint 제거 (순환 참조 방지용으로 import를 안에서 하므로)
    """
    토큰을 검증하고 현재 로그인된 참가자(Participant) 객체를 반환합니다.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    
    payload = decode_token(token)
    if payload is None:
        raise credentials_exception
        
    participant_id: str = payload.get("sub")
    if participant_id is None:
        raise credentials_exception
        
    try:
        uuid_id = UUID(participant_id)
    except ValueError:
        raise credentials_exception

    # [THE FIX] 함수 내부 import 유지 (순환 참조 방지)
    from diag_project.services import participant as participant_service

    # 서비스 계층 호출
    participant = await participant_service.get_participant(db, uuid_id)
    
    if participant is None:
        raise credentials_exception
        
    return participant