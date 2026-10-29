"""조직 단위(본부·팀) DB 도우미: 로그인 코드 해석, 조직 트리·참여 집계.

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
    """단위 자신 + 하위 단위 id (본부 → 소속 팀까지). 단계는 본부·팀 2단이라 한 번만 내려간다."""
    children = (await db.execute(select(OrgUnit.id).where(OrgUnit.parent_id == unit_id))).scalars().all()
    return [unit_id, *children]


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

    teams_by_parent: Dict[UUID, List[Dict[str, Any]]] = defaultdict(list)
    for u in units:
        if u.level == "team" and u.parent_id:
            teams_by_parent[u.parent_id].append(node(u))
    divisions = []
    for u in units:
        if u.level != "division":
            continue
        d = node(u)
        d["teams"] = teams_by_parent.get(u.id, [])
        d["registered_total"] = d["registered"] + sum(t["registered"] for t in d["teams"])
        d["completed_total"] = d["completed"] + sum(t["completed"] for t in d["teams"])
        divisions.append(d)

    return {
        "divisions": divisions,
        "unassigned": {"registered": int(reg.get(None, 0)), "completed": int(done.get(None, 0))},
    }


async def unit_labels(db: AsyncSession, unit_ids: List[UUID]) -> Dict[UUID, Dict[str, Optional[str]]]:
    """참여자 목록 표시용: 단위 id → {code, name, division_name}."""
    ids = [u for u in set(unit_ids) if u]
    if not ids:
        return {}
    units = (await db.execute(select(OrgUnit).where(OrgUnit.id.in_(ids)))).scalars().all()
    parent_ids = [u.parent_id for u in units if u.parent_id]
    parents = {}
    if parent_ids:
        parents = {p.id: p for p in (await db.execute(select(OrgUnit).where(OrgUnit.id.in_(parent_ids)))).scalars().all()}
    out = {}
    for u in units:
        div = parents.get(u.parent_id) if u.parent_id else u
        out[u.id] = {
            "code": u.code, "name": u.name,
            "division_name": div.name if div else None,
            "division_id": str(div.id) if div else None,
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

    division = unit if unit.level == "division" else (await db.get(OrgUnit, unit.parent_id) if unit.parent_id else None)
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
