"""의존성 드리프트 방지 (2026-09-29 사고: Render 재빌드가 sqlmodel 0.0.46 을 받아 모든 메시지 INSERT 가 500)."""
import os
import re
from datetime import datetime
from typing import Optional

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CORE = ("fastapi", "starlette", "uvicorn", "sqlmodel", "SQLAlchemy", "asyncpg", "google-genai", "pydantic")


def test_core_requirements_are_exact_pins():
    txt = open(os.path.join(ROOT, "requirements.txt"), encoding="utf-8").read()
    for pkg in CORE:
        m = re.search(r"^" + re.escape(pkg) + r"(\[[^\]]*\])?\s*([=<>!~]=?)\s*([\w.]+)", txt, re.M | re.I)
        assert m, f"{pkg} 가 requirements.txt 에 없다"
        assert m.group(2) == "==", f"{pkg} 는 '==' 로 고정해야 한다(현재 {m.group(2)})"


def test_installed_sqlmodel_accepts_naive_datetime_models():
    """모델 기본값(datetime.now/utcnow)은 naive 다. 설치된 sqlmodel 이 naive 쓰기를 거부하면 전 턴이 500."""
    from sqlmodel import Field, Session, SQLModel, create_engine

    class _TzProbe(SQLModel, table=True):
        __tablename__ = "tz_probe_pin_test"
        id: Optional[int] = Field(default=None, primary_key=True)
        at: datetime = Field(default_factory=datetime.now)

    eng = create_engine("sqlite://")
    _TzProbe.__table__.create(eng)
    with Session(eng) as s:
        s.add(_TzProbe())
        s.commit()


def test_error_id_middleware_is_inside_cors():
    """5xx 에도 CORS 헤더가 붙으려면 오류 미들웨어가 CORS 안쪽(먼저 등록)이어야 한다."""
    from diag_project.main import app
    names = [m.cls.__name__ for m in app.user_middleware]   # 바깥 → 안쪽 순
    assert "CORSMiddleware" in names and "_ErrorIdMiddleware" in names
    assert names.index("CORSMiddleware") < names.index("_ErrorIdMiddleware")
