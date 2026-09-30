"""운영 DB 테스트 금지 가드 (2026-09-30)."""
import os

from tests.conftest import is_local_database_url


def test_local_urls_allowed_and_remote_refused():
    assert is_local_database_url("sqlite+aiosqlite:///./x.db")
    assert is_local_database_url("postgresql+asyncpg://postgres@localhost/repro")
    assert is_local_database_url("postgresql+asyncpg://postgres@127.0.0.1:5432/repro")
    assert is_local_database_url("postgresql+asyncpg://postgres@/repro?host=/tmp/sock")
    assert not is_local_database_url("postgresql+asyncpg://u:p@aws-1-ap-northeast-2.pooler.supabase.com:6543/postgres")
    assert not is_local_database_url("postgresql://u:p@db.example.com/x")
    assert not is_local_database_url("")


def test_session_database_url_is_local():
    assert is_local_database_url(os.environ.get("DATABASE_URL")), os.environ.get("DATABASE_URL")
