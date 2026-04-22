# diag_project/routes/coach_persona.py

from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Response
from sqlalchemy.ext.asyncio import AsyncSession

from diag_project.database import get_db
from diag_project.services import coach_persona as persona_service

# [THE FIX] 스키마는 schemas 패키지에서 임포트
from diag_project.schemas.coach_persona import (
    CoachPersonaCreate, 
    CoachPersonaUpdate, 
    CoachPersonaResponse,
    CoachPersonaListResponse
)
# 모델 임포트 (DB용)
from diag_project.models.coach_persona import CoachPersona

# 인증 관련
from diag_project.security import get_current_participant
from diag_project.models.participant import Participant

router = APIRouter(
    prefix="/api/v1/coach-personas",
    tags=["Coach Personas"],
    responses={404: {"description": "Not found"}},
)

@router.post("/", response_model=CoachPersonaResponse, status_code=status.HTTP_201_CREATED)
async def create_persona(
    persona: CoachPersonaCreate, 
    db: AsyncSession = Depends(get_db),
    # [THE FIX] 인증 의존성 (필요시 활성화)
    # current_user: Participant = Depends(get_current_participant) 
):
    return await persona_service.create_persona(db=db, persona=persona)

@router.get("/", response_model=CoachPersonaListResponse)
async def read_personas(skip: int = 0, limit: int = 100, db: AsyncSession = Depends(get_db)):
    personas, total = await persona_service.get_personas(db=db, skip=skip, limit=limit)
    return CoachPersonaListResponse(items=personas, total=total, skip=skip, limit=limit)

@router.get("/{persona_id}", response_model=CoachPersonaResponse)
async def read_persona(persona_id: str, db: AsyncSession = Depends(get_db)):
    try:
        uuid_id = UUID(persona_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")
        
    db_persona = await persona_service.get_persona(db=db, persona_id=uuid_id)
    if not db_persona:
        raise HTTPException(status_code=404, detail="Persona not found")
    return db_persona

@router.patch("/{persona_id}", response_model=CoachPersonaResponse)
async def update_persona(persona_id: str, persona_update: CoachPersonaUpdate, db: AsyncSession = Depends(get_db)):
    try:
        uuid_id = UUID(persona_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")

    db_persona = await persona_service.update_persona(db=db, persona_id=uuid_id, persona_update=persona_update)
    if not db_persona:
        raise HTTPException(status_code=404, detail="Persona not found")
    return db_persona

@router.delete("/{persona_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_persona(persona_id: str, db: AsyncSession = Depends(get_db)):
    try:
        uuid_id = UUID(persona_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")

    deleted_id = await persona_service.delete_persona(db=db, persona_id=uuid_id)
    if not deleted_id:
        raise HTTPException(status_code=404, detail="Persona not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)