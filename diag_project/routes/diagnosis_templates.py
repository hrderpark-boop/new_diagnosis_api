# diag_project/routes/diagnosis_templates.py

import logging
from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Response
from sqlalchemy.ext.asyncio import AsyncSession

from diag_project.database import get_db
from diag_project.services import diagnosis_templates as template_service
# [THE FIX] question_service 임포트 추가 (questions 조회용)
from diag_project.services import diagnosis_question as question_service

# 스키마 임포트
from diag_project.schemas.diagnosis_template import (
    DiagnosisTemplateCreate,
    DiagnosisTemplateUpdate,
    DiagnosisTemplateResponse,
    DiagnosisTemplateDetailResponse,
    DiagnosisTemplateListResponse
)
from diag_project.schemas.diagnosis_question import DiagnosisQuestionResponse 
from diag_project.models.participant import Participant
from diag_project.security import get_current_participant

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/diagnosis-templates",
    tags=["Diagnosis Templates"],
    responses={404: {"description": "Not found"}},
)

@router.post("/", response_model=DiagnosisTemplateResponse, status_code=status.HTTP_201_CREATED)
async def create_template(
    template: DiagnosisTemplateCreate, 
    db: AsyncSession = Depends(get_db),
    current_user: Participant = Depends(get_current_participant)
):
    return await template_service.create_template(db=db, template=template)

@router.get("/", response_model=DiagnosisTemplateListResponse)
async def read_templates_api(
    skip: int = 0, 
    limit: int = 100, 
    db: AsyncSession = Depends(get_db),
    # current_user: Participant = Depends(get_current_participant) # 필요시 주석 해제
):
    templates, total = await template_service.get_templates(db=db, skip=skip, limit=limit)
    
    # [THE FIX] Pydantic 모델로 명시적 변환 (ValidationError 방지)
    items = [DiagnosisTemplateResponse.model_validate(t, from_attributes=True) for t in templates]
    
    return DiagnosisTemplateListResponse(items=items, total=total, skip=skip, limit=limit)

@router.get("/{template_id}", response_model=DiagnosisTemplateDetailResponse)
async def read_template(
    template_id: str, 
    db: AsyncSession = Depends(get_db),
    current_user: Participant = Depends(get_current_participant)
):
    try:
        uuid_id = UUID(template_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")

    db_template = await template_service.get_template(db=db, template_id=uuid_id)
    
    if not db_template:
        raise HTTPException(status_code=404, detail="Template not found")
    
    return db_template

# [THE FIX] 404 에러 해결 (누락된 엔드포인트 추가)
@router.get("/{template_id}/questions", response_model=List[DiagnosisQuestionResponse])
async def read_questions_by_template_api(
    template_id: str,
    db: AsyncSession = Depends(get_db),
):
    try:
        validated_uuid = UUID(template_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid UUID format")
        
    questions = await question_service.get_questions_by_template(db=db, template_id=validated_uuid)
    return questions

@router.patch("/{template_id}", response_model=DiagnosisTemplateResponse)
async def update_template(
    template_id: str, 
    template_update: DiagnosisTemplateUpdate, 
    db: AsyncSession = Depends(get_db),
    current_user: Participant = Depends(get_current_participant)
):
    try:
        uuid_id = UUID(template_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")

    db_template = await template_service.update_template(db=db, template_id=uuid_id, template_update=template_update)
    if not db_template:
        raise HTTPException(status_code=404, detail="Template not found")
    return db_template

@router.delete("/{template_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_template(
    template_id: str, 
    db: AsyncSession = Depends(get_db),
    current_user: Participant = Depends(get_current_participant)
):
    try:
        uuid_id = UUID(template_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")

    deleted_id = await template_service.delete_template(db=db, template_id=uuid_id)
    if not deleted_id:
        raise HTTPException(status_code=404, detail="Template not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)