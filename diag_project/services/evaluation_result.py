# diag_project/services/evaluation_result.py (수정 반영)

import logging
from typing import List, Optional
from uuid import UUID

from sqlmodel.ext.asyncio.session import AsyncSession # <--- AsyncSession 임포트
from sqlmodel import select
from sqlalchemy.orm import joinedload # 관계형 데이터를 불러올 때 사용

from diag_project.models.evaluation_result import EvaluationResult
from diag_project.models.session import Session # 세션 존재 여부 확인 및 관계 로드용
from diag_project.models.participant_answer import ParticipantAnswer # 답변 조회용
from diag_project.models.question_choice import QuestionChoice # 선택지 점수 조회용

from diag_project.schemas.evaluation_result import (
    EvaluationResultCreate,
    EvaluationResultUpdate,
)
from diag_project.schemas.participant_answer import ParticipantAnswerResponse # 피드백 생성 로직에서 사용할 수 있음

logger = logging.getLogger(__name__)

# --- CRUD Operations ---

async def create_evaluation_result(db: AsyncSession, evaluation_result: EvaluationResultCreate) -> EvaluationResult: # <--- async 추가, AsyncSession 사용
    """
    새로운 EvaluationResult를 생성합니다. (일반적인 생성)
    """
    db_evaluation_result = EvaluationResult.model_validate(evaluation_result)
    db.add(db_evaluation_result)
    await db.commit() # <--- await 추가
    await db.refresh(db_evaluation_result) # <--- await 추가
    logger.info(f"EvaluationResult 생성: ID={db_evaluation_result.id}, 세션_ID={db_evaluation_result.session_id}")
    return db_evaluation_result

async def get_evaluation_result(db: AsyncSession, evaluation_result_id: UUID) -> Optional[EvaluationResult]: # <--- async 추가, AsyncSession 사용
    """
    ID로 특정 EvaluationResult를 조회합니다. 관련 세션 정보도 함께 로드합니다.
    """
    result = await db.execute( # <--- await 추가
        select(EvaluationResult)
        .where(EvaluationResult.id == str(evaluation_result_id)) # UUID는 문자열로 비교
        .options(joinedload(EvaluationResult.session))
    )
    return result.scalars().first()

async def get_evaluation_result_by_session_id(db: AsyncSession, session_id: UUID) -> Optional[EvaluationResult]: # <--- async 추가, AsyncSession 사용
    """
    Session ID로 특정 EvaluationResult를 조회합니다 (1:1 관계). 관련 세션 정보도 함께 로드합니다.
    """
    statement = (
        select(EvaluationResult)
        .where(EvaluationResult.session_id == str(session_id))
        .options(joinedload(EvaluationResult.session))
    )
    result = await db.execute(statement) # <--- await 추가
    return result.scalars().first()

async def get_evaluation_results(
    db: AsyncSession, # <--- AsyncSession 사용
    session_id: Optional[UUID] = None,
    skip: int = 0,
    limit: int = 100
) -> List[EvaluationResult]:
    """
    모든 EvaluationResult 목록을 조회합니다. session_id로 필터링 및 페이지네이션을 지원합니다.
    관련 세션 정보도 함께 로드합니다.
    """
    query = select(EvaluationResult).options(joinedload(EvaluationResult.session))
    if session_id:
        query = query.where(EvaluationResult.session_id == str(session_id))
    
    result = await db.execute(query.offset(skip).limit(limit)) # <--- await 추가
    results = result.scalars().all()
    logger.debug(f"EvaluationResult 목록 조회 (필터: session_id={session_id}, 스킵={skip}, 제한={limit}): {len(results)}개 결과 반환")
    return list(results)

async def update_evaluation_result( # <--- async 추가
    db: AsyncSession, # <--- AsyncSession 사용
    evaluation_result_id: UUID, 
    evaluation_result_update: EvaluationResultUpdate
) -> Optional[EvaluationResult]:
    """
    ID로 특정 EvaluationResult를 업데이트합니다.
    """
    result = await db.execute(select(EvaluationResult).where(EvaluationResult.id == str(evaluation_result_id))) # <--- await 추가
    db_evaluation_result = result.scalars().first()

    if not db_evaluation_result:
        logger.warning(f"EvaluationResult 업데이트 실패: ID '{evaluation_result_id}'를 찾을 수 없음.")
        return None
    
    update_data = evaluation_result_update.model_dump(exclude_unset=True)
    db_evaluation_result.sqlmodel_update(update_data)
    
    db.add(db_evaluation_result)
    await db.commit() # <--- await 추가
    await db.refresh(db_evaluation_result) # <--- await 추가
    logger.info(f"EvaluationResult 업데이트: ID={db_evaluation_result.id}")
    return db_evaluation_result

async def delete_evaluation_result(db: AsyncSession, evaluation_result_id: UUID) -> Optional[EvaluationResult]: # <--- async 추가, AsyncSession 사용
    """
    ID로 특정 EvaluationResult를 삭제합니다.
    """
    result = await db.execute(select(EvaluationResult).where(EvaluationResult.id == str(evaluation_result_id))) # <--- await 추가
    db_evaluation_result = result.scalars().first()
    
    if not db_evaluation_result:
        logger.warning(f"EvaluationResult 삭제 실패: ID '{evaluation_result_id}'를 찾을 수 없음.")
        return None
    
    await db.delete(db_evaluation_result) # <--- await 추가
    await db.commit() # <--- await 추가
    logger.info(f"EvaluationResult 삭제: ID={evaluation_result_id}")
    return db_evaluation_result

# --- New Logic for automatic Evaluation Result Generation ---

async def calculate_score_and_feedback(
    db: AsyncSession, session_id: UUID
) -> tuple[int, str, List[ParticipantAnswerResponse]]:
    """
    특정 세션의 모든 참가자 답변을 기반으로 총 점수와 피드백 요약을 계산합니다.
    """
    # 1. 세션의 모든 답변 로드
    answers_result = await db.execute(
        select(ParticipantAnswer)
        .where(ParticipantAnswer.session_id == str(session_id))
        .options(
            joinedload(ParticipantAnswer.question),
            joinedload(ParticipantAnswer.choice) # 선택지 점수를 위해 로드
        )
        .order_by(ParticipantAnswer.answered_at)
    )
    participant_answers = answers_result.scalars().all()

    total_score = 0
    feedback_parts = []
    
    # Pydantic Response 모델로 변환 (API 응답 시 유용)
    answers_for_response = [ParticipantAnswerResponse.model_validate(answer) for answer in participant_answers]

    for answer in participant_answers:
        # 2. 선택지 점수 합산
        if answer.choice and answer.choice.score is not None:
            total_score += answer.choice.score

        # 3. 피드백 요약 생성 로직
        # 여기서는 간단하게 각 질문의 답변 내용을 요약하지만,
        # 실제로는 점수 구간별, 특정 답변 조합별로 더 복잡한 피드백 로직을 구현할 수 있습니다.
        if answer.question and answer.choice:
            feedback_parts.append(
                f"- 질문 '{answer.question.question_text}': 선택 '{answer.choice.choice_text}' (점수: {answer.choice.score or 0}점)"
            )
        elif answer.question and answer.answer_text:
            feedback_parts.append(
                f"- 질문 '{answer.question.question_text}': 주관식 답변 '{answer.answer_text[:50]}...'"
            )
        else:
             feedback_parts.append(f"- 알 수 없는 답변 (ID: {answer.id})")
    
    feedback_summary = "세션 진단 결과 요약:\n" + "\n".join(feedback_parts)
    
    return total_score, feedback_summary, answers_for_response


async def create_or_update_evaluation_result_for_session(db: AsyncSession, session_id: UUID) -> Optional[EvaluationResult]: # <--- async 추가
    """
    특정 세션에 대한 EvaluationResult를 생성하거나 기존 것을 업데이트합니다.
    세션의 ParticipantAnswer를 기반으로 점수와 피드백을 계산합니다.
    """
    # 1. 세션 존재 여부 확인
    session_result = await db.execute(select(Session).where(Session.id == str(session_id)))
    db_session = session_result.scalars().first()
    if not db_session:
        logger.warning(f"세션 ID '{session_id}'를 찾을 수 없어 EvaluationResult를 생성/업데이트할 수 없음.")
        return None
    
    # 2. 현재 EvaluationResult 조회 (존재하면 업데이트, 없으면 생성)
    db_evaluation_result = await get_evaluation_result_by_session_id(db, session_id)

    # 3. 점수 및 피드백 계산
    total_score, feedback_summary, _ = await calculate_score_and_feedback(db, session_id)

    if db_evaluation_result:
        # 기존 결과 업데이트
        update_data = EvaluationResultUpdate(
            total_score=total_score,
            feedback_summary=feedback_summary,
            is_final=db_session.is_completed # 세션이 완료되면 최종 평가로 간주
        )
        updated_result = await update_evaluation_result(db, db_evaluation_result.id, update_data)
        logger.info(f"기존 EvaluationResult 업데이트: ID={updated_result.id}, 세션_ID={session_id}")
        return updated_result
    else:
        # 새 결과 생성
        create_data = EvaluationResultCreate(
            session_id=session_id,
            total_score=total_score,
            feedback_summary=feedback_summary,
            is_final=db_session.is_completed # 세션이 완료되면 최종 평가로 간주
        )
        new_result = await create_evaluation_result(db, create_data)
        logger.info(f"새 EvaluationResult 생성: ID={new_result.id}, 세션_ID={session_id}")
        return new_result