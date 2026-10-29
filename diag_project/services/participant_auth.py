"""참여자 인증 + 참여자 API 소유자 확인 (2026-10-29 보안 P0).

배경: 참여자 토큰이 'fake-jwt-token-for-{id}' 문자열이었고, 진단·대화·리포트·자가진단 API 가 요청에 담긴
participant_id·session_id 를 그대로 믿었다(누구나 남의 세션을 열 수 있었음). 리포트 목록 API 는 인증 없이 전체를 내줬다.

규칙
  - 참여자 토큰: 서명된 JWT(typ=participant, sub=참여자 id, 14일). /participants/token 이 발급한다.
  - 호출자(Caller): 참여자 JWT 또는 관리자 JWT. 둘 다 없으면 401.
      · 참여자는 자기 participant_id·자기 세션만
      · 관리자는 super_admin 이면 전부(대리 중이면 그 고객사), client_admin 이면 자사 참여자만 ('고객 화면 보기')
  - 전환 기간: 이미 진단 중인 사람의 브라우저에 남은 옛 토큰(fake-jwt-token-for-{id})은
    FM_ALLOW_LEGACY_PARTICIPANT_TOKEN=1(기본)일 때만 그 참여자로 인정한다. 전환이 끝나면 0 으로 끈다.
"""
from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from diag_project.config import settings
from diag_project.database import get_db

PARTICIPANT_TOKEN_DAYS = 14
_LEGACY_PREFIX = "fake-jwt-token-for-"
_bearer = HTTPBearer(auto_error=False)


def legacy_tokens_allowed() -> bool:
    return os.getenv("FM_ALLOW_LEGACY_PARTICIPANT_TOKEN", "1").strip().lower() in ("1", "true", "yes", "on")


def create_participant_token(participant_id: uuid.UUID | str) -> str:
    from diag_project.services.auth import _signing_key
    now = datetime.now(timezone.utc)
    payload = {"sub": str(participant_id), "typ": "participant", "iat": int(now.timestamp()),
               "exp": int((now + timedelta(days=PARTICIPANT_TOKEN_DAYS)).timestamp())}
    return jwt.encode(payload, _signing_key(), algorithm=settings.ALGORITHM)


@dataclass
class Caller:
    participant_id: Optional[uuid.UUID] = None
    admin: Optional[object] = None          # AdminContext

    @property
    def is_admin(self) -> bool:
        return self.admin is not None


def _unauth(detail: str = "로그인이 필요합니다. 처음 화면에서 다시 접속해 주세요.") -> HTTPException:
    return HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=detail,
                         headers={"WWW-Authenticate": "Bearer"})


async def get_caller(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
    db: AsyncSession = Depends(get_db),
    x_act_as_company: Optional[str] = Header(None, alias="X-Act-As-Company"),
) -> Caller:
    if credentials is None or not credentials.credentials:
        raise _unauth()
    token = credentials.credentials.strip()

    if token.startswith(_LEGACY_PREFIX):
        if not legacy_tokens_allowed():
            raise _unauth("접속 정보가 만료되었습니다. 처음 화면에서 다시 접속해 주세요.")
        try:
            return Caller(participant_id=uuid.UUID(token[len(_LEGACY_PREFIX):]))
        except ValueError:
            raise _unauth()

    from diag_project.services.auth import decode_token, get_current_admin
    payload = decode_token(token)                       # 서명·만료 검증(실패 시 401)
    typ = payload.get("typ")
    if typ == "participant":
        try:
            return Caller(participant_id=uuid.UUID(str(payload.get("sub"))))
        except ValueError:
            raise _unauth()
    if typ == "admin":
        ctx = await get_current_admin(credentials=credentials, db=db, x_act_as_company=x_act_as_company)
        return Caller(admin=ctx)
    raise _unauth()


async def assert_can_access_participant(caller: Caller, participant_id: uuid.UUID | str | None,
                                        db: AsyncSession) -> None:
    """호출자가 이 참여자의 데이터에 접근할 수 있는지. 아니면 403."""
    if participant_id is None:
        raise HTTPException(status_code=403, detail="이 진단에 접근할 권한이 없습니다.")
    pid = participant_id if isinstance(participant_id, uuid.UUID) else uuid.UUID(str(participant_id))
    if caller.participant_id is not None:
        if caller.participant_id != pid:
            raise HTTPException(status_code=403, detail="이 진단에 접근할 권한이 없습니다.")
        return
    ctx = caller.admin
    if ctx is None:
        raise _unauth()
    if ctx.is_super_admin and not ctx.is_acting:
        return
    from diag_project.models.participant import Participant
    p = await db.get(Participant, pid)
    ctx.assert_can_access_company(p.company_id if p else None)
    if ctx.is_acting and (p is None or p.company_id != ctx.company_id):
        raise HTTPException(status_code=403, detail="이 진단에 접근할 권한이 없습니다.")


async def assert_can_access_session(caller: Caller, session_id: uuid.UUID | str, db: AsyncSession):
    """세션 소유자 확인. 세션이 없으면 404. 통과하면 세션을 돌려준다."""
    from diag_project.models.diagnosis_session import DiagnosisSession
    try:
        sid = session_id if isinstance(session_id, uuid.UUID) else uuid.UUID(str(session_id))
    except ValueError:
        raise HTTPException(status_code=400, detail="세션 ID 형식이 올바르지 않습니다.")
    session = await db.get(DiagnosisSession, sid)
    if session is None:
        raise HTTPException(status_code=404, detail="진단 세션을 찾을 수 없습니다.")
    await assert_can_access_participant(caller, session.user_id, db)
    return session
