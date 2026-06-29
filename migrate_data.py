"""로컬 SQLite → Supabase PostgreSQL 데이터 마이그레이션.

원칙:
- 테이블 생성 X (클라우드에 이미 존재). 순수 '데이터 복사'만 수행.
- 동기 엔진(SQLite, 읽기) / 비동기 엔진(Postgres, 쓰기) 분리.
- FK 제약 오류 방지를 위해 SQLModel.metadata.sorted_tables 로
  '부모 → 자식' 의존성 순서로 INSERT.
- id(UUID)는 프로젝트의 GUID 타입이 SQLite(CHAR str) ↔ PG(uuid) 변환을
  자동 처리하므로 별도 변환 불필요.
- 멱등성: ON CONFLICT DO NOTHING (이미 복사된 행은 건너뜀 → 재실행 안전).
- 내결함성: 배치 INSERT 가 FK 위반 등으로 실패하면 해당 청크를 '행 단위'로
  재시도해(저장점 SAVEPOINT) 문제 행만 건너뛰고 나머지는 모두 저장한다.
  스킵된 행은 어떤 테이블/ID/누락 FK 때문인지 경고로 출력한다.

실행 방법:
    cd /Users/daniel/python_new/new_diagnosis_api
    /Users/daniel/python_new/.venv/bin/python migrate_data.py

    # 다른 SQLite 파일을 원본으로:
    LOCAL_SQLITE_URL="sqlite:///./old.db" \\
        /Users/daniel/python_new/.venv/bin/python migrate_data.py

    # 예행연습(쓰기 없이 행 수만 확인):
    /Users/daniel/python_new/.venv/bin/python migrate_data.py --dry-run
"""

import asyncio
import importlib
import os
import pkgutil
import sys

from dotenv import load_dotenv
from sqlalchemy import create_engine, inspect as sa_inspect, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine
from sqlmodel import SQLModel

load_dotenv()

# 모든 모델을 import 해 SQLModel.metadata 에 전체 테이블을 등록한다.
# (Core 작업만 쓰므로 ORM 매퍼는 구성되지 않음 → 매퍼 관계 이슈와 무관)
import diag_project.models as _models_pkg  # noqa: E402

for _m in pkgutil.iter_modules(_models_pkg.__path__):
    importlib.import_module(f"diag_project.models.{_m.name}")

DATABASE_URL = os.getenv("DATABASE_URL")
LOCAL_SQLITE_URL = os.getenv("LOCAL_SQLITE_URL", "sqlite:///./sql_app.db")
BATCH_SIZE = 500
DRY_RUN = "--dry-run" in sys.argv

# 명시적 FK 의존성 순서 (부모 → 자식).
# 일부 모델은 ForeignKey 제약 없이 평범한 UUID 컬럼이라 sorted_tables 가
# 의존성을 추론하지 못한다. 그래서 핵심 체인은 직접 못박고, 목록에 없는
# 나머지 테이블은 sorted_tables 순서로 뒤이어 처리한다.
EXPLICIT_ORDER = [
    "groups",
    "participants",
    "coaches",
    "coach_personas",
    "competencies",
    "indicators",
    "question_categories",
    "question_choices",
    "diagnosis_templates",
    "diagnosis_questions",
    "diagnosis",
    "diagnosis_sessions",
    "sessions",
    "events",
    "messages",
    "chat_messages",
    "participant_answers",
    "question_answers",
    "evaluation_results",
    "diagnosis_feedbacks",
    "diagnosis_reports",
]


def _ordered_tables():
    """EXPLICIT_ORDER 우선, 나머지는 sorted_tables 순서로 이어붙인다."""
    by_name = {t.name: t for t in SQLModel.metadata.sorted_tables}
    result = []
    seen = set()
    for name in EXPLICIT_ORDER:
        if name in by_name:
            result.append(by_name[name])
            seen.add(name)
    for t in SQLModel.metadata.sorted_tables:
        if t.name not in seen:
            result.append(t)
    return result


def _short_detail(err: Exception) -> str:
    """FK 위반 등의 원인을 사람이 읽을 수 있게 추출.

    asyncpg 의 ForeignKeyViolationError 는 .detail 에
    'Key (session_id)=(...) is not present in table "sessions".' 형태로
    누락된 FK 를 담고 있다.
    """
    orig = getattr(err, "orig", None)
    detail = getattr(orig, "detail", None)
    if detail:
        return str(detail)
    return str(orig or err).splitlines()[0][:160]


async def _copy_table(async_engine, table, rows):
    """배치 INSERT 후, FK 위반 등으로 실패하면 해당 청크를 행 단위로 재시도.

    - 정상 청크는 executemany 로 빠르게 삽입.
    - 실패 청크는 저장점(SAVEPOINT) 기반 '행 단위'로 재시도 → 문제 행만 스킵,
      나머지 정상 행은 모두 저장.
    - 반환: (성공 행 수, [(스킵된 id, 사유), ...]).
    """
    ok = 0
    skipped: list[tuple] = []
    stmt = pg_insert(table).on_conflict_do_nothing()

    async with async_engine.begin() as aconn:
        for i in range(0, len(rows), BATCH_SIZE):
            chunk = rows[i:i + BATCH_SIZE]
            try:
                # 빠른 경로: 청크 통째 삽입 (저장점 안에서 시도)
                async with aconn.begin_nested():
                    await aconn.execute(stmt, chunk)
                ok += len(chunk)
            except IntegrityError:
                # 느린 경로: 문제 청크만 행 단위로 재시도 (행별 저장점)
                for row in chunk:
                    rid = row.get("id", "?")
                    try:
                        async with aconn.begin_nested():
                            await aconn.execute(stmt, [row])
                        ok += 1
                    except IntegrityError as e:
                        reason = _short_detail(e)
                        skipped.append((rid, reason))
                        print(f"  ⚠️  {table.name} 스킵 id={rid} → {reason}")
    return ok, skipped


async def migrate() -> None:
    if not DATABASE_URL:
        sys.exit("❌ DATABASE_URL 미설정 — .env 를 확인하세요.")

    print(f"📂 원본(SQLite): {LOCAL_SQLITE_URL}")
    print(f"☁️  대상(Postgres): {DATABASE_URL.split('@')[-1]}")
    if DRY_RUN:
        print("🧪 DRY-RUN: 쓰기 없이 행 수만 확인합니다.\n")

    sync_engine = create_engine(LOCAL_SQLITE_URL)          # SQLite 읽기 (동기)
    async_engine = create_async_engine(DATABASE_URL)       # Postgres 쓰기 (비동기)

    insp = sa_inspect(sync_engine)
    sqlite_tables = set(insp.get_table_names())
    if not sqlite_tables:
        sys.exit(f"❌ SQLite 에 테이블이 없습니다: {LOCAL_SQLITE_URL}")

    # FK 의존성 순서 (부모 → 자식). 핵심 체인은 명시적, 나머지는 자동 정렬.
    ordered_tables = _ordered_tables()
    print(f"📦 메타데이터 테이블 {len(ordered_tables)}개 (FK 의존성 순)\n")

    # 요약: (테이블명, 성공행, 스킵행, 비고)
    summary: list[tuple[str, int, int, str]] = []

    for table in ordered_tables:
        if table.name not in sqlite_tables:
            summary.append((table.name, 0, 0, "SQLite 에 없음 — 건너뜀"))
            continue

        # SQLite ∩ 메타데이터 공통 컬럼만 복사 (스키마 드리프트 방어)
        sqlite_cols = {c["name"] for c in insp.get_columns(table.name)}
        cols = [c for c in table.columns if c.name in sqlite_cols]
        if not cols:
            summary.append((table.name, 0, 0, "공통 컬럼 없음 — 건너뜀"))
            continue

        # 1) SQLite 에서 읽기 (GUID 결과처리: str → UUID)
        with sync_engine.connect() as sconn:
            rows = [dict(r._mapping) for r in sconn.execute(select(*cols))]

        if not rows:
            summary.append((table.name, 0, 0, "원본 0행"))
            continue

        if DRY_RUN:
            summary.append((table.name, len(rows), 0, "DRY-RUN (미삽입)"))
            print(f"  🧪 {table.name}: {len(rows)}행 (예정)")
            continue

        # 2) Postgres 로 복사 (배치 → 실패 시 행 단위 폴백, FK 위반 행만 스킵)
        try:
            inserted, skipped = await _copy_table(async_engine, table, rows)
            n_skip = len(skipped)
            note = "OK" if n_skip == 0 else f"FK 위반 {n_skip}행 스킵"
            summary.append((table.name, inserted, n_skip, note))
            icon = "✅" if n_skip == 0 else "⚠️ "
            print(f"  {icon} {table.name}: {inserted}행 복사, {n_skip}행 스킵")
        except Exception as e:  # noqa: BLE001
            msg = str(e).splitlines()[0][:120]
            summary.append((table.name, 0, 0, f"실패: {msg}"))
            print(f"  ❌ {table.name}: 실패 — {msg}")

    await async_engine.dispose()
    sync_engine.dispose()

    print("\n================= 마이그레이션 요약 =================")
    total = 0
    total_skip = 0
    for name, n, n_skip, note in summary:
        total += n
        total_skip += n_skip
        print(f"  {name:<28} 복사 {n:>6}  스킵 {n_skip:>4}  {note}")
    print("---------------------------------------------------")
    print(f"  총 복사 행 수: {total}  /  총 스킵 행 수: {total_skip}")
    if total_skip:
        print("  ⚠️  스킵된 행은 부모(FK 대상) 데이터가 없는 고아 데이터입니다.")
        print("      위의 ⚠️ 경고에서 누락된 FK 와 id 를 확인하세요.")
    print("✅ 마이그레이션 완료" if not DRY_RUN else "🧪 DRY-RUN 완료")


if __name__ == "__main__":
    asyncio.run(migrate())
