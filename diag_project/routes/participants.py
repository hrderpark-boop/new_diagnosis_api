# diag_project/routes/participants.py

import uuid
import logging
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from pydantic import BaseModel

from diag_project.database import get_db
from diag_project.models.participant import Participant

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Participants"])

# 요청 모델
class LoginRequest(BaseModel):
    email: str
    password: str
    group_code: str
    name: Optional[str] = None

# 응답 모델
class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    participant_id: str
    name: str

# 로그인 API
@router.post("/token", response_model=TokenResponse)
async def login_for_access_token(
    form_data: LoginRequest, 
    db: AsyncSession = Depends(get_db)
):
    logger.info(f"🔐 로그인 시도: {form_data.email} / {form_data.name}")

    # 1. 사용자 조회
    query = select(Participant).where(Participant.email == form_data.email)
    result = await db.execute(query)
    participant = result.scalars().first()

    if not participant:
        # 2. 신규 회원가입 처리
        logger.info("✨ 신규 사용자 발견! 자동 회원가입 진행")
        
        new_participant = Participant(
            id=uuid.uuid4(),
            email=form_data.email,
            name=form_data.name if form_data.name else form_data.email.split("@")[0],
            group_code=form_data.group_code,
            password_hash="dummy_hashed_password", 
            created_at=datetime.now()
        )
        db.add(new_participant)
        await db.commit()
        await db.refresh(new_participant)
        participant = new_participant
        
    else:
        # 3. 기존 정보 업데이트
        is_changed = False
        if form_data.name and participant.name != form_data.name:
            participant.name = form_data.name
            is_changed = True
        if form_data.group_code and participant.group_code != form_data.group_code:
            participant.group_code = form_data.group_code
            is_changed = True
        
        if is_changed:
            db.add(participant)
            await db.commit()
            await db.refresh(participant)

    # 4. 토큰 응답
    return {
        "access_token": f"fake-jwt-token-for-{participant.id}",
        "token_type": "bearer",
        "participant_id": str(participant.id),
        "name": participant.name if participant.name else ""
    }