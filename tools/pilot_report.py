"""파일럿 수집 도구 — 완료된 실제 세션 1건 → P-3 지표 + P-2 사람검토 패킷.

API 0콜: /analyze 로 이미 저장된 리포트(DiagnosisReport.scores)와 세션 메시지를
DB 에서 읽어 집계만 한다. 참가자 세션이 끝난 뒤 실행한다.

용법: python tools/pilot_report.py <email_like> [out.json]
"""
import asyncio
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), ".env"))

_COMP_KO = {"organization_management": "조직관리",
            "performance_management": "성과관리",
            "people_management": "사람관리", "work_management": "일관리",
            "self_management": "자기관리"}


async def _load(email_like: str) -> dict:
    import asyncpg
    u = (os.getenv("DATABASE_URL") or os.getenv("DATABASE_URI")).replace(
        "postgresql+asyncpg://", "postgresql://")
    conn = await asyncpg.connect(u)
    s = await conn.fetchrow(
        "SELECT s.id, s.status, s.current_topic, s.self_assessment_data, p.name "
        "FROM diagnosis_sessions s JOIN participants p ON s.user_id=p.id "
        "WHERE p.email LIKE $1 ORDER BY s.created_at DESC LIMIT 1", email_like)
    if not s:
        await conn.close()
        raise SystemExit(f"세션 없음: {email_like}")
    sid = s["id"]
    msgs = await conn.fetch(
        "SELECT role, content, created_at FROM chat_messages "
        "WHERE session_id=$1 ORDER BY created_at ASC", sid)
    rep = await conn.fetchrow(
        "SELECT scores, total_score, created_at FROM diagnosis_reports "
        "WHERE session_id=$1 ORDER BY created_at DESC LIMIT 1", sid)
    await conn.close()
    sad = s["self_assessment_data"]
    sad = json.loads(sad) if isinstance(sad, str) else (sad or {})
    scores = None
    if rep:
        scores = rep["scores"]
        scores = json.loads(scores) if isinstance(scores, str) else scores
    return {"name": s["name"], "status": s["status"],
            "current_topic": s["current_topic"], "sad": sad,
            "messages": [dict(m) for m in msgs],
            "scores": scores, "has_report": rep is not None}


def _packet(d: dict) -> dict:
    msgs = d["messages"]
    user_turns = [m for m in msgs if m["role"] == "user"]
    # 소요 시간(첫→마지막 메시지)
    dur_min = None
    ts = [m.get("created_at") for m in msgs if m.get("created_at")]
    if len(ts) >= 2 and isinstance(ts[0], datetime):
        dur_min = round((ts[-1] - ts[0]).total_seconds() / 60, 1)

    scores = d.get("scores") or {}
    cov = scores.get("coverage") or {}
    details = scores.get("details") or {}

    # P-3: 대역량별 measured/asked/total 분포 + '탐색됐으나 0 측정' 경고.
    #   자기관리(하위 3개)는 하한이 3이라 전부 탐색되는데도 0 이면 앵커/판정
    #   문제 후보. 실제로 사례를 준 리더에서 이 경고가 반복되면 도구 문제.
    per_comp = {}
    zero_warn = []
    for ck, cv in details.items():
        led = cv.get("sub_ledger") or {}
        total = len(led)
        asked = sum(1 for v in led.values() if v.get("asked"))
        meas = sum(1 for v in led.values() if v.get("measured"))
        per_comp[_COMP_KO.get(ck, ck)] = f"측정 {meas}/탐색 {asked}/{total}"
        if asked >= 2 and meas == 0:
            zero_warn.append(
                f"⚠️ {_COMP_KO.get(ck, ck)}: 탐색 {asked}인데 측정 0 — "
                "부재진술이면 정당, 사례를 줬는데도 0이면 앵커/판정 점검")

    # P-2: 카드 + 인용문(사람 검토용)
    cr = scores.get("course_recommendation") or {}
    cards = []
    for c in (cr.get("growth") or []) + (
            [cr["strength"]] if cr.get("strength") else []):
        cards.append({
            "하위역량": c.get("sub_competency"), "레벨": c.get("level"),
            "배지_근거제한적": bool(c.get("evidence_limited")),
            "인용문": c.get("bei_citation"),
            "과정": c.get("course"),
        })

    return {
        "참가자": d["name"], "세션상태": d["status"],
        "리포트존재": d["has_report"],
        "── ⚠️ 경고 (P-4/자기관리 감시) ──": zero_warn or "없음",
        "── P-3 참여 ──": {
            "사용자_턴수": len(user_turns), "전체_턴수": len(msgs),
            "소요_분": dur_min, "current_topic": d["current_topic"],
            "중단여부(aborted_disengaged)":
                d["status"] == "aborted_disengaged",
        },
        "── P-3 커버리지 ──": {
            "measured_total": cov.get("measured_total", cov.get("measured")),
            "asked/26": cov.get("asked"), "measured/26": cov.get("measured"),
            "임계": cov.get("composite_min_measured"),
            "composite_shown": cov.get("composite_shown"),
            "포맷": ("종합 섹션 포함" if cov.get("composite_shown")
                   else "단일(종합 없음)"),
            "대역량별_분포": per_comp,
            "borderline_배지수": cov.get("borderline_count"),
        },
        "── P-3 비용 ──": scores.get("usage_metering"),
        "── P-2 사람검토 패킷 ──": {
            "카드": cards,
            "검토항목": ["인용문이 실제 발화인가(verbatim)",
                     "레벨이 인상과 어긋나지 않는가",
                     "카드 4장이 납득 가능한가",
                     "배지 카드가 어색하지 않은가"],
        },
    }


async def main():
    if len(sys.argv) < 2:
        print(__doc__)
        return
    d = await _load(sys.argv[1])
    pkt = _packet(d)
    out = json.dumps(pkt, ensure_ascii=False, indent=2, default=str)
    print(out)
    if len(sys.argv) > 2:
        with open(sys.argv[2], "w", encoding="utf-8") as f:
            f.write(out)
        print(f"\n저장 → {sys.argv[2]}")


if __name__ == "__main__":
    asyncio.run(main())
