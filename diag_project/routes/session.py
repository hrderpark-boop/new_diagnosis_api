import logging
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status, Response # 👈 Response 임포트 추가
from sqlalchemy.ext.asyncio import AsyncSession # 👈 AsyncSession 임포트
from uuid import UUID 

# ✅ 순환 참조 해결
from diag_project.database import get_db 
from diag_project.services import session as session_service
from diag_project.services import participant as participant_service 
from diag_project.services import coach as coach_service 

from diag_project.schemas.session import (
    SessionCreate,
    SessionUpdate,
    SessionResponse,
    SessionListResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/session",
    tags=["Session"],
    responses={404: {"description": "Not found"}},
)

# ✅ async def로 변경
@router.post("/", response_model=SessionResponse, status_code=status.HTTP_201_CREATED)
async def create_session_api(session: SessionCreate, db: AsyncSession = Depends(get_db)):
    """
    새로운 진단 세션을 생성합니다.
    """
    # ✅ await 추가
    if not await participant_service.get_participant(db, participant_id=session.participant_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Participant with ID '{session.participant_id}' not found.")
    # ✅ await 추가
    if not await coach_service.get_coach(db, coach_id=session.coach_id):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=f"Coach with ID '{session.coach_id}' not found.")

    # ✅ await 추가
    db_session = await session_service.create_session(db=db, session=session)
    if db_session is None:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Failed to create session.")

    logger.info(f"세션 생성: ID={db_session.id}, 참가자_ID={db_session.participant_id}, 코치_ID={db_session.coach_id}")
    return db_session

# ✅ async def로 변경
@router.get("/", response_model=SessionListResponse)
async def get_sessions_api(
    participant_id: Optional[UUID] = None,
    coach_id: Optional[UUID] = None,
    is_completed: Optional[bool] = None,
    skip: int = 0,
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    """
    모든 진단 세션 목록을 조회합니다. 필터링 및 페이지네이션을 지원합니다.
    """
    # ✅ await 추가
    sessions = await session_service.get_sessions(
        db=db,
        participant_id=participant_id,
        coach_id=coach_id,
        is_completed=is_completed,
        skip=skip,
        limit=limit
    )
    return {"items": sessions, "total": len(sessions), "skip": skip, "limit": limit}

# ✅ async def로 변경
@router.get("/{session_id}", response_model=SessionResponse)
async def get_session_api(session_id: UUID, db: AsyncSession = Depends(get_db)):
    """
    ID로 특정 진단 세션을 조회합니다.
    """
    # ✅ await 추가
    db_session = await session_service.get_session(db=db, session_id=session_id)
    if db_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    return db_session

# ✅ async def로 변경
@router.put("/{session_id}", response_model=SessionResponse)
async def update_session_api(
    session_id: UUID,
    session_update: SessionUpdate,
    db: AsyncSession = Depends(get_db)
):
    """
    ID로 특정 진단 세션을 업데이트합니다.
    """
    # ✅ await 추가
    updated_session = await session_service.update_session(db=db, session_id=session_id, session_update=session_update)
    if updated_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    logger.info(f"세션 업데이트: ID={updated_session.id}")
    return updated_session

# ✅ async def로 변경
@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_session_api(session_id: UUID, db: AsyncSession = Depends(get_db)):
    """
    ID로 특정 진단 세션을 삭제합니다.
    """
    # ✅ await 추가
    deleted_session = await session_service.delete_session(db=db, session_id=session_id)
    if deleted_session is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Session not found")
    
    logger.info(f"세션 삭제: ID={session_id}")
    return Response(status_code=status.HTTP_204_NO_CONTENT)