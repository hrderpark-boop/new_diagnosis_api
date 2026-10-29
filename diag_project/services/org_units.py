"""조직 단위(본부·실·팀) DB 도우미: 로그인 코드 해석, 조직 트리·참여 집계, 조직별 진행·평균 통계.

순수 코드 규칙은 services/org_codes.py, HTTP 는 routes/org_units.py.
"""
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from diag_project.models.company import Company
from diag_project.models.diagnosis_report import DiagnosisReport
from diag_project.models.org_unit import OrgUnit
from diag_project.models.participant import Participant


async def resolve_login_code(db: AsyncSession, code: str) -> Tuple[Optional[Company], Optional[OrgUnit]]:
    """로그인 그룹 코드 → (회사, 조직 단위).

    1) 회사 코드(companies.code)와 같으면 회사만(소속 미분류).
    2) 아니면 조직 참여 코드(org_units.code)로 찾아 그 회사와 단위.
    코드가 비었거나 못 찾으면 (None, None).
    """
    if not code:
        return None, None
    company = (await db.execute(select(Company).where(Company.code == code))).scalars().first()
    if company is not None:
        return company, None
    unit = (await db.execute(select(OrgUnit).where(OrgUnit.code == code))).scalars().first()
    if unit is None:
        return None, None
    company = await db.get(Company, unit.company_id)
    return company, unit


async def code_in_use(db: AsyncSession, code: str, exclude_unit_id: Optional[UUID] = None) -> bool:
    """회사 코드나 다른 조직 코드와 겹치는지."""
    if (await db.execute(select(Company.id).where(Company.code == code))).first():
        return True
    q = select(OrgUnit.id).where(OrgUnit.code == code)
    if exclude_unit_id:
        q = q.where(OrgUnit.id != exclude_unit_id)
    return (await db.execute(q)).first() is not None


async def descendant_ids(db: AsyncSession, unit_id: UUID) -> List[UUID]:
    """단위 자신 + 모든 하위 단위 id (본부 → 실 → 팀). 단계가 3단이라 최대 두 번 내려간다."""
    out = [unit_id]
    frontier = [unit_id]
    for _ in range(3):
        if not frontier:
            break
        children = (await db.execute(select(OrgUnit.id).where(OrgUnit.parent_id.in_(frontier)))).scalars().all()
        out.extend(children)
        frontier = list(children)
    return out


async def build_org_tree(db: AsyncSession, company_id: UUID) -> Dict[str, Any]:
    """회사의 본부 → 팀 트리 + 단위별 등록 인원·완료 인원.

    완료 = 리포트가 있는 참여자(리포트는 완주 시에만 생긴다). 본부 숫자는 소속 팀 + 본부에 바로 속한 인원의 합.
    """
    units = (await db.execute(
        select(OrgUnit).where(OrgUnit.company_id == company_id)
        .order_by(OrgUnit.sort_order, OrgUnit.code)
    )).scalars().all()

    reg = dict((await db.execute(
        select(Participant.org_unit_id, func.count(Participant.id))
        .where(Participant.company_id == company_id)
        .group_by(Participant.org_unit_id)
    )).all())
    done_rows = (await db.execute(
        select(Participant.org_unit_id, func.count(func.distinct(Participant.id)))
        .join(DiagnosisReport, DiagnosisReport.user_id == Participant.id)
        .where(Participant.company_id == company_id)
        .group_by(Participant.org_unit_id)
    )).all()
    done = dict(done_rows)

    def node(u: OrgUnit) -> Dict[str, Any]:
        return {
            "id": str(u.id), "parent_id": str(u.parent_id) if u.parent_id else None,
            "level": u.level, "name": u.name, "short_code": u.short_code, "code": u.code,
            "sort_order": u.sort_order, "is_active": u.is_active,
            "registered": int(reg.get(u.id, 0)), "completed": int(done.get(u.id, 0)),
        }

    children: Dict[UUID, List[OrgUnit]] = defaultdict(list)
    for u in units:
        if u.parent_id:
            children[u.parent_id].append(u)

    def with_totals(n: Dict[str, Any], subs: List[Dict[str, Any]]) -> Dict[str, Any]:
        n["registered_total"] = n["registered"] + sum(x.get("registered_total", x["registered"]) for x in subs)
        n["completed_total"] = n["completed"] + sum(x.get("completed_total", x["completed"]) for x in subs)
        return n

    divisions = []
    for u in units:
        if u.level != "division":
            continue
        d = node(u)
        offices, teams = [], []
        for c in children.get(u.id, []):
            if c.level == "office":
                o = node(c)
                o["teams"] = [node(t) for t in children.get(c.id, []) if t.level == "team"]
                offices.append(with_totals(o, o["teams"]))
            elif c.level == "team":
                teams.append(node(c))
        d["offices"] = offices
        d["teams"] = teams          # 본부 직속 팀(실 없이)
        divisions.append(with_totals(d, offices + teams))

    return {
        "divisions": divisions,
        "unassigned": {"registered": int(reg.get(None, 0)), "completed": int(done.get(None, 0))},
    }


async def unit_labels(db: AsyncSession, unit_ids: List[UUID]) -> Dict[UUID, Dict[str, Optional[str]]]:
    """참여자 목록 표시용: 단위 id → {code, name, division_*, office_*, team_name}."""
    ids = [u for u in set(unit_ids) if u]
    if not ids:
        return {}
    known: Dict[UUID, OrgUnit] = {}
    frontier = ids
    for _ in range(3):     # 자신 → 부모 → 조부모
        if not frontier:
            break
        got = (await db.execute(select(OrgUnit).where(OrgUnit.id.in_(frontier)))).scalars().all()
        for g in got:
            known[g.id] = g
        frontier = [g.parent_id for g in got if g.parent_id and g.parent_id not in known]
    out = {}
    for uid in ids:
        u = known.get(uid)
        if u is None:
            continue
        chain = []
        cur: Optional[OrgUnit] = u
        while cur is not None:
            chain.append(cur)
            cur = known.get(cur.parent_id) if cur.parent_id else None
        by_level = {c.level: c for c in chain}
        div, off, team = by_level.get("division"), by_level.get("office"), by_level.get("team")
        out[uid] = {
            "code": u.code, "name": u.name, "level": u.level,
            "division_id": str(div.id) if div else None, "division_name": div.name if div else None,
            "office_id": str(off.id) if off else None, "office_name": off.name if off else None,
            "team_name": team.name if team else None,
        }
    return out


async def _latest_details_for_units(db: AsyncSession, unit_ids: List[UUID]) -> List[dict]:
    """해당 단위들에 속한 참여자의 최신 리포트 details 목록(참여자당 1건)."""
    rows = (await db.execute(
        select(DiagnosisReport, DiagnosisReport.user_id)
        .join(Participant, Participant.id == DiagnosisReport.user_id)
        .where(Participant.org_unit_id.in_(unit_ids))
        .order_by(DiagnosisReport.created_at.desc())
    )).all()
    seen, out = set(), []
    for rep, uid in rows:
        if uid in seen:
            continue
        seen.add(uid)
        out.append(((rep.scores or {}).get("details")) or {})
    return out


async def org_comparison_levels(db: AsyncSession, org_unit_id: Optional[UUID], order: List[str],
                                all_group: Dict[str, Any]) -> Dict[str, Any]:
    """리포트의 조직 비교(전체·본부·팀). 프론트 OrgCompare 가 그대로 쓰는 모양.

    전체 = 기존 같은 그룹(회사) 평균. 본부·팀은 참여자 소속이 있을 때만 계산하고, 표본이 모자라면
    available=False 와 안내 문구(가짜 숫자 없음). 최소 인원 규칙은 group_average 와 같다.
    """
    from diag_project.services.self_view import group_average

    def level(key: str, label: str, g: Dict[str, Any], note: Optional[str] = None) -> Dict[str, Any]:
        return {"key": key, "label": label, "n": g.get("n", 0), "available": bool(g.get("available")),
                "averages": g.get("averages") if g.get("available") else None,
                "note": note or g.get("label")}

    levels = [level("all", "전체", all_group)]
    unit = await db.get(OrgUnit, org_unit_id) if org_unit_id else None
    if unit is None:
        levels.append({"key": "division", "label": "본부", "n": 0, "available": False, "averages": None,
                       "note": "참여 코드로 소속이 정해지면 본부 평균과 비교해 드립니다"})
        levels.append({"key": "team", "label": "팀", "n": 0, "available": False, "averages": None,
                       "note": "참여 코드로 소속이 정해지면 팀 평균과 비교해 드립니다"})
        return {"levels": levels}

    division = unit
    while division is not None and division.level != "division":
        division = await db.get(OrgUnit, division.parent_id) if division.parent_id else None
    if division is not None:
        div_ids = await descendant_ids(db, division.id)
        levels.append(level("division", f"본부({division.name})",
                            group_average(await _latest_details_for_units(db, div_ids), order)))
    if unit.level == "team":
        levels.append(level("team", f"팀({unit.name})",
                            group_average(await _latest_details_for_units(db, [unit.id]), order)))
    else:
        levels.append({"key": "team", "label": "팀", "n": 0, "available": False, "averages": None,
                       "note": "본부 단위 코드로 참여해 팀 비교는 없습니다"})
    return {"levels": levels}


# ---------------------------------------------------------------------------
# 참여자 진행 상태 · 조직별 진행/평균 통계 (HR 진단 현황 · 종합 리포트 조직 비교)
# ---------------------------------------------------------------------------
# 상태 4가지: completed(리포트 있음) · in_progress(진행 중 세션) · abandoned(중단·보관만) · not_started(세션 없음)
STATUSES = ("completed", "in_progress", "abandoned", "not_started")


async def participant_statuses(db: AsyncSession, participant_ids: List[UUID]) -> Dict[UUID, str]:
    from diag_project.models.diagnosis_session import DiagnosisSession
    if not participant_ids:
        return {}
    has_report = set((await db.execute(
        select(DiagnosisReport.user_id).where(DiagnosisReport.user_id.in_(participant_ids))
    )).scalars().all())
    sess: Dict[UUID, List[str]] = defaultdict(list)
    for uid, st in (await db.execute(
        select(DiagnosisSession.user_id, DiagnosisSession.status).where(DiagnosisSession.user_id.in_(participant_ids))
    )).all():
        sess[uid].append(st or "")
    out = {}
    for pid in participant_ids:
        if pid in has_report:
            out[pid] = "completed"
        elif not sess.get(pid):
            out[pid] = "not_started"
        elif all(s == "abandoned" for s in sess[pid]):
            out[pid] = "abandoned"
        else:
            out[pid] = "in_progress"
    return out


async def org_stats(db: AsyncSession, company_id: UUID, level: str, order: List[str]) -> Dict[str, Any]:
    """조직 단위(level = division | office | team)별 진행 현황 + 역량 평균.

    각 단위 숫자는 하위 단위 소속까지 포함한다(본부 = 소속 실·팀 전체). 평균은 참여자별 최신 리포트의 측정 점수.
    회사 전체 행(total)과 미분류(unassigned) 행을 함께 돌려준다. 가짜 값 없음: 측정이 없으면 None.
    """
    from diag_project.routes.admin_education import measured_scores   # 측정 점수 규칙 공유(순환 import 회피용 지연)

    participants = (await db.execute(select(Participant).where(Participant.company_id == company_id))).scalars().all()
    pids = [p.id for p in participants]
    statuses = await participant_statuses(db, pids)
    latest: Dict[UUID, DiagnosisReport] = {}
    if pids:
        for r in (await db.execute(
            select(DiagnosisReport).where(DiagnosisReport.user_id.in_(pids)).order_by(DiagnosisReport.created_at.desc())
        )).scalars().all():
            latest.setdefault(r.user_id, r)

    units = (await db.execute(select(OrgUnit).where(OrgUnit.company_id == company_id))).scalars().all()
    by_id = {u.id: u for u in units}

    def ancestors(uid: Optional[UUID]) -> List[UUID]:
        out, cur = [], by_id.get(uid) if uid else None
        while cur is not None:
            out.append(cur.id)
            cur = by_id.get(cur.parent_id) if cur.parent_id else None
        return out

    def empty() -> Dict[str, Any]:
        return {"registered": 0, **{s: 0 for s in STATUSES}, "_scores": defaultdict(list), "_totals": []}

    buckets: Dict[Any, Dict[str, Any]] = defaultdict(empty)
    for p in participants:
        keys = ["__total__"] + (ancestors(p.org_unit_id) or ["__unassigned__"])
        rep = latest.get(p.id)
        ms = measured_scores(rep.scores or {}) if rep else {}
        for k in keys:
            b = buckets[k]
            b["registered"] += 1
            b[statuses.get(p.id, "not_started")] += 1
            for ck, v in ms.items():
                b["_scores"][ck].append(v)
            if rep is not None and rep.total_score is not None:
                b["_totals"].append(float(rep.total_score))

    def row(key: Any, meta: Dict[str, Any]) -> Dict[str, Any]:
        b = buckets.get(key) or empty()
        reg = b["registered"]
        return {
            **meta,
            "registered": reg, **{s: b[s] for s in STATUSES},
            "completion_rate": round(b["completed"] / reg * 100) if reg else 0,
            "n_reports": len(b["_totals"]),
            "total_average": round(sum(b["_totals"]) / len(b["_totals"]), 1) if b["_totals"] else None,
            "averages": {ck: (round(sum(b["_scores"][ck]) / len(b["_scores"][ck]), 1) if b["_scores"].get(ck) else None)
                         for ck in order},
        }

    def path_name(u: OrgUnit) -> str:
        names, cur = [], u
        while cur is not None:
            names.append(cur.name)
            cur = by_id.get(cur.parent_id) if cur.parent_id else None
        return " · ".join(reversed(names))

    rows = [row(u.id, {"id": str(u.id), "code": u.code, "name": u.name, "path": path_name(u),
                       "level": u.level, "is_active": u.is_active})
            for u in sorted(units, key=lambda x: x.code) if u.level == level]
    return {
        "level": level,
        "total": row("__total__", {"id": None, "code": None, "name": "전체", "path": "전체", "level": "company"}),
        "unassigned": row("__unassigned__", {"id": None, "code": None, "name": "미분류", "path": "미분류(조직 코드 없이 참여)", "level": "none"}),
        "rows": rows,
    }
