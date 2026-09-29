"""운영 감시 (2026-09-29, 파일럿 전 필수) — 5xx 집계 + 쓰기 경로 합성 점검.

배경: 09-22~09-29 프로덕션이 일주일 동안 쓰기 불가(submit_message 500)였는데 아무도 몰랐다.
- 5xx: 전역 오류 미들웨어가 모든 5xx 를 기록 → /admin/alerts 가 최근 1시간 건수를 올리고 임계(기본 3건) 이상이면 배너.
- 합성 점검: 하루 1회(기동 60초 뒤 첫 실행) 테스트 참가자·세션·메시지를 한 트랜잭션에서 INSERT(flush — DB 가 실제로 실행)한 뒤
  rollback. 이번 사고의 실패 지점(바인딩·INSERT)을 그대로 지나며 데이터는 남기지 않는다. 결과는 /admin/alerts.
프로세스 메모리 상태(Render 단일 인스턴스) — 재기동하면 초기화된다.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from collections import deque
from datetime import datetime

logger = logging.getLogger(__name__)

_ERRORS: deque = deque(maxlen=500)   # (epoch, path, status, error_id)
SYNTHETIC: dict = {"last_run_at": None, "ok": None, "error": None, "elapsed_ms": None}
ALERT_5XX_THRESHOLD = int(os.getenv("FM_5XX_ALERT_THRESHOLD", "3"))
SYNTHETIC_INTERVAL_S = int(os.getenv("FM_SYNTHETIC_INTERVAL_S", str(24 * 3600)))


def record_5xx(path: str, status: int, error_id: str | None = None) -> None:
    _ERRORS.append((time.time(), path, int(status), error_id))


def recent_5xx(minutes: int = 60) -> list[dict]:
    cut = time.time() - minutes * 60
    return [{"at": datetime.utcfromtimestamp(t).isoformat(timespec="seconds"), "path": p, "status": s, "error_id": e}
            for (t, p, s, e) in _ERRORS if t >= cut]


def alerts_snapshot() -> dict:
    recent = recent_5xx(60)
    return {
        "errors_5xx_last_hour": len(recent),
        "errors_5xx_alert": len(recent) >= ALERT_5XX_THRESHOLD,
        "errors_5xx_threshold": ALERT_5XX_THRESHOLD,
        "recent_5xx": recent[-5:],
        "synthetic_check": dict(SYNTHETIC),
    }


async def run_synthetic_write_check(sessionmaker=None) -> dict:
    """테스트 참가자·세션·메시지 INSERT(flush) 후 rollback. 성공/실패를 SYNTHETIC 에 기록하고 돌려준다."""
    from sqlalchemy import select
    from diag_project.models.coach import Coach
    from diag_project.models.diagnosis_session import ChatMessage, DiagnosisSession
    from diag_project.models.participant import Participant
    if sessionmaker is None:
        from diag_project.database import async_session as sessionmaker
    t0 = time.perf_counter()
    SYNTHETIC["last_run_at"] = datetime.utcnow().isoformat(timespec="seconds")
    try:
        async with sessionmaker() as db:
            try:
                coach_id = (await db.execute(select(Coach.id).limit(1))).scalars().first()
                if coach_id is None:
                    raise RuntimeError("coaches 테이블이 비어 있음")
                p = Participant(email=f"synthetic-{uuid.uuid4().hex[:10]}@healthcheck.local", name="합성점검")
                db.add(p)
                await db.flush()
                s = DiagnosisSession(user_id=p.id, coach_id=coach_id, status="in_progress", current_topic="General")
                db.add(s)
                await db.flush()
                db.add(ChatMessage(session_id=s.id, role="user", content="[synthetic write check]"))
                await db.flush()   # ← 이번 사고의 실패 지점: 모델 → DB 바인딩·INSERT
            finally:
                await db.rollback()   # 흔적을 남기지 않는다
        SYNTHETIC.update(ok=True, error=None)
    except Exception as e:  # noqa: BLE001
        SYNTHETIC.update(ok=False, error=f"{type(e).__name__}: {str(e)[:240]}")
        logger.error("🚨 합성 쓰기 점검 실패 — 프로덕션 쓰기 경로 이상: %s", SYNTHETIC["error"])
    SYNTHETIC["elapsed_ms"] = int((time.perf_counter() - t0) * 1000)
    return dict(SYNTHETIC)


async def synthetic_loop(first_delay_s: int = 60) -> None:
    await asyncio.sleep(first_delay_s)
    while True:
        await run_synthetic_write_check()
        await asyncio.sleep(SYNTHETIC_INTERVAL_S)
