"""고정 사용자 발화 fixture 를 로컬 서버에 리플레이해 턴별 계측(⏱ turn timing)을 모은다.

용법:
  DATABASE_URL="sqlite+aiosqlite:///./sim.db" USE_PHASE3A=true FM_STYLE_TAIL=1 \\
      uvicorn diag_project.main:app --port 8010 > sim_server.log 2>&1 &
  python tools/replay_session.py tests/fixtures/fixture_daniel_users.json --coach 4 --log sim_server.log [--out result.json]

프로덕션 DB 무접촉. 서버 로그의 '⏱ turn timing' 줄을 세션 id 로 묶어 재생성 횟수·시간 비율을 낸다.
"""
import argparse
import json
import os
import re
import sys
import time
import uuid

import httpx

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from diag_project.routes.diagnoses import COACH_UUID_TO_KEY  # noqa: E402

BASE = os.getenv("SIM_BASE", "http://127.0.0.1:8010/api/v1")
TEMPLATE_ID = "10000000-0000-0000-0000-000000000008"
_TIMING = re.compile(
    r"⏱ turn timing session=(\w+) instr=(\S+) decider=([\d.]+)s llm=([\d.]+)s regen=(\d+)\(([\d.]+)s\) "
    r"post\+db=([\d.]+)s total=([\d.]+)s")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("fixture")
    ap.add_argument("--coach", default="4")
    ap.add_argument("--log", default="sim_server.log")
    ap.add_argument("--out", default=None)
    ap.add_argument("--max", type=int, default=0, help="앞에서 N턴만(0=전부)")
    args = ap.parse_args()
    users = json.load(open(args.fixture, encoding="utf-8"))
    if args.max:
        users = users[: args.max]
    coach_uuid = {v: k for k, v in COACH_UUID_TO_KEY.items()}[args.coach]
    pid = str(uuid.uuid4())
    turns = []
    with httpx.Client(timeout=240.0) as c:
        r = c.post(f"{BASE}/diagnoses/start", json={"coach_id": coach_uuid, "participant_id": pid, "template_id": TEMPLATE_ID})
        r.raise_for_status()
        sid = r.json()["session_id"]
        for i, u in enumerate(users):
            t0 = time.perf_counter()
            r = c.post(f"{BASE}/diagnoses/submit_message", json={"session_id": sid, "diagnosis_id": sid, "content": u})
            wall = time.perf_counter() - t0
            r.raise_for_status()
            d = r.json()
            turns.append({"i": i + 1, "user": u, "coach": d["coach_response_message"], "wall": round(wall, 2),
                          "topic_done": d.get("is_topic_completed")})
            print(f"[{i + 1:2d}/{len(users)}] {wall:5.1f}s  {d['coach_response_message'][:90].replace(chr(10), ' ')}")
            # 챕터 전환 팝업 대기면 '네' 로 확인(프론트 버튼과 동일)
            if d.get("is_topic_completed") and d.get("has_next_chapter"):
                r2 = c.post(f"{BASE}/diagnoses/submit_message", json={"session_id": sid, "diagnosis_id": sid, "content": "네, 다음으로 이어가 주세요."})
                r2.raise_for_status()
                turns.append({"i": f"{i + 1}b", "user": "네, 다음으로 이어가 주세요.", "coach": r2.json()["coach_response_message"], "wall": None})
    # 서버 로그에서 이 세션의 계측 줄 수집
    rows = []
    if os.path.exists(args.log):
        for line in open(args.log, encoding="utf-8", errors="ignore"):
            m = _TIMING.search(line)
            if m and sid.replace("-", "").startswith(m.group(1)) or (m and str(sid).startswith(m.group(1))):
                rows.append({"instr": m.group(2), "decider": float(m.group(3)), "llm": float(m.group(4)),
                             "regen_n": int(m.group(5)), "regen_s": float(m.group(6)), "post": float(m.group(7)),
                             "total": float(m.group(8))})
    n = len(rows)
    if n:
        tot = sum(r["total"] for r in rows); rg = sum(r["regen_s"] for r in rows)
        rn = sum(1 for r in rows if r["regen_n"])
        print(f"\n=== 세션 {sid[:8]} 코치 {args.coach}: 턴 {n} | 재생성 걸린 턴 {rn} ({rn / n:.0%}) | 재생성 시간 {rg:.1f}s / 총 {tot:.1f}s ({rg / tot:.0%})")
        print(f"    평균: decider {sum(r['decider'] for r in rows) / n:.2f}s  llm {sum(r['llm'] for r in rows) / n:.2f}s  "
              f"post+db {sum(r['post'] for r in rows) / n:.2f}s  total {tot / n:.2f}s")
        print("    재생성 턴:", [(i + 1, r["instr"], r["regen_n"]) for i, r in enumerate(rows) if r["regen_n"]])
    else:
        print("\n(서버 로그에서 계측 줄을 찾지 못함 — --log 경로 확인)")
    if args.out:
        json.dump({"session": sid, "turns": turns, "timing": rows}, open(args.out, "w"), ensure_ascii=False, indent=1)
        print("→", args.out)


if __name__ == "__main__":
    main()
