"""회귀: 코치 턴 LLM_ERROR 3회 연속 → 세션 paused, 상태(메시지·원장) 무변경 (2026-09-22, 파일럿 전 필수).

실서버 경로를 그대로 탄다: 로컬 sqlite + FM_LLM_STUB=error(LLM 호출 실패 흉내)로 uvicorn 을 띄우고 API 로 3턴 보낸다.
"""
import os
import shutil
import socket
import subprocess
import sys
import time
import uuid
import sqlite3

import httpx
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEMPLATE_ID = "10000000-0000-0000-0000-000000000008"


def _free_port() -> int:
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


@pytest.fixture(scope="module")
def server():
    if shutil.which("uvicorn") is None and not os.path.exists(os.path.join(os.path.dirname(sys.executable), "uvicorn")):
        pytest.skip("uvicorn 없음")
    port = _free_port()
    db = os.path.join(ROOT, f"test_llm_error_{port}.db")
    env = dict(os.environ, DATABASE_URL=f"sqlite+aiosqlite:///{db}", USE_PHASE3A="true", FM_LLM_STUB="error")
    proc = subprocess.Popen([sys.executable, "-m", "uvicorn", "diag_project.main:app", "--port", str(port)],
                            cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    base = f"http://127.0.0.1:{port}/api/v1"
    try:
        for _ in range(60):
            try:
                if httpx.get(f"http://127.0.0.1:{port}/openapi.json", timeout=2).status_code == 200:
                    break
            except Exception:
                pass
            time.sleep(0.5)
        else:
            proc.kill(); pytest.skip("서버 기동 실패")
        yield base, db
    finally:
        proc.kill(); proc.wait(timeout=10)
        for f in (db, db + "-journal", db + "-wal"):
            if os.path.exists(f):
                os.remove(f)


def test_llm_error_three_times_pauses_session_without_state_change(server):
    base, db = server
    from diag_project.routes.diagnoses import COACH_UUID_TO_KEY
    coach_uuid = {v: k for k, v in COACH_UUID_TO_KEY.items()}["4"]
    pid = str(uuid.uuid4())
    with httpx.Client(timeout=60) as c:
        r = c.post(f"{base}/diagnoses/start", json={"coach_id": coach_uuid, "participant_id": pid, "template_id": TEMPLATE_ID})
        assert r.status_code == 201, r.text
        sid = r.json()["session_id"]
        con = sqlite3.connect(db)

        def _count():
            return max(con.execute("select count(*) from chat_messages where session_id=?", (k,)).fetchone()[0]
                       for k in (sid, sid.replace("-", "")))
        n_before = _count()
        # 온보딩 첫 턴들은 시스템 템플릿(LLM 미호출)이라 정상 응답이 올 수 있다 → LLM 을 실제로 부르는 턴에서만 실패가 난다.
        errors = []
        for i in range(8):
            n0 = _count()
            r = c.post(f"{base}/diagnoses/submit_message", json={"session_id": sid, "diagnosis_id": sid, "content": f"안녕하세요, 박기진입니다. {i}번째 답변이에요."})
            assert r.status_code in (200, 201), r.text
            d = r.json()
            if d.get("llm_error") is True:
                assert d["_phase3a_metadata"]["guard"] == "LLM_ERROR"
                assert _count() == n0, "LLM 실패 턴은 메시지를 하나도 저장하지 않아야 한다"
                errors.append(d)
                if d["is_session_paused"]:
                    break
            else:
                assert len(errors) == 0, "실패가 시작된 뒤에는 정상 턴이 나올 수 없다(스텁이 항상 실패)"
        assert [e["llm_error_streak"] for e in errors] == [1, 2, 3], errors
        assert errors[0]["is_session_paused"] is False and "다시 시도" in errors[0]["coach_response_message"]
        d = errors[-1]
        assert d["is_session_paused"] is True and d["session_status"] == "paused"
        assert "이어서" in d["coach_response_message"]
        row = con.execute("select status from diagnosis_sessions").fetchone()
        assert row[0] == "paused"
        # 세션 상태 조회도 paused
        st = c.get(f"{base}/diagnoses/{sid}/state").json()
        assert st["status"] == "paused" and st["is_paused"] is True
