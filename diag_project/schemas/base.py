# diag_project/schemas/base.py (최종 수정)

from datetime import datetime
from pydantic import BaseModel, ConfigDict
from typing import TypeVar, Generic
import uuid # uuid.UUID 타입을 위해 임포트

# 모든 모델의 ID가 통일되어 있지 않으므로, 제네릭 타입을 사용하여 유연하게 처리
# int 또는 uuid.UUID (Pydantic은 uuid.UUID를 자동으로 str로 변환합니다.)
IDType = TypeVar("IDType", int, uuid.UUID)

class BaseSchema(BaseModel, Generic[IDType]):
    id: IDType # BaseSchema[UUID]로 상속받으면 id는 UUID 타입이 됩니다.
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)