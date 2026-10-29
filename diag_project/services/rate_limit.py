"""로그인 시도 제한(2026-10-29 보안 P0). 단일 인스턴스(Render) 기준 메모리 슬라이딩 윈도.

  - 관리자 로그인: 같은 IP + 같은 이메일로 15분 안에 5번 틀리면 15분 잠금(429). 성공하면 기록을 지운다.
  - 참여자 접속(/participants/token): 같은 IP 에서 5분에 30회까지(코드 대입 속도 제한).
여러 인스턴스로 늘리면 Redis 등 공유 저장소로 옮겨야 한다.
"""
import threading
import time
from collections import defaultdict, deque
from typing import Deque, Dict, Optional

from fastapi import HTTPException, Request

ADMIN_MAX_FAILS = 5
ADMIN_WINDOW_SEC = 15 * 60
PARTICIPANT_MAX_REQ = 30
PARTICIPANT_WINDOW_SEC = 5 * 60

_lock = threading.Lock()
_events: Dict[str, Deque[float]] = defaultdict(deque)


def client_ip(request: Request) -> str:
    """프록시(Render) 뒤 실제 IP: X-Forwarded-For 첫 값, 없으면 연결 IP."""
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _prune(q: Deque[float], window: float, now: float) -> None:
    while q and now - q[0] > window:
        q.popleft()


def _count(key: str, window: float) -> int:
    now = time.monotonic()
    with _lock:
        q = _events[key]
        _prune(q, window, now)
        return len(q)


def _add(key: str) -> None:
    with _lock:
        _events[key].append(time.monotonic())


def _retry_after(key: str, window: float) -> int:
    with _lock:
        q = _events.get(key)
        if not q:
            return 0
        return max(1, int(window - (time.monotonic() - q[0])))


# ── 관리자 로그인 ──
def _admin_key(ip: str, email: Optional[str]) -> str:
    return f"admin:{ip}:{(email or '').strip().lower()}"


def check_admin_login(ip: str, email: Optional[str]) -> None:
    key = _admin_key(ip, email)
    if _count(key, ADMIN_WINDOW_SEC) >= ADMIN_MAX_FAILS:
        wait = _retry_after(key, ADMIN_WINDOW_SEC)
        raise HTTPException(status_code=429, detail=f"로그인 시도가 너무 많습니다. {max(1, wait // 60)}분 후 다시 시도해 주세요.",
                            headers={"Retry-After": str(wait)})


def record_admin_failure(ip: str, email: Optional[str]) -> None:
    _add(_admin_key(ip, email))


def clear_admin_failures(ip: str, email: Optional[str]) -> None:
    with _lock:
        _events.pop(_admin_key(ip, email), None)


# ── 참여자 접속 ──
def check_participant_login(ip: str) -> None:
    key = f"participant:{ip}"
    if _count(key, PARTICIPANT_WINDOW_SEC) >= PARTICIPANT_MAX_REQ:
        wait = _retry_after(key, PARTICIPANT_WINDOW_SEC)
        raise HTTPException(status_code=429, detail="접속 시도가 너무 많습니다. 잠시 후 다시 시도해 주세요.",
                            headers={"Retry-After": str(wait)})
    _add(key)


def reset_all() -> None:
    """테스트용."""
    with _lock:
        _events.clear()
