"""대상 PostgreSQL(Supabase)에 누락된 테이블을 모두 생성한다.

migrate_data.py 가 'UndefinedTableError' 로 실패하는 경우, 클라우드 DB 에
테이블 자체가 없기 때문이다. 이 스크립트는 데이터 복사 전에 한 번 실행해
SQLModel.metadata 의 모든 테이블을 생성한다.

원칙:
- 프로젝트의 모든 모델 파일을 import 해 metadata 에 빠짐없이 등록(2번 요구사항).
- DATABASE_URL(.env) 이 asyncpg 라 비동기 엔진 + run_sync(create_all) 사용.
- create_all 은 '없는 테이블만' 만든다(기존 테이블/데이터는 건드리지 않음 → 안전).

실행 방법:
    cd /Users/daniel/python_new/new_diagnosis_api
    /Users/daniel/python_new/.venv/bin/python create_tables.py
"""

import asyncio
import importlib
import os
import pkgutil
import sys

from dotenv import load_dotenv
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel

load_dotenv()

# 2번 요구사항: 모든 모델(테이블) 파일을 빠짐없이 import → metadata 등록.
import diag_project.models as _models_pkg  # noqa: E402

for _m in pkgutil.iter_modules(_models_pkg.__path__):
    importlib.import_module(f"diag_project.models.{_m.name}")

DATABASE_URL = os.getenv("DATABASE_URL")


async def create_tables() -> None:
    if not DATABASE_URL:
        sys.exit("❌ DATABASE_URL 미설정 — .env 를 확인하세요.")

    print(f"☁️  대상(Postgres): {DATABASE_URL.split('@')[-1]}")

    tables = list(SQLModel.metadata.sorted_tables)
    print(f"📦 등록된 테이블 {len(tables)}개:")
    for t in tables:
        print(f"   - {t.name}")

    engine = create_async_engine(DATABASE_URL)
    async with engine.begin() as conn:
        # create_all = 없는 테이블만 생성(checkfirst=True 기본). 기존 데이터 안전.
        await conn.run_sync(SQLModel.metadata.create_all)
    await engine.dispose()

    print("\n✅ 테이블 생성 완료 (이미 있던 테이블/데이터는 그대로 유지).")
    print("➡️  이제 migrate_data.py 로 데이터를 복사하세요.")


if __name__ == "__main__":
    asyncio.run(create_tables())
