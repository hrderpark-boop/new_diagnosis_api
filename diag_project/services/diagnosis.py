# diag_project/services/diagnosis.py

import logging
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from diag_project.models.diagnosis import Diagnosis, DiagnosisCreate, DiagnosisStatus

logger = logging.getLogger(__name__)

async def create_diagnosis(db: AsyncSession, diagnosis: DiagnosisCreate) -> Diagnosis:
    """ 새로운 Diagnosis 레코드를 생성합니다. """
    
    # (선택적) 동일한 템플릿으로 이미 진행중인 진단이 있는지 확인
    # ... (지금은 생략)
    
    db_diagnosis = Diagnosis.model_validate(diagnosis)
    try:
        db.add(db_diagnosis)
        await db.commit()
        await db.refresh(db_diagnosis)
        logger.info(f"New diagnosis started: {db_diagnosis.id} for participant {db_diagnosis.participant_id}")
        return db_diagnosis
    except Exception as e:
        await db.rollback()
        logger.error(f"Error creating diagnosis: {e}", exc_info=True)
        raise e