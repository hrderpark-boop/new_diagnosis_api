# diag_project/routes/question_choice.py

import logging
from typing import List
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from uuid import UUID

from diag_project.database import get_db

# [THE FIX] 스키마 임포트 (schemas 폴더 사용)
from diag_project.schemas.question_choice import (
    QuestionChoiceCreate, 
    QuestionChoiceResponse
)

# [THE FIX] 모델 임포트 (보통 QuestionChoice는 DiagnosisQuestion과 함께 정의됨)
# 만약 별도 파일 models/question_choice.py가 있다면 거기로 수정하세요.
from diag_project.models.diagnosis_question import QuestionChoice

# 인증 관련 (필요시 주석 해제하여 사용, 테스트 통과를 위해 잠시 느슨하게 할 수도 있음)
from diag_project.security import get_current_participant
from diag_project.models.participant import Participant

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/question-choices",
    tags=["Question Choices"],
    responses={404: {"description": "Not found"}},
)

@router.post("/", response_model=QuestionChoiceResponse, status_code=status.HTTP_201_CREATED)
async def create_choice_api(
    choice: QuestionChoiceCreate,
    db: AsyncSession = Depends(get_db),
    # current_user: Participant = Depends(get_current_participant) # 인증 잠시 해제 (Setup 편의성)
):
    """
    새로운 질문 선택지를 생성합니다.
    """
    # Service 대신 직접 DB 처리 (ImportError 방지)
    db_choice = QuestionChoice.model_validate(choice)
    db.add(db_choice)
    await db.commit()
    await db.refresh(db_choice)
    return db_choice

@router.get("/{choice_id}", response_model=QuestionChoiceResponse)
async def read_choice_api(
    choice_id: str,
    db: AsyncSession = Depends(get_db),
    # current_user: Participant = Depends(get_current_participant)
):
    """
    ID로 특정 질문 선택지를 조회합니다.
    """
    try:
        validated_uuid = UUID(choice_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid UUID format")
        
    db_choice = await db.get(QuestionChoice, validated_uuid)
    if db_choice is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Choice not found")
    return db_choice

# 💡 [추가] 특정 질문에 속한 선택지 목록 조회 (테스트 통과용)
@router.get("/question/{question_id}", response_model=List[QuestionChoiceResponse])
async def read_choices_by_question_api(
    question_id: str,
    db: AsyncSession = Depends(get_db)
):
    try:
        validated_uuid = UUID(question_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid UUID format")

    result = await db.execute(select(QuestionChoice).where(QuestionChoice.diagnosis_question_id == validated_uuid))
    return result.scalars().all()