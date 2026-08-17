"""§4/§8: 세션 fixture export + 재분석 하버스트 (대화생성 없이 분석만).

용법:
  export  <email_like>  <out.json>   : DB 세션 → fixture JSON 저장
  analyze <in.json>                  : fixture 재분석 → measured/gate/추천 + 계측
  compare <in.json>                  : 동일 fixture 2회 재분석 결과 대조(±노이즈)

핵심: 새 대화 sim 을 돌리지 않는다. 이미 DB 에 있는 세션을 export 해 fixture 로
고정하고, 이후 로직 변경은 이 fixture 재분석으로만 검증한다(§9 준수).
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), ".env"))


async def _load_session(email_like: str) -> dict:
    import asyncpg
    u = (os.getenv("DATABASE_URL") or os.getenv("DATABASE_URI")).replace(
        "postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(u)
    r = await conn.fetchrow(
        "SELECT s.id, s.self_assessment_data, p.name FROM diagnosis_sessions s "
        "JOIN participants p ON s.user_id=p.id WHERE p.email LIKE $1 "
        "ORDER BY s.created_at DESC LIMIT 1", email_like)
    sid = r["id"]
    msgs = await conn.fetch(
        "SELECT role, content, chapter, instruction_used FROM chat_messages "
        "WHERE session_id=$1 ORDER BY created_at ASC", sid)
    evs = await conn.fetch(
        "SELECT chapter, sequence_num, situation, task, action, result, "
        "summary, mapped_subcompetency FROM events WHERE session_id=$1 "
        "ORDER BY sequence_num ASC", sid)
    sad = r["self_assessment_data"]
    sad = json.loads(sad) if isinstance(sad, str) else (sad or {})
    await conn.close()
    return {
        "session_id": str(sid), "user_name": r["name"] or "리더",
        "self_assessment_data": sad,
        "messages": [dict(m) for m in msgs],
        "events": [dict(e) for e in evs],
    }


def _build_inputs(fx: dict):
    """fixture → generate_diagnosis_result 입력(reports.py 와 동일 로직)."""
    from diag_project.routes.reports import (
        _build_asked_subcompetencies, _build_chapter_transcripts,
    )

    class _M:
        def __init__(self, d):
            self.role = d["role"]; self.content = d["content"]
            self.chapter = d.get("chapter")

    class _E:
        def __init__(self, d):
            self._d = d

        def __getattr__(self, k):
            return (self.__dict__.get("_d") or {}).get(k)

    msgs = [_M(m) for m in fx["messages"]]
    evs = [_E(e) for e in fx["events"]]
    formatted_history = [{"role": m.role, "parts": m.content} for m in msgs]
    chapter_transcripts = _build_chapter_transcripts(msgs, evs)
    asked_subs = _build_asked_subcompetencies(fx["self_assessment_data"] or {})
    return formatted_history, chapter_transcripts, asked_subs


async def _analyze(fx: dict) -> dict:
    from diag_project.llm_service import GeminiService
    svc = GeminiService()
    hist, ctx, asked = _build_inputs(fx)
    res = await svc.generate_diagnosis_result(
        history=hist, user_name=fx["user_name"],
        chapter_transcripts=ctx, asked_subcompetencies=asked)
    return res


def _digest(res: dict) -> dict:
    """비교용 요약: measured 집합·레벨·gate 4분포·추천 카드."""
    details = res.get("details", {})
    measured = {}
    gate = {"passed": 0, "failed": 0, "pending": 0, "n_a": 0}
    for ch, cv in details.items():
        for sub, row in (cv.get("sub_ledger") or {}).items():
            g = row.get("gate_status")
            gate[g] = gate.get(g, 0) + 1
            if row.get("measured"):
                measured[f"{ch}/{sub}"] = row.get("level")
    cr = res.get("course_recommendation") or {}
    cards = [c.get("sub_competency") for c in (cr.get("growth") or [])]
    if cr.get("strength"):
        cards.append("D:" + cr["strength"].get("sub_competency", ""))
    return {
        "measured": measured, "gate": gate,
        "cards": sorted(cards),
        "coverage": {k: res.get("coverage", {}).get(k) for k in
                     ("measured", "asked", "score_suppressed",
                      "qualifying_competencies")},
        "usage": res.get("usage_metering"),
    }


async def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "export":
        fx = await _load_session(sys.argv[2])
        with open(sys.argv[3], "w", encoding="utf-8") as f:
            json.dump(fx, f, ensure_ascii=False, default=str)
        print(f"export OK → {sys.argv[3]} (msgs={len(fx['messages'])}, "
              f"events={len(fx['events'])})")
    elif cmd == "analyze":
        fx = json.load(open(sys.argv[2], encoding="utf-8"))
        res = await _analyze(fx)
        d = _digest(res)
        print(json.dumps(d, ensure_ascii=False, indent=2))
    elif cmd == "compare":
        fx = json.load(open(sys.argv[2], encoding="utf-8"))
        d1 = _digest(await _analyze(fx))
        d2 = _digest(await _analyze(fx))
        same_m = set(d1["measured"]) == set(d2["measured"])
        same_g = d1["gate"] == d2["gate"]
        print("run1 measured:", sorted(d1["measured"]))
        print("run2 measured:", sorted(d2["measured"]))
        print(f"measured 집합 동일: {same_m} · gate 4분포 동일: {same_g}")
        print("usage run1:", d1["usage"])
    else:
        print(__doc__)


if __name__ == "__main__":
    asyncio.run(main())
