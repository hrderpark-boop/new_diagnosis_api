"""(2026-10-19) 운영 DB 가드 — 앱 기동 시 비운영 환경이 Supabase 를 가리키면 거부, 로그에는 비밀번호 없음(LLM·DB 없음)."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.db_guard import check_db_allowed, is_prod_db_url, is_production_env, mask_db_url  # noqa: E402

SUPA = "postgresql+asyncpg://postgres.abc:S3cretPw@aws-1-ap-northeast-2.pooler.supabase.com:6543/postgres"
LOCAL_PG = "postgresql+asyncpg://user:pw@localhost:5432/diag"
SQLITE = "sqlite+aiosqlite:///./sql_app.db"


def test_mask_hides_credentials_keeps_host_db():
    m = mask_db_url(SUPA)
    assert "S3cretPw" not in m and "postgres.abc" not in m
    assert m == "postgresql+asyncpg://***@aws-1-ap-northeast-2.pooler.supabase.com:6543/postgres"
    assert mask_db_url(SQLITE) == SQLITE
    assert mask_db_url(None) == "(unset)"


def test_prod_url_detection():
    assert is_prod_db_url(SUPA)
    assert not is_prod_db_url(LOCAL_PG)
    assert not is_prod_db_url(SQLITE)
    assert not is_prod_db_url(None)


def test_production_env_detection():
    assert is_production_env({"ENV": "production"})
    assert is_production_env({"ENV": "Prod"})
    assert is_production_env({"RENDER": "true"})     # Render 자동 주입 폴백
    assert not is_production_env({})
    assert not is_production_env({"ENV": "development"})


def test_refuses_prod_db_outside_production():
    with pytest.raises(RuntimeError) as ei:
        check_db_allowed(SUPA, {})
    msg = str(ei.value)
    assert "S3cretPw" not in msg and "supabase.com" in msg and "ALLOW_PROD_DB=1" in msg
    with pytest.raises(RuntimeError):
        check_db_allowed(SUPA, {"ENV": "development", "ALLOW_PROD_DB": "0"})


def test_allowed_cases():
    check_db_allowed(SUPA, {"ENV": "production"})
    check_db_allowed(SUPA, {"RENDER": "true"})
    check_db_allowed(SUPA, {"ALLOW_PROD_DB": "1"})
    check_db_allowed(LOCAL_PG, {})
    check_db_allowed(SQLITE, {})
    check_db_allowed(None, {})


def test_startup_calls_guard_and_logs_masked():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    main_src = open(os.path.join(root, "diag_project", "main.py"), encoding="utf-8").read()
    db_src = open(os.path.join(root, "diag_project", "database.py"), encoding="utf-8").read()
    assert "check_db_allowed(" in main_src
    assert "mask_db_url(DATABASE_URL)" in db_src
    assert "Database initialized at: {DATABASE_URL}" not in db_src
