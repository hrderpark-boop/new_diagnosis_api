# diag_project/schemas/competency_indicator.py

from pydantic import BaseModel, Field, ConfigDict
from typing import Optional, List, Dict, Any
from datetime import datetime
import uuid # uuid 임포트 추가

from diag_project.schemas.base import BaseSchema

# --- Indicator (지표) 스키마 ---
class IndicatorBase(BaseModel):
    name: str = Field(..., json_schema_extra={"example":"문제 해결 능력"})
    description: Optional[str] = Field(None, json_schema_extra={"example":"복잡한 문제를 분석하고 효과적인 해결책을 찾는 능력"})
    
    levels: Dict[str, str] = Field(default_factory=dict, json_schema_extra={"example": {
        "1": "지표의 기본 개념 이해도가 낮음",
        "2": "간단한 문제 해결에 지표를 적용할 수 있음",
    }})
    examples: Dict[str, List[str]] = Field(default_factory=dict, json_schema_extra={"example": {
        "level_1": ["이런 상황에서 어떻게 문제를 해결했는지 설명해보세요."],
        "level_2": ["당면한 문제에 대한 여러 해결책 중 어떤 것을 선택했나요?"]
    }})

    model_config = ConfigDict(from_attributes=True)

class IndicatorCreate(IndicatorBase):
    competency_id: str = Field(..., json_schema_extra={"example":str(uuid.uuid4())}, description="관련 역량 ID (필수)")
    
    model_config = ConfigDict(from_attributes=True)

class IndicatorUpdate(BaseModel):
    name: Optional[str] = Field(None, json_schema_extra={"example":"문제 해결 능력 (수정됨)"})
    description: Optional[str] = Field(None, json_schema_extra={"example":"복잡한 문제를 분석하고 효과적인 해결책을 찾는 능력 (수정됨)"})
    levels: Optional[Dict[str, str]] = Field(None, json_schema_extra={"example": {
        "1": "지표의 기본 개념 이해도가 낮음 (수정됨)",
        "2": "간단한 문제 해결에 지표를 적용할 수 있음 (수정됨)",
    }})
    examples: Optional[Dict[str, List[str]]] = Field(None, json_schema_extra={"example": {
        "level_1": ["이런 상황에서 어떻게 문제를 해결했는지 설명해보세요. (수정됨)"],
        "level_2": ["당면한 문제에 대한 여러 해결책 중 어떤 것을 선택했나요? (수정됨)"]
    }})

    model_config = ConfigDict(from_attributes=True)

class IndicatorResponse(BaseSchema[str]):
    name: str
    description: Optional[str] = None
    competency_id: str
    levels: Dict[str, str] = Field(default_factory=dict)
    examples: Dict[str, List[str]] = Field(default_factory=dict)
    
class IndicatorListResponse(BaseModel):
    items: List[IndicatorResponse]
    total: int = 0
    skip: int = 0
    limit: int = 100

    model_config = ConfigDict(from_attributes=True)


# --- Competency (역량) 스키마 ---
class CompetencyBase(BaseModel):
    name: str = Field(..., json_schema_extra={"example":"전략적 사고"})
    description: Optional[str] = Field(None, json_schema_extra={"example":"장기적인 목표 달성을 위해 거시적인 관점에서 계획을 수립하는 능력"})

    model_config = ConfigDict(from_attributes=True)

class CompetencyCreate(CompetencyBase):
    pass

    model_config = ConfigDict(from_attributes=True)

class CompetencyUpdate(BaseModel):
    name: Optional[str] = Field(None, json_schema_extra={"example":"전략적 사고 (수정됨)"})
    description: Optional[str] = Field(None, json_schema_extra={"example":"장기적인 목표 달성을 위해 거시적인 관점에서 계획을 수립하는 능력 (수정됨)"})

    model_config = ConfigDict(from_attributes=True)

class CompetencyResponse(BaseSchema[str]):
    name: str
    description: Optional[str] = None
    
    indicators: List[IndicatorResponse] = Field(default_factory=list)

class CompetencyListResponse(BaseModel):
    items: List[CompetencyResponse]
    total: int = 0
    skip: int = 0
    limit: int = 100

    model_config = ConfigDict(from_attributes=True)
