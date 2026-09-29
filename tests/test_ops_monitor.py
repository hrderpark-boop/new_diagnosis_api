"""운영 감시: 5xx 집계·배너 임계, 합성 쓰기 점검, 오류 미들웨어 (2026-09-29)."""
import asyncio

import pytest


def test_5xx_counter_and_threshold():
    from diag_project.services import ops_monitor as om
    om._ERRORS.clear()
    for i in range(om.ALERT_5XX_THRESHOLD - 1):
        om.record_5xx("/api/v1/diagnoses/submit_message", 500, f"e{i}")
    snap = om.alerts_snapshot()
    assert snap["errors_5xx_last_hour"] == om.ALERT_5XX_THRESHOLD - 1 and snap["errors_5xx_alert"] is False
    om.record_5xx("/api/v1/diagnoses/submit_message", 503)
    snap = om.alerts_snapshot()
    assert snap["errors_5xx_alert"] is True and snap["recent_5xx"][-1]["status"] == 503
    om._ERRORS.clear()


def _sqlite_sessionmaker(tmp_path, with_coach=True):
    from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
    from sqlalchemy.orm import sessionmaker
    from sqlmodel import SQLModel
    import diag_project.main  # noqa: F401 — 모든 모델 로드
    eng = create_async_engine(f"sqlite+aiosqlite:///{tmp_path}/synthetic.db")

    async def _init():
        async with eng.begin() as conn:
            await conn.run_sync(SQLModel.metadata.create_all)
        if with_coach:
            from diag_project.models.coach import Coach
            async with sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)() as db:
                db.add(Coach(name="합성점검 코치", email="synthetic-coach@healthcheck.local"))
                await db.commit()
    asyncio.run(_init())
    return eng, sessionmaker(eng, class_=AsyncSession, expire_on_commit=False)


def test_synthetic_write_check_inserts_then_leaves_no_rows(tmp_path):
    from sqlalchemy import func, select, text
    from diag_project.models.diagnosis_session import ChatMessage
    from diag_project.services.ops_monitor import run_synthetic_write_check
    eng, sm = _sqlite_sessionmaker(tmp_path)
    res = asyncio.run(run_synthetic_write_check(sm))
    assert res["ok"] is True and res["error"] is None

    async def _count():
        async with sm() as db:
            return (await db.execute(select(func.count()).select_from(ChatMessage))).scalar()
    assert asyncio.run(_count()) == 0   # rollback — 흔적 없음


def test_synthetic_write_check_reports_failure(tmp_path):
    from diag_project.services.ops_monitor import run_synthetic_write_check
    eng, sm = _sqlite_sessionmaker(tmp_path, with_coach=False)
    res = asyncio.run(run_synthetic_write_check(sm))
    assert res["ok"] is False and "coaches" in res["error"]


def test_unhandled_exception_returns_error_id_with_cors_and_is_counted():
    from fastapi.testclient import TestClient
    from diag_project.main import app
    from diag_project.services import ops_monitor as om
    om._ERRORS.clear()

    async def _boom():
        raise RuntimeError("boom")
    if not any(getattr(r, "path", "") == "/__test_boom" for r in app.routes):
        app.add_api_route("/__test_boom", _boom, methods=["GET"])
    c = TestClient(app, raise_server_exceptions=False)   # with 블록 없이 — 기동 이벤트(DB 초기화·합성 루프) 미실행
    r = c.get("/__test_boom", headers={"Origin": "https://fm.connectn.co.kr"})
    assert r.status_code == 500
    assert r.json().get("error_id")
    assert r.headers.get("access-control-allow-origin") == "https://fm.connectn.co.kr"
    assert om.alerts_snapshot()["recent_5xx"][-1]["path"] == "/__test_boom"
    om._ERRORS.clear()
