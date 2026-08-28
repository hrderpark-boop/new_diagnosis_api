"""비밀번호 → bcrypt 해시만 출력(DB 접속 없음).

로컬 PC 가 DB(5432)에 못 닿을 때의 대안: 여기서 해시만 만들고, 그 해시를
Supabase 대시보드 SQL Editor 에 붙여 UPDATE 한다. 평문은 로컬을 벗어나지 않는다.

비밀번호는 NEW_ADMIN_PASSWORD env 또는 숨김 입력(getpass)으로만 받는다.

용법:
  cd new_diagnosis_api
  /Users/daniel/python_new/.venv/bin/python tools/make_password_hash.py
  → 해시 출력. 그 해시로 SQL Editor 에서:
    UPDATE admin_users SET password_hash='<붙여넣기>'
    WHERE email='ops@connectn.co.kr';
"""
import getpass
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.services.auth import hash_password  # noqa: E402

_MIN_LEN = 8

if __name__ == "__main__":
    pw = os.getenv("NEW_ADMIN_PASSWORD")
    if not pw:
        pw = getpass.getpass("새 비밀번호(화면에 안 보임): ")
        if getpass.getpass("한 번 더 입력: ") != pw:
            print("🛑 두 입력이 다릅니다."); sys.exit(1)
    if len(pw) < _MIN_LEN:
        print(f"🛑 최소 {_MIN_LEN}자 이상."); sys.exit(2)
    h = hash_password(pw)
    print("\nbcrypt 해시(이 값을 SQL Editor 에 붙여넣기):")
    print(h)
    print("\nSQL Editor 실행문 예시:")
    print("UPDATE admin_users SET password_hash='" + h
          + "' WHERE email='ops@connectn.co.kr';")
