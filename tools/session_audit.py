"""실세션 챕터 감사(읽기 전용) — 원장·guard_log·턴 시간을 한 표로.

용법: python tools/session_audit.py <email_like> [chapter_key] [--all]
  chapter_key 기본 people_management. --all 이면 전 챕터.
출력: 진입 경로(정의 질문/합의), asked_subs, 사건, 턴별(instr / 위반 / 재생성 / 하드교정 / llm·total s / 코치 첫 60자),
      부재 폴백(ABSENCE_PROBE) 턴, 결과 질문 풀 사용, 연결 절 사용 턴, 칭찬·느낌표 0건 확인.
"""
import asyncio
import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))

from diag_project.services.output_guard import find_praise  # noqa: E402
from diag_project.services.traversal import RESULT_PROBE_POOL  # noqa: E402

_BRIDGE = re.compile(r"(방금|앞서|아까)?\s*말씀하신\s*['\"“‘][^'\"”’]{1,10}['\"”’]")


async def main():
    if len(sys.argv) < 2:
        print(__doc__); return
    email_like = sys.argv[1]
    chapter = next((a for a in sys.argv[2:] if not a.startswith("--")), "people_management")
    all_ch = "--all" in sys.argv
    import asyncpg
    u = os.getenv("DATABASE_URL").replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(u, statement_cache_size=0)
    s = await conn.fetchrow(
        "SELECT s.id, s.status, s.current_topic, s.self_assessment_data, s.created_at, c.name AS coach "
        "FROM diagnosis_sessions s JOIN participants p ON s.user_id=p.id LEFT JOIN coaches c ON c.id=s.coach_id "
        "WHERE p.email LIKE $1 ORDER BY s.created_at DESC LIMIT 1", email_like)
    if not s:
        print("세션 없음"); await conn.close(); return
    sad = s["self_assessment_data"]; sad = json.loads(sad) if isinstance(sad, str) else (sad or {})
    ms = await conn.fetch("SELECT role, content, chapter, probe_type_used, instruction_used, turn_index, created_at "
                          "FROM chat_messages WHERE session_id=$1 ORDER BY created_at, turn_index", s["id"])
    ev = await conn.fetch("SELECT chapter, mapped_subcompetency, star_coverage, is_complete, probe_count FROM events "
                          "WHERE session_id=$1 ORDER BY started_at", s["id"])
    await conn.close()
    print(f"세션 {str(s['id'])[:8]} {s['coach']} status={s['status']} topic={s['current_topic']} msgs={len(ms)}")
    chapters = sorted({m["chapter"] for m in ms if m["chapter"]}) if all_ch else [chapter]
    gl = {g.get("t"): g for g in (sad.get("guard_log") or []) if isinstance(g, dict)}
    for ch in chapters:
        rows = [m for m in ms if m["chapter"] == ch]
        print(f"\n===== {ch}")
        print("asked_subs:", (sad.get("asked_subs") or {}).get(ch), "| turns_on_target:", (sad.get("turns_on_target") or {}).get(ch),
              "| result_probed:", (sad.get("result_probed") or {}).get(ch), "| opening_merged:", (sad.get("opening_merged") or {}).get(ch))
        print("사건:", [(e["mapped_subcompetency"], e["star_coverage"], e["is_complete"], e["probe_count"]) for e in ev if e["chapter"] == ch])
        print("결과 질문 풀 사용 idx:", (sad.get("result_probe_used") or {}).get(ch))
        firsts = [m for m in rows if m["role"] == "model"][:3]
        print("진입 첫 3 코치 턴:", [(m["turn_index"], m["instruction_used"]) for m in firsts])
        print(f"\n{'턴':>3} {'instr':26} {'위반':22} {'재생':4} {'하드':4} {'llm':5} {'tot':5}  코치 첫 70자")
        hard = regen = praise = excl = absence = bridge = pool = 0; coach_n = 0
        prev_user = ""
        for m in rows:
            if m["role"] == "user":
                prev_user = m["content"] or ""; continue
            coach_n += 1
            g = gl.get(m["turn_index"], {})
            v = ",".join(g.get("v") or [])
            hard += 1 if g.get("hard") else 0; regen += g.get("regen") or 0
            c = m["content"] or ""
            praise += len(find_praise(c)); excl += c.count("!")
            absence += 1 if m["instruction_used"] == "ABSENCE_PROBE" else 0
            bridge += 1 if _BRIDGE.search(c) else 0
            pool += 1 if any(q in c for q in RESULT_PROBE_POOL) else 0
            dt = ""
            if g.get("llm") is not None:
                dt = f"{g.get('llm'):5.1f} {g.get('total'):5.1f}"
            print(f"{str(m['turn_index']):>3} {str(m['instruction_used'])[:26]:26} {v[:22]:22} {str(g.get('regen', '')):4} "
                  f"{'예' if g.get('hard') else '-':4} {dt:11}  {c[:70].replace(chr(10), ' ')}")
        ts = [m["created_at"] for m in rows if isinstance(m["created_at"], datetime)]
        dur = (ts[-1] - ts[0]).total_seconds() / 60 if len(ts) > 1 else 0
        print(f"\n요약 [{ch}]: 코치 턴 {coach_n} | 재생성 {regen} | 하드 교정 {hard} ({hard / max(coach_n, 1):.0%}) | "
              f"칭찬 표현 {praise} | 느낌표 {excl} | 부재 폴백(ABSENCE_PROBE) {absence} | 연결 절 사용 {bridge} | "
              f"결과 질문 풀 문장 {pool} | 소요 {dur:.1f}분")


if __name__ == "__main__":
    asyncio.run(main())
