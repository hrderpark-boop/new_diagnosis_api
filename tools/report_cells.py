"""(2026-11-12 P11-J1) 리포트 칸별 근거 덤프(읽기 전용, LLM 호출 없음) — 저장된 리포트만 읽는다.

26칸(하위역량)마다 점수와 근거 인용문을 표로 내고, 같은 문장이 몇 칸의 근거로 쓰였는지, 리더가 두 번 붙여넣은 답이 근거에 들어갔는지,
'26개 지표 중 N개 확인'의 N(1.0 = 사례 미확인 칸을 뺀 수)을 센다.

용법:
  python tools/report_cells.py <email_like> [--chapter people_management]     # .env 의 DATABASE_URL 로 읽는다(읽기 전용 SELECT 2건)
  python tools/report_cells.py --json scores.json [--messages messages.json]   # 내보낸 scores(JSON)·리더 발화 목록으로
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _norm(t: str | None) -> str:
    return re.sub(r"[\s\"'“”‘’.,!?…·*()\[\]-]", "", t or "")


def cell_rows(details: dict) -> list[dict]:
    """scores.details → [{chapter, cell, score, quotes[]}] (프레임워크 순서)."""
    from diag_project.data.competencies import COMPETENCY_FRAMEWORK as CF
    rows: list[dict] = []
    for ch_key, ch in CF.items():
        if ch_key == "supplementary":
            continue
        ch_d = (details or {}).get(ch_key) or {}
        subs = ch_d.get("sub_scores") or {}
        ledger = ch_d.get("sub_ledger") or {}            # 칸별 판정 기록 — {score, level, status, evidence[]}
        assess = ch_d.get("sub_assessments") or {}
        for ind in (ch.get("indicators") or {}).values():
            name = ind.get("name")
            d = ledger.get(name) or assess.get(name) or {}
            score = d.get("score") if d.get("score") is not None else subs.get(name)
            quotes = [str(e) for e in (d.get("evidence") or []) if e]
            rows.append({"chapter": ch.get("name"), "chapter_key": ch_key, "cell": name, "score": score, "quotes": quotes,
                         "status": d.get("status"), "level": d.get("level")})
    return rows


def shared_quotes(rows: list[dict]) -> dict[str, list[str]]:
    """같은 문장(공백·문장부호 무시, 앞 30자 기준 포함 관계)이 근거로 쓰인 칸들 — 2칸 이상만."""
    by: dict[str, set[str]] = defaultdict(set)
    text: dict[str, str] = {}
    for r in rows:
        for q in r["quotes"]:
            k = _norm(q)[:30]
            if len(k) >= 8:
                by[k].add(r["cell"]); text.setdefault(k, q)
    return {text[k]: sorted(v) for k, v in by.items() if len(v) >= 2}


def pasted_answers(user_texts: list[str]) -> list[str]:
    """리더가 세션에서 두 번 이상 보낸 같은 답(20자 이상)."""
    seen: dict[str, int] = defaultdict(int)
    first: dict[str, str] = {}
    for t in user_texts or []:
        k = _norm(t)
        if len(k) >= 20:
            seen[k] += 1; first.setdefault(k, t)
    return [first[k] for k, n in seen.items() if n >= 2]


def render(rows: list[dict], user_texts: list[str] | None = None, chapter: str | None = None) -> str:
    L: list[str] = []
    sel = [r for r in rows if not chapter or r["chapter_key"] == chapter]
    L.append("| 영역 | 칸 | 점수 | 근거 수 | 근거 인용문 |")
    L.append("|---|---|---|---|---|")
    for r in sel:
        qs = " / ".join(f"“{q[:70]}”" for q in r["quotes"]) or "(없음)"
        L.append(f"| {r['chapter']} | {r['cell']} | {r['score']} | {len(r['quotes'])} | {qs} |")
    sh = shared_quotes(sel)
    L.append("")
    L.append(f"같은 문장이 2칸 이상의 근거로 쓰인 경우: {len(sh)}건")
    for q, cells in sorted(sh.items(), key=lambda kv: -len(kv[1])):
        L.append(f"- {len(cells)}칸 ({', '.join(cells)}): “{q[:90]}”")
    if user_texts is not None:
        pasted = pasted_answers(user_texts)
        hit = [(p, [r["cell"] for r in sel if any(_norm(q)[:20] and _norm(q)[:20] in _norm(p) for q in r["quotes"])]) for p in pasted]
        L.append("")
        L.append(f"두 번 이상 보낸 같은 답: {len(pasted)}건")
        for p, cells in hit:
            L.append(f"- 근거로 쓰인 칸 {len(cells)} ({', '.join(cells) or '없음'}): “{p[:90]}”")
    ones = [r["cell"] for r in rows if r["score"] is not None and float(r["score"]) <= 1.0]
    none = [r["cell"] for r in rows if r["score"] is None]
    L.append("")
    L.append(f"26칸 중 점수 있는 칸 {len(rows) - len(none)} · 1.0(사례 미확인) {len(ones)}칸 → 확인 {len(rows) - len(none) - len(ones)}칸")
    if ones:
        L.append("- 1.0 칸: " + ", ".join(ones))
    if none:
        L.append("- 점수 없는 칸: " + ", ".join(none))
    return "\n".join(L)


async def _from_db(email_like: str) -> tuple[dict, list[str]]:
    import asyncpg
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
    url = (os.getenv("DATABASE_URL") or "").replace("postgresql+asyncpg://", "postgresql://")
    if not url:
        raise SystemExit("DATABASE_URL 이 없습니다 — --json 으로 내보낸 scores 를 주세요.")
    conn = await asyncpg.connect(url)
    try:
        s = await conn.fetchrow("SELECT s.id FROM diagnosis_sessions s JOIN participants p ON s.user_id=p.id WHERE p.email LIKE $1 "
                                "ORDER BY s.created_at DESC LIMIT 1", email_like)
        if not s:
            raise SystemExit("세션 없음")
        r = await conn.fetchrow("SELECT scores FROM diagnosis_reports WHERE session_id=$1 ORDER BY created_at DESC LIMIT 1", s["id"])
        if not r:
            raise SystemExit("리포트 없음")
        sc = r["scores"]; sc = json.loads(sc) if isinstance(sc, str) else (sc or {})
        users = await conn.fetch("SELECT content FROM chat_messages WHERE session_id=$1 AND role='user' ORDER BY created_at", s["id"])
        return sc, [x["content"] or "" for x in users]
    finally:
        await conn.close()


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="리포트 칸별 근거 덤프(읽기 전용)")
    ap.add_argument("email_like", nargs="?")
    ap.add_argument("--json", dest="json_path")
    ap.add_argument("--messages")
    ap.add_argument("--chapter")
    a = ap.parse_args(argv)
    if a.json_path:
        sc = json.load(open(a.json_path, encoding="utf-8"))
        users = json.load(open(a.messages, encoding="utf-8")) if a.messages else None
    elif a.email_like:
        sc, users = asyncio.run(_from_db(a.email_like))
    else:
        ap.error("email_like 또는 --json 이 필요합니다.")
    details = sc.get("details") if isinstance(sc, dict) and "details" in sc else sc
    print(render(cell_rows(details or {}), users, a.chapter))
    return 0


if __name__ == "__main__":
    sys.exit(main())
