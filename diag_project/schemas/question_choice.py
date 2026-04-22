# diag_project/schemas/question_choice.py 

from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict
from uuid import UUID

from diag_project.schemas.base import BaseSchema

class QuestionChoiceBase(BaseModel):
    choice_text: str = Field(..., examples=["A. 동료에게 직접 대화를 요청하여 상황을 파악한다."], description="선택지 내용")
    score: Optional[int] = Field(None, examples=[5], description="이 선택지를 선택했을 때 얻는 점수 (내부 로직용)")
    order: int = Field(default=0, description="선택지 순서")
    is_active: bool = Field(default=True)

    model_config = ConfigDict(from_attributes=True)

class QuestionChoiceCreate(QuestionChoiceBase):
    # [수정] API(/api/v1/question-choices/)를 통해 생성할 때 필수입니다.
    diagnosis_question_id: UUID

class QuestionChoiceUpdate(BaseModel):
    choice_text: Optional[str] = Field(None, examples=["B. 상사에게 먼저 보고한다."])
    score: Optional[int] = Field(None, examples=[2])
    order: Optional[int] = Field(None)
    is_active: Optional[bool] = Field(None)

    model_config = ConfigDict(from_attributes=True)

class QuestionChoiceResponse(BaseSchema[UUID]): 
    choice_text: str
    score: Optional[int]
    order: int
    is_active: bool
    
    # [수정] DB 모델의 컬럼명(diagnosis_question_id)과 일치시킴
    diagnosis_question_id: UUID 

    # 순환 참조 방지를 위해 객체 참조는 제거하거나 필요시 문자열 ForwardRef 사용
    
    model_config = ConfigDict(from_attributes=True)


class QuestionChoiceListResponse(BaseModel):
    items: List[QuestionChoiceResponse]
    total: int = 0
    skip: int = 0
    limit: int = 100

    model_config = ConfigDict(from_attributes=True)