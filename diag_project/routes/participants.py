# diag_project/routes/participants.py

import os
import uuid
import logging
from datetime import datetime
from typing import Optional
from fastapi import Request, APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from pydantic import BaseModel

from diag_project.database import get_db
from diag_project.models.company import Company
from diag_project.models.participant import Participant

logger = logging.getLogger(__name__)

router = APIRouter(tags=["Participants"])

# A(그룹코드 게이트): B2B 폐쇄형 — group_code 가 companies.code(정규화 일치) +
#   is_active=True 일 때만 로그인 허용. 기본 켜짐. 문제 시 즉시 되돌릴 수 있게
#   env 킬스위치를 둔다(GROUP_CODE_ENFORCED=false → 기존 개방 동작).
GROUP_CODE_ENFORCED = (
    os.getenv("GROUP_CODE_ENFORCED", "true").strip().lower()
    not in ("false", "0", "no", "off")
)
# 사용자 문구는 통일한다 — 코드 '존재 여부'를 노출하지 않는다(계정/코드 열거 방지).
_GATE_MSG = "유효하지 않은 그룹 코드입니다. 관리자에게 문의해 주세요."


def _normalize_group_code(s: Optional[str]) -> str:
    """결정2: 앞뒤 공백 제거 + 대문자 정규화. 손입력/붙여넣기 편차 흡수."""
    return (s or "").strip().upper()


def evaluate_group_code_gate(normalized_code: str,
                             company_active: Optional[bool],
                             enforced: bool) -> tuple[bool, str]:
    """A 게이트 순수 판정 (DB·HTTP 무관, 테스트 고정용).

    company_active: 코드로 찾은 회사의 is_active. 회사 미존재면 None.
    반환: (허용?, 사유). 사유 = not_enforced|empty|not_found|inactive|ok.
    """
    if not enforced:
        return True, "not_enforced"
    if not normalized_code:
        return False, "empty"
    if company_active is None:
        return False, "not_found"
    if not company_active:
        return False, "inactive"
    return True, "ok"

# 요청 모델
class LoginRequest(BaseModel):
    email: str
    password: str
    group_code: str
    name: Optional[str] = None

# 응답 모델
class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    participant_id: str
    name: str

# 로그인 API
@router.post("/token", response_model=TokenResponse)
async def login_for_access_token(
    form_data: LoginRequest,
    request: Request,
    db: AsyncSession = Depends(get_db)
):
    # (2026-10-29 보안) 같은 IP 접속 시도 속도 제한 + 서명된 참여자 토큰(JWT) 발급
    from diag_project.services import rate_limit
    from diag_project.services.participant_auth import create_participant_token
    rate_limit.check_participant_login(rate_limit.client_ip(request))
    logger.info(f"🔐 로그인 시도: {form_data.email} / {form_data.name}")

    # 1. 사용자 조회
    query = select(Participant).where(Participant.email == form_data.email)
    result = await db.execute(query)
    participant = result.scalars().first()

    # 1-a. (2026-10-29) 개인 참여 코드(명단 업로드로 발급): 그 사람으로 들어온다. 이메일이 명단과 다르면 거부.
    _raw_code = _normalize_group_code(form_data.group_code)
    _personal = (await db.execute(
        select(Participant).where(Participant.access_code == _raw_code)
    )).scalars().first() if _raw_code else None
    if _personal is not None:
        if (_personal.email or "").strip().lower() != (form_data.email or "").strip().lower():
            logger.warning("🔒 로그인 거부(개인 코드·이메일 불일치, 코드=%r): %s", _raw_code, form_data.email)
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                                detail="개인 참여 코드와 이메일이 명단과 맞지 않습니다. 담당자에게 문의해 주세요.")
        _pc = await db.get(Company, _personal.company_id) if _personal.company_id else None
        if _pc is None or not _pc.is_active:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=_GATE_MSG)
        if form_data.name and _personal.name != form_data.name:
            _personal.name = form_data.name
            db.add(_personal)
            await db.commit()
            await db.refresh(_personal)
        return {
            "access_token": create_participant_token(_personal.id),
            "token_type": "bearer",
            "participant_id": str(_personal.id),
            "name": _personal.name or "",
        }

    # 1-b. A 게이트: group_code 정규화 → companies.code 대조 + 소속 매핑.
    #   ENFORCED=True 면 미존재/비활성/빈값을 거부(사유는 로그로 구분, 사용자
    #   문구는 통일). company_id 는 활성 회사일 때만 채운다.
    _code = _normalize_group_code(form_data.group_code)
    # (2026-10-29) 회사 코드(07960) 또는 조직 참여 코드(AS1). 조직 코드면 회사와 소속 단위가 함께 정해진다.
    from diag_project.services.org_units import resolve_login_code
    company, org_unit = await resolve_login_code(db, _code)
    company_id = company.id if (company and company.is_active) else None
    org_unit_id = org_unit.id if (org_unit is not None and org_unit.is_active and company_id) else None

    _company_active = company.is_active if company is not None else None
    if org_unit is not None and not org_unit.is_active:
        _company_active = False   # 사용 중지한 조직 코드는 비활성 회사와 같이 막는다
    _allowed, _reason = evaluate_group_code_gate(
        _code, _company_active, GROUP_CODE_ENFORCED)
    if not _allowed:
        logger.warning("🔒 로그인 거부(%s, 코드=%r): %s",
                       _reason, _code, form_data.email)
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail=_GATE_MSG)

    if not participant:
        # 2. 신규 회원가입 처리
        logger.info("✨ 신규 사용자 발견! 자동 회원가입 진행")

        new_participant = Participant(
            id=uuid.uuid4(),
            email=form_data.email,
            name=form_data.name if form_data.name else form_data.email.split("@")[0],
            # 정규화된 코드로 저장(빈 값은 None). 조직 코드로 들어와도 group_code 는 회사 코드로 둔다
            #   (리포트의 '같은 그룹 평균' 비교가 회사 단위로 유지되도록).
            group_code=(company.code if (org_unit is not None and company is not None) else _code) or None,
            company_id=company_id,
            org_unit_id=org_unit_id,
            password_hash="dummy_hashed_password",
            created_at=datetime.now()
        )
        db.add(new_participant)
        await db.commit()
        await db.refresh(new_participant)
        participant = new_participant

    else:
        # 3. 기존 정보 업데이트
        is_changed = False
        if form_data.name and participant.name != form_data.name:
            participant.name = form_data.name
            is_changed = True
        _gc = company.code if (org_unit is not None and company is not None) else _code
        if _gc and participant.group_code != _gc:
            participant.group_code = _gc  # 정규화된 코드로 갱신(조직 코드면 회사 코드)
            is_changed = True
        # 조직 코드로 들어오면 소속을 그 단위로(회사 코드로만 들어오면 기존 소속 유지)
        if org_unit_id and participant.org_unit_id != org_unit_id:
            participant.org_unit_id = org_unit_id
            is_changed = True
        # 소속사가 새로 등록됐거나 group_code 가 바뀐 경우 소급 반영
        if company_id and participant.company_id != company_id:
            participant.company_id = company_id
            is_changed = True

        if is_changed:
            db.add(participant)
            await db.commit()
            await db.refresh(participant)

    # 4. 토큰 응답
    return {
        "access_token": create_participant_token(participant.id),
        "token_type": "bearer",
        "participant_id": str(participant.id),
        "name": participant.name if participant.name else ""
    }