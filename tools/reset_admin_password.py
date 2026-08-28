"""관리자 비밀번호 재설정 (admin_users.password_hash 갱신).

🔐 비밀번호는 '절대' 인자로 받지 않는다(쉘 기록·프로세스 목록 노출 방지).
   - 우선순위 1: 환경변수 NEW_ADMIN_PASSWORD
   - 우선순위 2: 없으면 실행 중 숨김 입력(getpass)으로 물어봄
   어느 쪽도 이 파일/커밋에 값이 남지 않는다.

대상 DB: DATABASE_URL 이 가리키는 곳. 관리자 페이지는 프로덕션에서 쓰므로
   반드시 프로덕션(Supabase) DATABASE_URL 로 실행해야 한다. 실행 전 접속 호스트를
   마스킹해 출력하니 Supabase 가 맞는지 확인하고 진행할 것.

용법:
  cd new_diagnosis_api
  # 방법 A (권장): 환경변수로 비번 전달
  NEW_ADMIN_PASSWORD='새비밀번호' /Users/daniel/python_new/.venv/bin/python \
      tools/reset_admin_password.py
  # 방법 B: 비번 없이 실행 → 숨김 입력 프롬프트가 뜸
  /Users/daniel/python_new/.venv/bin/python tools/reset_admin_password.py
  # 이메일 바꾸려면(기본 ops@connectn.co.kr):
  ... tools/reset_admin_password.py --email other@connectn.co.kr
"""
import argparse
import asyncio
import getpass
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), ".env"))

from diag_project.services.auth import hash_password  # noqa: E402

_DEFAULT_EMAIL = "ops@connectn.co.kr"
_MIN_LEN = 8


def _mask_dsn(dsn: str) -> str:
    """자격증명 숨기고 host 만 보이게."""
    return re.sub(r"://[^@]*@", "://<자격증명숨김>@", dsn or "")


async def main(email: str, new_password: str, port: int | None) -> int:
    import asyncpg
    dsn = os.getenv("DATABASE_URL") or os.getenv("DATABASE_URI")
    if not dsn:
        print("🛑 DATABASE_URL 이 설정돼 있지 않습니다. .env 또는 환경변수 확인.")
        return 2
    conn_dsn = dsn.replace("postgresql+asyncpg://", "postgresql://")
    # 포트 오버라이드(회사망이 5432 를 막으면 6543=Transaction 풀러로).
    #   DSN 의 자격증명은 그대로 두고 포트만 바꾼다(전체 URL 을 손입력하지 않게).
    if port:
        conn_dsn = re.sub(r"(:)\d+(/)", rf"\g<1>{port}\g<2>", conn_dsn, count=1)

    # 실행 전 접속 대상 확인(프로덕션 Supabase 인지 눈으로 확인).
    print(f"접속 대상 DB: {_mask_dsn(conn_dsn)}")
    if "supabase" not in conn_dsn:
        print("⚠️ 주의: DATABASE_URL 에 'supabase' 가 없습니다. 로컬/다른 DB 일 수 "
              "있습니다. 프로덕션(Supabase)이 맞는지 반드시 확인하세요.")

    new_hash = hash_password(new_password)  # bcrypt (admin_login 과 동일 검증)

    # statement_cache_size=0: Transaction 풀러(6543, PgBouncer)에서 prepared
    #   statement 미지원으로 나는 오류를 막는다(세션 모드에도 무해). timeout 로
    #   무한 대기 방지.
    conn = await asyncpg.connect(conn_dsn, statement_cache_size=0, timeout=15)
    try:
        row = await conn.fetchrow(
            "SELECT id, email, role, is_active FROM admin_users WHERE email=$1",
            email)
        if not row:
            print(f"🛑 계정 없음: {email} (admin_users). 이메일 확인.")
            return 3
        print(f"대상 계정: {row['email']} | role={row['role']} | "
              f"active={row['is_active']}")
        await conn.execute(
            "UPDATE admin_users SET password_hash=$1 WHERE email=$2",
            new_hash, email)
    finally:
        await conn.close()

    print(f"✅ 비밀번호 재설정 완료: {email}")
    print("   (해시만 저장됨 — 평문은 어디에도 남지 않습니다. 새 비번으로 "
          "/admin/login 로그인해 확인하세요.)")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="관리자 비밀번호 재설정")
    ap.add_argument("--email", default=_DEFAULT_EMAIL)
    ap.add_argument("--port", type=int, default=None,
                    help="DB 포트 오버라이드(회사망이 5432 차단 시 6543 사용).")
    args = ap.parse_args()

    pw = os.getenv("NEW_ADMIN_PASSWORD")
    if not pw:
        pw = getpass.getpass("새 비밀번호(입력 시 화면에 안 보임): ")
        pw2 = getpass.getpass("한 번 더 입력: ")
        if pw != pw2:
            print("🛑 두 입력이 다릅니다. 중단.")
            sys.exit(4)
    if len(pw) < _MIN_LEN:
        print(f"🛑 비밀번호는 최소 {_MIN_LEN}자 이상이어야 합니다.")
        sys.exit(5)

    sys.exit(asyncio.run(main(args.email, pw, args.port)))
