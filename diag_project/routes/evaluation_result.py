# diag_project/routes/evaluation_result.py (최종 수정 반영)

import logging
from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlmodel.ext.asyncio.session import AsyncSession 

from diag_project.database import get_db 

# 모델 및 스키마 임포트
from diag_project.models.evaluation_result import EvaluationResult
from diag_project.schemas.evaluation_result import (
    EvaluationResultCreate,
    EvaluationResultUpdate,
    EvaluationResultResponse,
    EvaluationResultListResponse,
)
from diag_project.schemas.session import SessionResponse # 세션 정보를 반환할 수 있도록 임포트

# 서비스 임포트
from diag_project.services import evaluation_result as evaluation_result_service
from diag_project.services import session as session_service # Session 존재 여부 확인용

router = APIRouter(
    prefix="/api/v1/evaluation-result", # 기본 prefix 설정
    tags=["Evaluation Result"],
    responses={404: {"description": "Not found"}},
)
logger = logging.getLogger(__name__)


@router.post(
    "/",
    response_model=EvaluationResultResponse,
    status_code=status.HTTP_201_CREATED,
    summary="새로운 평가 결과 생성 (수동)",
    description="제공된 데이터로 새로운 진단 평가 결과를 수동으로 생성합니다. 일반적으로는 `/sessions/{session_id}/evaluate`를 통해 자동으로 생성됩니다."
)
async def create_new_evaluation_result(
    evaluation_result_create: EvaluationResultCreate,
    db: AsyncSession = Depends(get_db)
):
    """
    새로운 평가 결과를 수동으로 생성하고 데이터베이스에 저장합니다.
    """
    existing_session = await session_service.get_session(db, evaluation_result_create.session_id)
    if not existing_session:
        logger.warning(f"EvaluationResult 생성 실패: 세션 ID '{evaluation_result_create.session_id}'를 찾을 수 없음.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"세션 ID '{evaluation_result_create.session_id}'를 찾을 수 없습니다."
        )
    
    existing_evaluation = await evaluation_result_service.get_evaluation_result_by_session_id(db, evaluation_result_create.session_id)
    if existing_evaluation:
        logger.warning(f"EvaluationResult 생성 실패: 세션 ID '{evaluation_result_create.session_id}'에 대한 평가 결과가 이미 존재합니다.")
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"세션 ID '{evaluation_result_create.session_id}'에 대한 평가 결과가 이미 존재합니다. PUT을 사용하여 업데이트하거나 `/sessions/{{session_id}}/evaluate`를 사용하세요."
        )

    try:
        db_evaluation_result = await evaluation_result_service.create_evaluation_result(db, evaluation_result_create)
        return db_evaluation_result
    except Exception as e:
        logger.error(f"EvaluationResult 생성 중 오류 발생: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"평가 결과 생성 중 서버 오류 발생: {e}"
        )


@router.post(
    "/sessions/{session_id}/evaluate", # <--- 새로운 엔드포인트 경로
    response_model=EvaluationResultResponse,
    status_code=status.HTTP_200_OK, # 생성 또는 업데이트이므로 200 OK 또는 201 Created (여기선 업데이트도 가능하므로 200)
    summary="세션 답변 기반 평가 결과 생성/업데이트",
    description="지정된 세션의 참가자 답변을 기반으로 평가 결과를 계산하여 생성하거나 기존 결과를 업데이트합니다."
)
async def create_or_update_evaluation_for_session_api(
    session_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """
    `session_id`에 해당하는 세션의 모든 참가자 답변을 분석하여
    총 점수와 피드백 요약을 계산하고, 해당 세션의 `EvaluationResult`를 생성하거나 업데이트합니다.
    """
    # 세션 존재 여부 확인
    existing_session = await session_service.get_session(db, session_id)
    if not existing_session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"세션 ID '{session_id}'를 찾을 수 없습니다."
        )

    try:
        # 서비스 계층의 자동 생성/업데이트 함수 호출
        db_evaluation_result = await evaluation_result_service.create_or_update_evaluation_result_for_session(db, session_id)
        if db_evaluation_result is None:
            # 서비스 내부에서 세션을 찾지 못했거나, 답변이 없어서 결과 생성이 불가능한 경우
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"세션 ID '{session_id}'에 대한 평가 결과를 생성/업데이트할 수 없습니다. 답변이 없거나 세션이 유효하지 않을 수 있습니다."
            )
        logger.info(f"세션 {session_id}에 대한 EvaluationResult 생성/업데이트 완료: ID={db_evaluation_result.id}")
        return db_evaluation_result
    except HTTPException as e:
        raise e # 서비스에서 발생한 HTTPException은 그대로 전달
    except Exception as e:
        logger.error(f"세션 {session_id} 평가 결과 생성/업데이트 중 오류 발생: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"세션 평가 결과 생성/업데이트 중 서버 오류 발생: {e}"
        )


@router.get(
    "/",
    response_model=EvaluationResultListResponse,
    summary="평가 결과 목록 조회",
    description="모든 평가 결과 또는 특정 세션 ID에 대한 평가 결과를 페이지네이션하여 조회합니다."
)
async def read_evaluation_results(
    session_id: Optional[UUID] = Query(None, description="특정 세션 ID로 필터링"),
    skip: int = Query(0, ge=0, description="건너뛸 항목 수"),
    limit: int = Query(100, ge=1, le=1000, description="반환할 최대 항목 수"),
    db: AsyncSession = Depends(get_db)
):
    """
    쿼리 파라미터로 `session_id`를 전달하여 특정 세션의 평가 결과를 조회하거나,
    `skip`과 `limit`을 사용하여 전체 평가 결과 목록을 페이지네이션하여 조회합니다.
    """
    results = await evaluation_result_service.get_evaluation_results(db, session_id=session_id, skip=skip, limit=limit)
    
    total_count_query = select(EvaluationResult)
    if session_id:
        total_count_query = total_count_query.where(EvaluationResult.session_id == str(session_id))
    
    total_count_result = await db.execute(total_count_query)
    total_count = len(total_count_result.scalars().all())
    
    return EvaluationResultListResponse(items=results, total=total_count, skip=skip, limit=limit)


@router.get(
    "/{result_id}",
    response_model=EvaluationResultResponse,
    summary="ID로 특정 평가 결과 조회",
    description="제공된 EvaluationResult ID를 사용하여 특정 평가 결과를 조회합니다."
)
async def read_evaluation_result_by_id(
    result_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """
    `result_id`에 해당하는 평가 결과를 반환합니다.
    """
    db_evaluation_result = await evaluation_result_service.get_evaluation_result(db, result_id)
    if not db_evaluation_result:
        logger.warning(f"EvaluationResult 조회 실패: ID '{result_id}'를 찾을 수 없음.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"평가 결과 ID '{result_id}'를 찾을 수 없습니다."
        )
    return db_evaluation_result


@router.get(
    "/sessions/{session_id}", # <--- 경로를 /sessions/{session_id}/evaluation-result에서 /sessions/{session_id}로 변경.
                              # 이는 /evaluation-results/{result_id}와 구분하기 위함입니다.
    response_model=EvaluationResultResponse,
    summary="세션 ID로 평가 결과 조회",
    description="특정 세션에 연결된 평가 결과를 조회합니다 (1:1 관계)."
)
async def read_evaluation_result_by_session_id_route(
    session_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """
    `session_id`에 해당하는 세션과 연결된 평가 결과를 반환합니다.
    """
    db_evaluation_result = await evaluation_result_service.get_evaluation_result_by_session_id(db, session_id)
    if not db_evaluation_result:
        logger.warning(f"EvaluationResult 조회 실패: 세션 ID '{session_id}'에 대한 평가 결과를 찾을 수 없음.")
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"세션 ID '{session_id}'에 대한 평가 결과를 찾을 수 없습니다."
        )
    return db_evaluation_result


@router.put(
    "/{result_id}",
    response_model=EvaluationResultResponse,
    summary="ID로 평가 결과 업데이트",
    description="제공된 EvaluationResult ID를 사용하여 기존 평가 결과를 업데이트합니다."
)
async def update_existing_evaluation_result(
    result_id: UUID,
    evaluation_result_update: EvaluationResultUpdate,
    db: AsyncSession = Depends(get_db)
):
    """
    `result_id`에 해당하는 평가 결과를 업데이트하고 업데이트된 객체를 반환합니다.
    """
    db_evaluation_result = await evaluation_result_service.update_evaluation_result(db, result_id, evaluation_result_update)
    if not db_evaluation_result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"평가 결과 ID '{result_id}'를 찾을 수 없습니다."
        )
    return db_evaluation_result


@router.delete(
    "/{result_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="ID로 평가 결과 삭제",
    description="제공된 EvaluationResult ID를 사용하여 특정 평가 결과를 삭제합니다."
)
async def delete_existing_evaluation_result(
    result_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """
    `result_id`에 해당하는 평가 결과를 삭제합니다.
    """
    db_evaluation_result = await evaluation_result_service.delete_evaluation_result(db, result_id)
    if not db_evaluation_result:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"평가 결과 ID '{result_id}'를 찾을 수 없습니다."
        )
    return # 204 No Content 응답을 위해 아무것도 반환하지 않음