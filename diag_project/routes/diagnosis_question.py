# diag_project/routes/diagnosis_question.py

from typing import List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from diag_project.database import get_db
from diag_project.services import diagnosis_question as question_service

from diag_project.schemas.diagnosis_question import (
    DiagnosisQuestionCreate, 
    DiagnosisQuestionUpdate, 
    DiagnosisQuestionResponse
)
# [THE FIX] 선택지 관련 임포트 추가
from diag_project.models.diagnosis_question import QuestionChoice, DiagnosisQuestion
from diag_project.schemas.question_choice import QuestionChoiceResponse 

router = APIRouter(
    prefix="/api/v1/diagnosis-questions",
    tags=["Diagnosis Questions"],
    responses={404: {"description": "Not found"}},
)

@router.post("/", response_model=DiagnosisQuestionResponse, status_code=status.HTTP_201_CREATED)
async def create_question(question: DiagnosisQuestionCreate, db: AsyncSession = Depends(get_db)):
    try:
        return await question_service.create_question(db=db, question=question)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

@router.get("/{question_id}", response_model=DiagnosisQuestionResponse)
async def read_question(question_id: str, db: AsyncSession = Depends(get_db)):
    try:
        uuid_id = UUID(question_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")
        
    db_question = await question_service.get_question(db=db, question_id=uuid_id)
    if not db_question:
        raise HTTPException(status_code=404, detail="Question not found")
    return db_question

@router.get("/template/{template_id}", response_model=List[DiagnosisQuestionResponse])
async def read_questions_by_template(template_id: str, db: AsyncSession = Depends(get_db)):
    try:
        uuid_id = UUID(template_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")
    
    return await question_service.get_questions_by_template(db=db, template_id=uuid_id)

# [THE FIX] 404 에러 해결 (누락된 엔드포인트 추가)
@router.get("/{question_id}/choices", response_model=List[QuestionChoiceResponse])
async def read_choices_by_question(question_id: str, db: AsyncSession = Depends(get_db)):
    try:
        uuid_id = UUID(question_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")
    
    # 질문 존재 확인
    question = await db.get(DiagnosisQuestion, uuid_id)
    if not question:
        raise HTTPException(status_code=404, detail="Question not found")

    result = await db.execute(select(QuestionChoice).where(QuestionChoice.diagnosis_question_id == uuid_id))
    items = result.scalars().all()
    # Pydantic 모델로 변환
    return [QuestionChoiceResponse.model_validate(item, from_attributes=True) for item in items]

@router.patch("/{question_id}", response_model=DiagnosisQuestionResponse)
async def update_question(question_id: str, question_update: DiagnosisQuestionUpdate, db: AsyncSession = Depends(get_db)):
    try:
        uuid_id = UUID(question_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")

    db_question = await question_service.update_question(db=db, question_id=uuid_id, question_update=question_update)
    if not db_question:
        raise HTTPException(status_code=404, detail="Question not found")
    return db_question

@router.delete("/{question_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_question(question_id: str, db: AsyncSession = Depends(get_db)):
    try:
        uuid_id = UUID(question_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")

    deleted_id = await question_service.delete_question(db=db, question_id=uuid_id)
    if not deleted_id:
        raise HTTPException(status_code=404, detail="Question not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)