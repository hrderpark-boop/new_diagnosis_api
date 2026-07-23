# diag_project/routes/self_eval.py
#
# 자가진단(Self-Assessment) API.
#
# 대상자가 AI 코칭 대화를 시작하기 직전에 스스로 매긴 5대 역량 점수와
# 주관식 강약점을 세션에 저장한다. 이후 AI 분석 결과와 대조해
# '메타인지(자기 객관화) 격차'를 산출하는 근거가 된다.

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field as PydanticField
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from diag_project.data.competencies import COMPETENCY_FRAMEWORK
from diag_project.database import get_db
from diag_project.models.diagnosis_session import DiagnosisSession

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/sessions", tags=["Self Assessment"])

# 자가진단 대상 역량 = AI 채점 대상 역량과 동일한 키 집합.
# (supplementary 는 보조 항목이라 자가진단에서 제외)
SELF_EVAL_KEYS = [k for k in COMPETENCY_FRAMEWORK.keys() if k != "supplementary"]

MIN_SCORE = 1.0
MAX_SCORE = 5.0
MAX_TEXT_LEN = 2000


class SelfEvalRequest(BaseModel):
    # {역량키: 점수} — 5개 역량 전부 필요
    scores: Dict[str, float]
    # 주관식: 본인이 생각하는 강점과 약점
    strength_weakness_text: Optional[str] = PydanticField(default=None)


@router.patch("/{session_id}/self-eval")
async def submit_self_evaluation(
    session_id: UUID,
    body: SelfEvalRequest,
    db: AsyncSession = Depends(get_db),
):
    """세션에 자가진단 결과를 저장한다.

    대화 시작 전 1회 제출이 원칙이지만, 재제출도 허용한다(오입력 정정).
    이미 완료된 세션에 대해서는 거부한다 — 사후 입력은 '진단 전 자기 인식'이
    아니어서 갭 분석의 전제가 깨지기 때문이다.
    """
    session = (
        await db.execute(
            select(DiagnosisSession).where(DiagnosisSession.id == session_id)
        )
    ).scalars().first()

    if not session:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")

    if session.status == "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="이미 종료된 진단에는 자가진단을 등록할 수 없습니다.",
        )

    # --- 점수 검증 ---
    missing = [k for k in SELF_EVAL_KEYS if k not in body.scores]
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"누락된 역량 점수가 있습니다: {', '.join(missing)}",
        )

    unknown = [k for k in body.scores if k not in SELF_EVAL_KEYS]
    if unknown:
        raise HTTPException(
            status_code=400,
            detail=f"알 수 없는 역량 키입니다: {', '.join(unknown)}",
        )

    clean_scores: Dict[str, float] = {}
    for key in SELF_EVAL_KEYS:
        try:
            value = float(body.scores[key])
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=400, detail=f"'{key}' 점수가 숫자가 아닙니다."
            )
        if not (MIN_SCORE <= value <= MAX_SCORE):
            raise HTTPException(
                status_code=400,
                detail=f"'{key}' 점수는 {MIN_SCORE}~{MAX_SCORE} 범위여야 합니다.",
            )
        clean_scores[key] = round(value, 1)

    # --- 주관식 검증 ---
    text = (body.strength_weakness_text or "").strip()
    if len(text) > MAX_TEXT_LEN:
        raise HTTPException(
            status_code=400,
            detail=f"주관식 답변은 {MAX_TEXT_LEN}자 이내로 작성해주세요.",
        )

    payload: Dict[str, Any] = {
        "scores": clean_scores,
        "strength_weakness_text": text or None,
        "self_average": round(sum(clean_scores.values()) / len(clean_scores), 2),
        "submitted_at": datetime.now(timezone.utc).isoformat(),
    }

    # JSON 컬럼은 통째로 재할당해야 변경이 감지된다.
    session.self_assessment_data = payload
    db.add(session)
    await db.commit()

    logger.info("자가진단 저장: session=%s, avg=%s", session_id, payload["self_average"])

    return {
        "success": True,
        "message": "자가진단이 저장되었습니다.",
        "self_assessment": payload,
    }


@router.get("/{session_id}/self-eval")
async def get_self_evaluation(
    session_id: UUID,
    db: AsyncSession = Depends(get_db),
):
    """저장된 자가진단 조회. 미제출이면 submitted=false 로 응답한다."""
    session = (
        await db.execute(
            select(DiagnosisSession).where(DiagnosisSession.id == session_id)
        )
    ).scalars().first()

    if not session:
        raise HTTPException(status_code=404, detail="세션을 찾을 수 없습니다.")

    data = session.self_assessment_data
    return {
        "submitted": bool(data),
        "self_assessment": data,
        "competency_keys": SELF_EVAL_KEYS,
    }
