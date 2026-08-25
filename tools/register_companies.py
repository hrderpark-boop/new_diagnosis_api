"""파일럿 회사 코드 등록 (결정1·3). idempotent upsert.

용법: python tools/register_companies.py <contact_email>
등록: CNC-PILOT, G-TEST (name=커넥트앤컴퍼니, is_active=True).
코드는 strip+upper 정규화(로그인 게이트와 동일 기준). 이미 있으면 contact_email·
is_active 갱신. 실행 후 companies 목록을 출력해 확인시킨다.
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), ".env"))

_RECORDS = [
    ("커넥트앤컴퍼니", "CNC-PILOT"),
    ("커넥트앤컴퍼니", "G-TEST"),
]


async def main(contact_email: str):
    import asyncpg
    u = (os.getenv("DATABASE_URL") or os.getenv("DATABASE_URI")).replace(
        "postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(u)
    now = datetime.now(timezone.utc)
    for name, code in _RECORDS:
        norm = code.strip().upper()
        # unique(code) 기준 upsert — 있으면 contact_email·is_active·updated_at 갱신.
        await conn.execute(
            """
            INSERT INTO companies (id, name, code, contact_email, is_active,
                                   created_at, updated_at)
            VALUES ($1, $2, $3, $4, TRUE, $5, $5)
            ON CONFLICT (code) DO UPDATE
              SET contact_email = EXCLUDED.contact_email,
                  is_active = TRUE,
                  updated_at = EXCLUDED.updated_at
            """,
            uuid.uuid4(), name, norm, contact_email, now,
        )
        print(f"  ✅ upsert: {norm} ({name})")

    print("\n=== 등록 후 companies 목록 ===")
    rows = await conn.fetch(
        "SELECT code, is_active, contact_email, name FROM companies "
        "ORDER BY code")
    for r in rows:
        print(f"  {r['code']:<12} active={r['is_active']} "
              f"email={r['contact_email']} {r['name']}")
    await conn.close()


if __name__ == "__main__":
    if len(sys.argv) < 2 or "@" not in sys.argv[1]:
        print("사용법: python tools/register_companies.py <contact_email>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
