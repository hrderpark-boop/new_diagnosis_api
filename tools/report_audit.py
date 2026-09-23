"""리포트 감사(읽기 전용) — participant 필드, 26개 하위역량 렌더, 추천 카드 4장, 인용문 verbatim.

용법: python tools/report_audit.py <email_like>
"""
import asyncio
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))


def _norm(t: str) -> str:
    return re.sub(r"[\s\"'“”‘’.,!?…·*()\[\]-]", "", t or "")


async def main():
    if len(sys.argv) < 2:
        print(__doc__); return
    import asyncpg
    u = os.getenv("DATABASE_URL").replace("postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(u, statement_cache_size=0)
    s = await conn.fetchrow(
        "SELECT s.id, s.status, s.user_id, p.name, p.email, p.group_code, p.company_id FROM diagnosis_sessions s "
        "JOIN participants p ON s.user_id=p.id WHERE p.email LIKE $1 ORDER BY s.created_at DESC LIMIT 1", sys.argv[1])
    if not s:
        print("세션 없음"); await conn.close(); return
    print(f"세션 {str(s['id'])[:8]} status={s['status']} | participant name={s['name']!r} email={s['email']} group={s['group_code']} company_id={s['company_id']}")
    r = await conn.fetchrow("SELECT id, total_score, summary, scores, created_at FROM diagnosis_reports WHERE session_id=$1 ORDER BY created_at DESC LIMIT 1", s["id"])
    if not r:
        print("리포트 없음"); await conn.close(); return
    sc = r["scores"]; sc = json.loads(sc) if isinstance(sc, str) else (sc or {})
    print(f"리포트 {str(r['id'])[:8]} total={r['total_score']} created={r['created_at']} | scores keys={list(sc.keys())}")
    details = sc.get("details") or {}
    print(f"\n== 하위역량 렌더: {len(details)}개 (기대 26)")
    from diag_project.data.competencies import COMPETENCY_FRAMEWORK as CF
    all_names = [v.get("name") for c in CF.values() for v in (c.get("indicators") or {}).values()]
    missing = [n for n in all_names if n not in details]
    print("  프레임워크 26 중 누락:", missing or "없음")
    users = await conn.fetch("SELECT content FROM chat_messages WHERE session_id=$1 AND role='user'", s["id"])
    corpus = _norm(" ".join((x["content"] or "") for x in users))
    total_ev = found_ev = 0; empty_fields = []
    for name, d in details.items():
        if not isinstance(d, dict):
            continue
        for f in ("comment", "strength_point", "growth_point", "gap_analysis"):
            if not (d.get(f) or "").strip():
                empty_fields.append(f"{name}.{f}")
        rp = d.get("reasoning_process") or {}
        for step, val in rp.items():
            evs = (val.get("evidence") if isinstance(val, dict) else None) or []
            for e in evs:
                if not e:
                    continue
                total_ev += 1
                k = _norm(e)
                if k and (k in corpus or (len(k) > 20 and k[:20] in corpus)):
                    found_ev += 1
                else:
                    print(f"  ✗ verbatim 아님 [{name}/{step}]: {e[:80]!r}")
    print(f"  빈 필드 {len(empty_fields)}: {empty_fields[:10]}")
    print(f"\n== 인용문 verbatim: {found_ev}/{total_ev} 이 사용자 발화에 그대로 존재")
    cr = sc.get("course_recommendation")
    if isinstance(cr, dict):
        lists = {k: v for k, v in cr.items() if isinstance(v, list)}
        print(f"\n== 추천: keys={list(cr.keys())} | 목록 크기 { {k: len(v) for k, v in lists.items()} }")
        for k, v in lists.items():
            for c in v[:6]:
                if isinstance(c, dict):
                    print(f"  - [{k}] " + " | ".join(f"{kk}={str(vv)[:40]!r}" for kk, vv in list(c.items())[:4]))
    else:
        print("\n== 추천: 없음 또는 비정형", type(cr).__name__)
    print("\n== coverage:", sc.get("coverage"))
    await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
