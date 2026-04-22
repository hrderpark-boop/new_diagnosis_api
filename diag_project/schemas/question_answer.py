# diag_project/schemas/question_answer.py (수정 반영)

from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone
import uuid # UUID 타입 힌트를 위해 필요 (예시 값에 사용)

from diag_project.schemas.base import BaseSchema
# from diag_project.schemas.competency_indicator import CompetencyResponse, IndicatorResponse # 관계형 필드 포함 시 필요

# --- QuestionCategory (질문 카테고리) 스키마 ---
# (아직 모델이 없지만, Question 스키마에서 참조할 수 있으므로 미리 정의)
class QuestionCategoryBase(BaseModel):
    name: str = Field(..., example="자기 인식")
    description: Optional[str] = Field(None, example="자신에 대한 이해도 관련 질문")

class QuestionCategoryCreate(QuestionCategoryBase):
    pass

class QuestionCategoryUpdate(QuestionCategoryBase):
    name: Optional[str] = Field(None, example="자기 인식")
    description: Optional[str] = Field(None, example="자신에 대한 이해도 관련 질문")

class QuestionCategoryResponse(BaseSchema[str]): # <--- BaseSchema[str]로 변경
    name: str
    description: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


# --- Question (일반 질문) 스키마 ---
class QuestionBase(BaseModel):
    question_text: str = Field(..., example="우리 조직의 비전과 목표를 명확히 이해하고, 이를 통해 업무에 동기 부여를 받은 경험에 대해 이야기해 주십시오.", description="실제 질문 내용")
    category_id: Optional[str] = Field(None, example=str(uuid.uuid4()), description="관련 질문 카테고리 ID") # <--- str로 변경
    competency_id: Optional[str] = Field(None, example=str(uuid.uuid4()), description="관련 역량 ID") # <--- str로 변경
    indicator_id: Optional[str] = Field(None, example=str(uuid.uuid4()), description="관련 지표 ID") # <--- str로 변경
    is_active: Optional[bool] = Field(True, example=True, description="질문 활성화 여부")

    model_config = ConfigDict(from_attributes=True)

class QuestionCreate(QuestionBase):
    pass

class QuestionUpdate(BaseModel):
    question_text: Optional[str] = None
    category_id: Optional[str] = None # <--- str로 변경
    competency_id: Optional[str] = None # <--- str로 변경
    indicator_id: Optional[str] = None # <--- str로 변경
    is_active: Optional[bool] = None

    model_config = ConfigDict(from_attributes=True)

class QuestionResponse(BaseSchema[str]): # <--- BaseSchema[str]로 변경
    question_text: str
    category_id: Optional[str] = None # <--- str로 변경
    competency_id: Optional[str] = None # <--- str로 변경
    indicator_id: Optional[str] = None # <--- str로 변경
    is_active: bool

    category: Optional[QuestionCategoryResponse] = None # <--- QuestionCategoryResponse 정의 후 추가
    # competency: Optional[CompetencyResponse] = None # 필요시 주석 해제
    # indicator: Optional[IndicatorResponse] = None # 필요시 주석 해제

    model_config = ConfigDict(from_attributes=True) # <--- 명시적으로 추가


# --- Answer (세션 내 특정 질문에 대한 답변) 스키마 ---
class AnswerBase(BaseModel):
    session_id: str = Field(..., example=str(uuid.uuid4()), description="세션 ID") # <--- str로 변경
    session_question_id: str = Field(..., example=str(uuid.uuid4()), description="SessionQuestion의 ID") # <--- str로 변경 (이름도 일관성 있게)
    answer_text: str = Field(..., description="참여자의 답변") # <--- '코치' 대신 '참여자' 답변으로 변경 (모델과 일관성)
    feedback_text: Optional[str] = None
    score: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)

class AnswerCreate(AnswerBase):
    pass

class AnswerUpdate(BaseModel):
    session_id: Optional[str] = None # <--- str로 변경
    session_question_id: Optional[str] = None # <--- str로 변경 (이름도 일관성 있게)
    answer_text: Optional[str] = None
    feedback_text: Optional[str] = None
    score: Optional[int] = None

    model_config = ConfigDict(from_attributes=True)

class AnswerResponse(BaseSchema[str]): # <--- BaseSchema[str]로 변경
    session_id: str # <--- str로 변경
    session_question_id: str # <--- str로 변경 (이름도 일관성 있게)
    answer_text: str
    feedback_text: Optional[str] = None
    score: Optional[int] = None
    answered_at: datetime

    # session: Optional["SessionResponse"] = None # 순환 참조 주의, 필요시 update_forward_refs()와 함께
    # session_question: Optional["SessionQuestionResponse"] = None # 순환 참조 주의, 필요시 update_forward_refs()와 함께

    model_config = ConfigDict(from_attributes=True) # <--- 명시적으로 추가


# --- 리스트 응답 스키마 ---
class QuestionListResponse(BaseModel): # <--- QuestionsListResponse -> QuestionListResponse (일관성)
    items: List[QuestionResponse]
    total: int = 0
    skip: int = 0
    limit: int = 100

    model_config = ConfigDict(from_attributes=True)

class AnswerListResponse(BaseModel): # <--- AnswerListResponse 추가
    items: List[AnswerResponse]
    total: int = 0
    skip: int = 0
    limit: int = 100

    model_config = ConfigDict(from_attributes=True)