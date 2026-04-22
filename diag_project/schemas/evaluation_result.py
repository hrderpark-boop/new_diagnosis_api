# diag_project/schemas/evaluation_result.py (최종 수정)

from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List
from datetime import datetime
from uuid import UUID

from diag_project.schemas.base import BaseSchema


# --- EvaluationResult (평가 결과) 스키마 ---
class EvaluationResultBase(BaseModel):
    session_id: UUID = Field(..., description="이 평가 결과가 속한 진단 세션의 ID")
    total_score: int = Field(..., description="진단 세션의 총 점수")
    feedback_summary: Optional[str] = Field(None, max_length=5000, description="진단 결과에 대한 피드백 요약")
    
    model_config = ConfigDict(from_attributes=True)

class EvaluationResultCreate(EvaluationResultBase):
    pass

class EvaluationResultUpdate(BaseModel):
    total_score: Optional[int] = Field(None, description="진단 세션의 총 점수")
    feedback_summary: Optional[str] = Field(None, max_length=5000, description="진단 결과에 대한 피드백 요약")
    is_final: Optional[bool] = Field(None, description="최종 평가 결과 여부")

    model_config = ConfigDict(from_attributes=True)

class EvaluationResultResponse(EvaluationResultBase):
    id: UUID = Field(..., description="평가 결과의 고유 ID")
    is_final: bool = Field(False, description="최종 평가 결과 여부")
    created_at: datetime = Field(..., description="생성 일시")
    updated_at: datetime = Field(..., description="최근 업데이트 일시")

    # 관계형 필드
    # --- 중요: 다시 문자열 참조로 변경 (따옴표 필수) ---
    session: Optional["SessionResponse"] = None

    model_config = ConfigDict(from_attributes=True)

# --- 리스트 응답 스키마 ---
class EvaluationResultListResponse(BaseModel):
    items: List[EvaluationResultResponse]
    total: int = 0
    skip: int = 0
    limit: int = 100

    model_config = ConfigDict(from_attributes=True)

# 이 파일에는 model_rebuild() 호출이 없어야 합니다.