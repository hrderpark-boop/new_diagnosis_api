"""테스트 안전장치 (2026-09-30): 운영 DB 에 대한 테스트 실행 금지.

배경: 에이전트가 tests/test_chat_flow.py 를 DATABASE_URL 없이 돌려 .env 의 운영 DB 에 접속했다(읽기뿐이었지만 같은 경로로
쓰기 테스트가 돌면 운영 데이터가 오염된다).
규칙:
- DATABASE_URL 환경변수가 없으면 로컬 sqlite 테스트 DB 를 기본으로 잡는다(.env 의 운영 URL 보다 먼저 — load_dotenv 는 기존 env 를 덮지 않는다).
- DATABASE_URL 이 localhost/127.0.0.1/sqlite 가 아니면 수집 자체를 거부하고 중단한다.
"""
import os
import re

import pytest

_LOCAL_RE = re.compile(r"^(sqlite|postgresql(\+\w+)?://[^@]*@(localhost|127\.0\.0\.1|/)|postgresql(\+\w+)?://(localhost|127\.0\.0\.1))", re.I)
_DEFAULT_TEST_DB = "sqlite+aiosqlite:///./.pytest_local.db"


def is_local_database_url(url: str | None) -> bool:
    if not url:
        return False
    if url.lower().startswith("sqlite"):
        return True
    # host 부분이 localhost/127.0.0.1 또는 유닉스 소켓(host 없음)
    m = re.match(r"^[a-z+]+://(?:[^@/]*@)?([^/:?]*)", url, re.I)
    host = (m.group(1) if m else "").lower()
    return host in ("localhost", "127.0.0.1", "")


def pytest_configure(config):
    url = os.environ.get("DATABASE_URL")
    if not url:
        os.environ["DATABASE_URL"] = _DEFAULT_TEST_DB
        return
    if not is_local_database_url(url):
        pytest.exit(
            "운영 DB에 대한 테스트 실행 금지: DATABASE_URL 이 localhost/sqlite 가 아닙니다. "
            "예) DATABASE_URL=sqlite+aiosqlite:///./.pytest_local.db pytest", returncode=3,
        )
