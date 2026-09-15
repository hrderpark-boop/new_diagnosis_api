"""코치 페르소나 톤 비교 시뮬레이션 — 6명 × 고정 사용자 스크립트 6턴(코치 턴만 LLM 생성).

실제 파이프라인(라포 → 이름 확인 → 안내 → 정의 질문·제시+첫 앵커 → 되받기)을 로컬 서버
(sqlite, 포트 8010)에 HTTP 로 그대로 태워서, 같은 단계의 코치 발화를 코치별로 나란히 뽑는다.
프로덕션 DB 에는 아무것도 쓰지 않는다.

용법:  DATABASE_URL="sqlite+aiosqlite:///./sim.db" USE_PHASE3A=true uvicorn diag_project.main:app --port 8010
       python tools/coach_tone_sim.py [out.json]
"""
import asyncio
import json
import os
import sqlite3
import sys
import uuid

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from diag_project.data.coaches_persona import COACHES_PERSONA  # noqa: E402
from diag_project.routes.diagnoses import COACH_UUID_TO_KEY  # noqa: E402

BASE = os.getenv("SIM_BASE", "http://127.0.0.1:8010/api/v1")
TEMPLATE_ID = "10000000-0000-0000-0000-000000000008"

# 고정 사용자 스크립트(kjpark 실세션 도입부와 같은 결) — 모든 코치에 동일
USER_SCRIPT = [
    "안녕하세요, 박기진입니다.",
    "오전은 그냥 그래요. 일이 좀 있죠.",
    "그다지 기대하는 건 없어요.",
    "네 좋아요.",
    "조직을 효율적으로 관리하는 거요. 리더는 늘 한정된 자원에서 성과를 내야 하잖아요.",
    "음.. 새로 교육체계를 개편하라고 했는데 팀원들이 왜 해야 하는지, 일만 많아지는 것 아니냐고 불평했던 때가 있어요.",
]


async def run_one(key: str, coach_uuid: str) -> dict:
    pid = str(uuid.uuid4())   # sqlite 는 FK 를 강제하지 않아 참가자 행 없이도 세션이 생긴다(이름은 '리더' 폴백)
    turns = []
    async with httpx.AsyncClient(timeout=180.0) as c:
        r = await c.post(f"{BASE}/diagnoses/start", json={
            "coach_id": coach_uuid, "participant_id": pid, "template_id": TEMPLATE_ID})
        r.raise_for_status()
        d = r.json()
        sid = d["session_id"]
        turns.append({"stage": "인사(템플릿)", "user": None, "coach": d["coach_response_message"]})
        for u in USER_SCRIPT:
            r = await c.post(f"{BASE}/diagnoses/submit_message", json={
                "session_id": sid, "diagnosis_id": sid, "content": u})
            r.raise_for_status()
            turns.append({"stage": None, "user": u, "coach": r.json()["coach_response_message"]})
    return {"key": key, "name": COACHES_PERSONA[key]["name"], "session_id": sid, "turns": turns}


def _label_from_db(results: list[dict]) -> None:
    """sqlite 에서 instruction_used/probe_type 을 읽어 단계 라벨을 붙인다."""
    db = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sim.db")
    if not os.path.exists(db):
        return
    con = sqlite3.connect(db)
    for res in results:
        rows = con.execute(
            "select instruction_used, probe_type_used from chat_messages "
            "where session_id=? and role='model' order by created_at, turn_index",
            (res["session_id"].replace("-", ""),)).fetchall()
        if not rows:  # GUID 저장 형식이 다르면 하이픈 포함으로 재시도
            rows = con.execute(
                "select instruction_used, probe_type_used from chat_messages "
                "where session_id=? and role='model' order by created_at, turn_index",
                (res["session_id"],)).fetchall()
        for t, (instr, ptype) in zip(res["turns"], rows):
            t["instruction"] = instr
            t["probe_type"] = ptype
    con.close()


async def main():
    keys = sorted(COACHES_PERSONA.keys(), key=int)
    if "--only" in sys.argv:                      # 예: --only 5  (Michael 만)
        i = sys.argv.index("--only"); keys = [sys.argv[i + 1]]; del sys.argv[i:i + 2]
    uuid_of = {v: k for k, v in COACH_UUID_TO_KEY.items()}
    results = await asyncio.gather(*[run_one(k, uuid_of[k]) for k in keys])
    _label_from_db(list(results))
    out = sys.argv[1] if len(sys.argv) > 1 else "coach_tone_sim.json"
    json.dump(list(results), open(out, "w"), ensure_ascii=False, indent=1)
    for res in results:
        _ex = sum(t["coach"].count("!") for t in res["turns"][1:])
        print(f"\n===== {res['name']} ({res['session_id'][:8]})  느낌표 합계(코치 턴 1~6): {_ex}")
        for i, t in enumerate(res["turns"]):
            print(f"[{i}] {t.get('instruction') or t['stage'] or ''} / {t.get('probe_type') or ''}")
            if t["user"]:
                print(f"   👤 {t['user']}")
            print(f"   🤖 {t['coach'][:400]}")
    print(f"\n→ {out}")


if __name__ == "__main__":
    asyncio.run(main())
