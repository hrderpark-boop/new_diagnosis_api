"""step 4: group_code 게이트 라이브 검증 (실제 HTTP, 추정 금지).

전제: 백엔드가 http://127.0.0.1:8000 에서 기동 중 + CNC-PILOT/G-TEST 등록 완료.
용법: python tools/verify_gate.py            (참가자 게이트 6~8번만)
      ADMIN_PW=<비번> python tools/verify_gate.py   (super-admin 로그인 1번 포함)

각 항목의 실제 HTTP 상태코드를 그대로 출력한다. 통과 기대는 200, 거부 기대는 403.
"""
import os
import sys
import urllib.request
import urllib.error
import json

BASE = os.getenv("API_BASE", "http://127.0.0.1:8000/api/v1")


def _post(path: str, body: dict) -> int:
    req = urllib.request.Request(
        BASE + path, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception as e:  # noqa: BLE001
        print(f"    (연결 실패: {e})")
        return -1


def _participant(code, email):
    return _post("/participants/token",
                 {"email": email, "password": "x", "group_code": code,
                  "name": "게이트검증"})


def main():
    print(f"=== step 4 게이트 검증 (BASE={BASE}) ===")
    # 1) super-admin 로그인 (비번 있을 때만)
    pw = os.getenv("ADMIN_PW")
    if pw:
        s = _post("/admin/auth/login",
                  {"email": "ops@connectn.co.kr", "password": pw})
        print(f"  1) super-admin 로그인(ops@connectn.co.kr): {s}  "
              f"{'✅' if s == 200 else '❌ 기대 200'}")
    else:
        print("  1) super-admin 로그인: SKIP (ADMIN_PW 미설정)")

    cases = [
        ("2) CNC-PILOT 로그인", "CNC-PILOT", "gate-v2@test.local", 200),
        ("3) G-TEST 로그인", "G-TEST", "gate-v3@test.local", 200),
        ("4) SIMCO 로그인", "SIMCO", "gate-v4@test.local", 200),
        ("5) 무효코드 ZZZZZ", "ZZZZZ", "gate-v5@test.local", 403),
        ("6) 빈 코드", "", "gate-v6@test.local", 403),
        ("7) cnc-pilot(소문자)", "cnc-pilot", "gate-v7@test.local", 200),
        ("8) ' CNC-PILOT '(공백)", " CNC-PILOT ", "gate-v8@test.local", 200),
    ]
    for label, code, email, expect in cases:
        s = _participant(code, email)
        ok = "✅" if s == expect else f"❌ 기대 {expect}"
        print(f"  {label}: {s}  {ok}")


if __name__ == "__main__":
    main()
