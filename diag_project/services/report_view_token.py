"""(2026-11-06 P5) '고객 화면 보기' 열람 토큰 — 관리자 쿠키를 참여자 도메인(fm)에 넘기지 않고 리포트 새 탭을 연다.

흐름
  1. 관리자 콘솔(fm-hr·fm-ops)에서 [고객 화면 보기] → POST /admin/sessions/{sid}/view-token (관리자 인증: 마스터 전부, HR 자사만)
     → 1회용 서명 토큰(typ=report_view, 60초, session_id 한정, jti)
  2. fm 새 탭이 URL 조각(#vt=…, 서버로 전송되지 않음)에서 받아 POST /reports/{sid}/view-session 으로 교환
     → 세션 전용 열람 토큰(typ=report_viewer, 30분). 1회용 토큰은 jti 를 소진해 다시 못 쓴다.
  3. 열람 토큰은 그 세션의 GET(리포트·진행 상태·예상 시간)에만 통한다 — POST(재분석·대화)는 403.
jti 소진 집합은 프로세스 메모리(Render 단일 인스턴스). 재기동되면 비워지지만 60초 만료라 무해하다. 토큰 값은 로그에 남기지 않는다.
"""
from __future__ import annotations

import time
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from jose import jwt

from diag_project.config import settings

VIEW_TOKEN_SECONDS = 60          # 1회용 — 클릭 → 새 탭 교환까지
VIEWER_TOKEN_MINUTES = 30        # 세션 전용 열람 — 분석 중 폴링(수 분)을 덮는다
TYP_VIEW = "report_view"
TYP_VIEWER = "report_viewer"
_USED_JTI: dict[str, float] = {}   # jti → 만료 시각(epoch). 만료 지난 것은 정리


def _signing_key() -> str:
    from diag_project.services.auth import _signing_key as _k
    return _k()


def create_view_token(session_id: uuid.UUID | str, participant_id: uuid.UUID | str, admin_id: uuid.UUID | str) -> tuple[str, int]:
    """(1회용 토큰, 만료 초). session_id·participant_id 한정, jti 로 1회성."""
    now = datetime.now(timezone.utc)
    payload = {"typ": TYP_VIEW, "sid": str(session_id), "pid": str(participant_id), "adm": str(admin_id), "jti": uuid.uuid4().hex,
               "iat": int(now.timestamp()), "exp": int((now + timedelta(seconds=VIEW_TOKEN_SECONDS)).timestamp())}
    return jwt.encode(payload, _signing_key(), algorithm=settings.ALGORITHM), VIEW_TOKEN_SECONDS


def create_viewer_token(session_id: uuid.UUID | str, participant_id: uuid.UUID | str, admin_id: uuid.UUID | str) -> tuple[str, int]:
    """(세션 전용 열람 토큰, 만료 초)."""
    now = datetime.now(timezone.utc)
    payload = {"typ": TYP_VIEWER, "sid": str(session_id), "pid": str(participant_id), "adm": str(admin_id),
               "iat": int(now.timestamp()), "exp": int((now + timedelta(minutes=VIEWER_TOKEN_MINUTES)).timestamp())}
    return jwt.encode(payload, _signing_key(), algorithm=settings.ALGORITHM), VIEWER_TOKEN_MINUTES * 60


def consume_view_token(payload: dict) -> None:
    """1회용 토큰의 jti 를 소진한다. 이미 쓴 jti 면 401."""
    jti = str(payload.get("jti") or "")
    exp = float(payload.get("exp") or 0)
    now = time.time()
    for k in [k for k, v in _USED_JTI.items() if v < now]:
        _USED_JTI.pop(k, None)
    if not jti or jti in _USED_JTI:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="열람 링크가 이미 사용되었거나 만료되었습니다. 관리자 콘솔에서 다시 열어 주세요.")
    _USED_JTI[jti] = exp or (now + VIEW_TOKEN_SECONDS)


def reset_used_jti() -> None:
    """테스트용."""
    _USED_JTI.clear()
