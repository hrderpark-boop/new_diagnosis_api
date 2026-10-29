"""테스트 하네스 (2026-09-30 운영 DB 가드 + 2026-10-16 공용 fixture 복원).

■ 운영 DB 가드(유지)
배경: 에이전트가 tests/test_chat_flow.py 를 DATABASE_URL 없이 돌려 .env 의 운영 DB 에 접속했다(읽기뿐이었지만 같은 경로로
쓰기 테스트가 돌면 운영 데이터가 오염된다).
규칙:
- DATABASE_URL 환경변수가 없으면 세션마다 새로 만든 임시 sqlite 파일을 쓴다(.env 의 운영 URL 보다 먼저 — load_dotenv 는
  기존 env 를 덮지 않는다). 테스트 간 상태가 다음 실행으로 새지 않는다.
- DATABASE_URL 이 localhost/127.0.0.1/sqlite 가 아니면 수집 자체를 거부하고 중단한다.

■ 공용 fixture(복원)
git 이력상 client/auth_headers/async_client fixture 는 한 번도 커밋된 적이 없다(4f60760 에 테스트 파일만 추가됨,
6c27391 은 가드만 추가). 여기서 처음 정의한다.
- client       : `with TestClient(app)` — startup(SECRET_KEY 검증·init_db) 실행. 세션 범위.
- auth_headers : 테스트 DB 에 super_admin 계정을 만들고 발급한 JWT 헤더.
- async_client : httpx.AsyncClient(ASGITransport) — test_diagnosis_flow 용.
- seed_data    : seed.py 의 시드(코치·템플릿·G-TEST) 적재 — test_chat_flow 용.
테스트 전용 환경 기본값: SECRET_KEY(테스트 키), GEMINI_API_KEYS=dummy(실호출·과금 방지), FM_SYNTHETIC_CHECK=0.
"""
import os
import re
import tempfile

import pytest
import pytest_asyncio

_LOCAL_RE = re.compile(r"^(sqlite|postgresql(\+\w+)?://[^@]*@(localhost|127\.0\.0\.1|/)|postgresql(\+\w+)?://(localhost|127\.0\.0\.1))", re.I)
_DEFAULT_TEST_DB = "sqlite+aiosqlite:///./.pytest_local.db"  # 하위 호환(문구·테스트 참조용). 실제 기본은 임시 파일.


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
        tmp = tempfile.mkdtemp(prefix="fm-pytest-")
        os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{os.path.join(tmp, 'test.db')}"
    elif not is_local_database_url(url):
        pytest.exit(
            "운영 DB에 대한 테스트 실행 금지: DATABASE_URL 이 localhost/sqlite 가 아닙니다. "
            "예) DATABASE_URL=sqlite+aiosqlite:///./.pytest_local.db pytest", returncode=3,
        )
    # 테스트 전용 기본값 — .env(load_dotenv)는 기존 env 를 덮지 않으므로 여기서 먼저 잡으면 운영 값이 쓰이지 않는다.
    os.environ.setdefault("SECRET_KEY", "pytest-only-secret-key-" + "0" * 40)
    os.environ.setdefault("GEMINI_API_KEYS", "dummy")
    os.environ.setdefault("ANTHROPIC_API_KEY", "dummy")   # (2026-10-29) 기본 provider claude — 기동 검증 통과용(실호출 없음)
    os.environ.setdefault("FM_SYNTHETIC_CHECK", "0")


# ── 공용 fixture ────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_rate_limits():
    """(2026-10-29) 로그인 시도 제한은 메모리 상태라 테스트끼리 섞이지 않게 매번 비운다(TestClient IP 가 같다)."""
    from diag_project.services import rate_limit
    rate_limit.reset_all()
    yield


@pytest.fixture(scope="session")
def client():
    """FastAPI TestClient. with-문으로 startup 이벤트(SECRET_KEY 검증·init_db·경량 마이그레이션)를 실행한다."""
    from fastapi.testclient import TestClient
    from diag_project.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def auth_headers(client):
    """super_admin 계정을 테스트 DB 에 만들고 JWT 헤더를 돌려준다(앱 이벤트 루프에서 실행)."""
    from diag_project.database import async_session
    from diag_project.models.admin_user import AdminUser, UserRole
    from diag_project.services.auth import create_access_token, hash_password

    async def _make_admin():
        async with async_session() as db:
            admin = AdminUser(
                email="pytest-super@test.local", name="pytest super admin",
                role=UserRole.SUPER_ADMIN.value,
                password_hash=hash_password("pytest-password-1"),
            )
            db.add(admin)
            await db.commit()
            await db.refresh(admin)
            return admin

    admin = client.portal.call(_make_admin)
    return {"Authorization": f"Bearer {create_access_token(admin)}"}


@pytest.fixture(scope="session")
def seed_data(client):
    """seed.py 의 시드(코치 6명·페르소나·템플릿·G-TEST 그룹/참가자)를 테스트 DB 에 적재한다.

    seed.py 는 레거시 groups 행만 만들고, 현재 로그인 게이트는 companies.code 를 본다
    (운영에는 tools/register_companies.py 로 G-TEST 가 등록돼 있다) → 여기서 companies 에 G-TEST 도 넣는다.
    """
    from seed import seed_data as _seed
    from sqlalchemy import select
    from diag_project.database import async_session
    from diag_project.models.company import Company

    async def _seed_all():
        await _seed()
        async with async_session() as db:
            exists = (await db.execute(select(Company).where(Company.code == "G-TEST"))).scalars().first()
            if not exists:
                db.add(Company(name="커넥트앤컴퍼니", code="G-TEST", is_active=True))
                await db.commit()

    client.portal.call(_seed_all)
    return True


@pytest_asyncio.fixture
async def async_client(client):
    """httpx AsyncClient(ASGI 직결). startup 은 client fixture 가 이미 실행했다."""
    from httpx import ASGITransport, AsyncClient
    from diag_project.main import app

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://testserver") as ac:
        yield ac
