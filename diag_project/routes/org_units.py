# diag_project/routes/org_units.py
#
# 조직 참여 코드(AS1 형식) 관리 API.
#   - 마스터(super_admin): 고객사 접두어 지정, 본부·팀 등록·수정·삭제, 일괄 등록
#   - 고객사 HR(client_admin): 자사 조직 트리 조회만
# 코드 규칙은 services/org_codes.py, 트리·집계는 services/org_units.py.

from typing import List, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from diag_project.database import get_db
from diag_project.models.company import Company
from diag_project.models.org_unit import OrgUnit
from diag_project.models.participant import Participant
from diag_project.services import org_codes
from diag_project.services.auth import AdminContext, get_current_admin, require_super_admin
from diag_project.services.org_units import build_org_tree, code_in_use

router = APIRouter(prefix="/admin", tags=["Admin · 조직 코드"])


# ---------------------------------------------------------------------------
# 스키마
# ---------------------------------------------------------------------------
class CompanyUpdateRequest(BaseModel):
    name: Optional[str] = None
    contact_email: Optional[str] = None
    is_active: Optional[bool] = None
    org_prefix: Optional[str] = Field(None, description="조직 코드 접두어(영문 1~3자)")


class OrgUnitCreateRequest(BaseModel):
    level: str = Field(..., description="division | team")
    name: str
    # 본부: 영문 1~2자 코드(필수). 팀: 무시.
    short_code: Optional[str] = None
    # 팀: 소속 본부 id(필수)와 번호(비우면 다음 번호)
    parent_id: Optional[UUID] = None
    number: Optional[int] = None


class OrgUnitUpdateRequest(BaseModel):
    name: Optional[str] = None
    is_active: Optional[bool] = None
    sort_order: Optional[int] = None


class OrgBulkRow(BaseModel):
    division: str
    division_code: str
    team: Optional[str] = None


class OrgBulkRequest(BaseModel):
    rows: List[OrgBulkRow]


# ---------------------------------------------------------------------------
# 내부 도우미
# ---------------------------------------------------------------------------
async def _get_company(db: AsyncSession, company_id: UUID) -> Company:
    company = await db.get(Company, company_id)
    if company is None:
        raise HTTPException(status_code=404, detail="고객사를 찾을 수 없습니다.")
    return company


def _require_prefix(company: Company) -> str:
    if not company.org_prefix:
        raise HTTPException(status_code=400, detail="먼저 고객사 접두어를 정해 주세요.")
    return company.org_prefix


async def _create_division(db: AsyncSession, company: Company, name: str, short: str) -> OrgUnit:
    err = org_codes.validate_division_code(short)
    if err:
        raise HTTPException(status_code=400, detail=err)
    code = org_codes.division_code(_require_prefix(company), short)
    if await code_in_use(db, code):
        raise HTTPException(status_code=409, detail=f"이미 쓰는 코드입니다({code}).")
    unit = OrgUnit(company_id=company.id, level="division", name=name.strip(),
                   short_code=org_codes.normalize(short), code=code)
    db.add(unit)
    await db.flush()
    return unit


async def _create_team(db: AsyncSession, company: Company, parent: OrgUnit, name: str,
                       number: Optional[int]) -> OrgUnit:
    if parent.company_id != company.id or parent.level != "division":
        raise HTTPException(status_code=400, detail="팀은 같은 고객사의 본부 아래에만 만들 수 있습니다.")
    if number is None:
        existing = (await db.execute(
            select(OrgUnit.short_code).where(OrgUnit.parent_id == parent.id)
        )).scalars().all()
        number = org_codes.next_team_number(existing)
    err = org_codes.validate_team_number(number)
    if err:
        raise HTTPException(status_code=400, detail=err)
    code = org_codes.team_code(parent.code, number)
    if await code_in_use(db, code):
        raise HTTPException(status_code=409, detail=f"이미 쓰는 코드입니다({code}).")
    unit = OrgUnit(company_id=company.id, parent_id=parent.id, level="team", name=name.strip(),
                   short_code=str(int(number)), code=code, sort_order=int(number))
    db.add(unit)
    await db.flush()
    return unit


# ---------------------------------------------------------------------------
# 고객사 수정(접두어 포함) — 마스터 전용
# ---------------------------------------------------------------------------
@router.patch("/companies/{company_id}")
async def update_company(
    company_id: UUID,
    body: CompanyUpdateRequest,
    ctx: AdminContext = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    company = await _get_company(db, company_id)
    if body.name is not None:
        if not body.name.strip():
            raise HTTPException(status_code=400, detail="고객사 이름은 비울 수 없습니다.")
        company.name = body.name.strip()
    if body.contact_email is not None:
        company.contact_email = body.contact_email.strip() or None
    if body.is_active is not None:
        company.is_active = body.is_active
    if body.org_prefix is not None:
        new_prefix = org_codes.normalize(body.org_prefix)
        if new_prefix != (company.org_prefix or ""):
            has_units = (await db.execute(
                select(OrgUnit.id).where(OrgUnit.company_id == company.id)
            )).first()
            if has_units:
                raise HTTPException(status_code=409,
                                    detail="조직 코드가 이미 있어 접두어를 바꿀 수 없습니다(배포한 코드가 깨집니다).")
            others = (await db.execute(
                select(Company.org_prefix).where(Company.id != company.id, Company.org_prefix.is_not(None))
            )).scalars().all()
            err = org_codes.validate_prefix(new_prefix, others)
            if err:
                raise HTTPException(status_code=400, detail=err)
            company.org_prefix = new_prefix
    db.add(company)
    await db.commit()
    await db.refresh(company)
    return {"id": str(company.id), "name": company.name, "code": company.code,
            "contact_email": company.contact_email, "is_active": company.is_active,
            "org_prefix": company.org_prefix}


# ---------------------------------------------------------------------------
# 조직 트리 조회 — 마스터는 모든 고객사, HR 은 자사만
# ---------------------------------------------------------------------------
@router.get("/companies/{company_id}/org-units")
async def get_org_units(
    company_id: UUID,
    ctx: AdminContext = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    ctx.assert_can_access_company(company_id)
    company = await _get_company(db, company_id)
    tree = await build_org_tree(db, company.id)
    return {
        "company": {"id": str(company.id), "name": company.name, "code": company.code,
                    "org_prefix": company.org_prefix},
        **tree,
    }


# ---------------------------------------------------------------------------
# 본부·팀 등록 — 마스터 전용
# ---------------------------------------------------------------------------
@router.post("/companies/{company_id}/org-units", status_code=status.HTTP_201_CREATED)
async def create_org_unit(
    company_id: UUID,
    body: OrgUnitCreateRequest,
    ctx: AdminContext = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    company = await _get_company(db, company_id)
    if not body.name or not body.name.strip():
        raise HTTPException(status_code=400, detail="이름을 입력해 주세요.")
    if body.level == "division":
        unit = await _create_division(db, company, body.name, body.short_code or "")
    elif body.level == "team":
        if not body.parent_id:
            raise HTTPException(status_code=400, detail="팀은 소속 본부를 골라야 합니다.")
        parent = await db.get(OrgUnit, body.parent_id)
        if parent is None:
            raise HTTPException(status_code=404, detail="본부를 찾을 수 없습니다.")
        unit = await _create_team(db, company, parent, body.name, body.number)
    else:
        raise HTTPException(status_code=400, detail="level 은 division 또는 team 입니다.")
    await db.commit()
    return {"id": str(unit.id), "code": unit.code, "name": unit.name, "level": unit.level,
            "parent_id": str(unit.parent_id) if unit.parent_id else None}


@router.post("/companies/{company_id}/org-units/bulk", status_code=status.HTTP_201_CREATED)
async def bulk_create_org_units(
    company_id: UUID,
    body: OrgBulkRequest,
    ctx: AdminContext = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """엑셀 붙여넣기용 일괄 등록. 행 = (본부, 본부 코드, 팀). 이미 있는 본부·팀(같은 이름)은 건너뛴다.

    한 행이라도 규칙 위반이면 전부 되돌린다(부분 등록 방지).
    """
    company = await _get_company(db, company_id)
    prefix = _require_prefix(company)
    created: List[dict] = []
    skipped = 0
    divisions = {u.short_code: u for u in (await db.execute(
        select(OrgUnit).where(OrgUnit.company_id == company.id, OrgUnit.level == "division")
    )).scalars().all()}
    try:
        for i, row in enumerate(body.rows, start=1):
            short = org_codes.normalize(row.division_code)
            div = divisions.get(short)
            if div is None:
                try:
                    div = await _create_division(db, company, row.division, short)
                except HTTPException as e:
                    raise HTTPException(status_code=e.status_code, detail=f"{i}행: {e.detail}")
                divisions[short] = div
                created.append({"code": div.code, "name": div.name, "level": "division"})
            elif div.name != row.division.strip():
                raise HTTPException(status_code=400,
                                    detail=f"{i}행: 본부 코드 {div.code} 는 이미 '{div.name}' 입니다.")
            team_name = (row.team or "").strip()
            if not team_name:
                continue
            same = (await db.execute(
                select(OrgUnit.id).where(OrgUnit.parent_id == div.id, OrgUnit.name == team_name)
            )).first()
            if same:
                skipped += 1
                continue
            try:
                t = await _create_team(db, company, div, team_name, None)
            except HTTPException as e:
                raise HTTPException(status_code=e.status_code, detail=f"{i}행: {e.detail}")
            created.append({"code": t.code, "name": t.name, "level": "team"})
        await db.commit()
    except HTTPException:
        await db.rollback()
        raise
    return {"prefix": prefix, "created": created, "skipped": skipped}


# ---------------------------------------------------------------------------
# 단위 수정·삭제 — 마스터 전용
# ---------------------------------------------------------------------------
@router.patch("/org-units/{unit_id}")
async def update_org_unit(
    unit_id: UUID,
    body: OrgUnitUpdateRequest,
    ctx: AdminContext = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """이름·사용 여부·순서만 바꾼다. 코드는 이미 배포됐을 수 있어 바꾸지 않는다."""
    unit = await db.get(OrgUnit, unit_id)
    if unit is None:
        raise HTTPException(status_code=404, detail="조직을 찾을 수 없습니다.")
    if body.name is not None:
        if not body.name.strip():
            raise HTTPException(status_code=400, detail="이름은 비울 수 없습니다.")
        unit.name = body.name.strip()
    if body.is_active is not None:
        unit.is_active = body.is_active
    if body.sort_order is not None:
        unit.sort_order = body.sort_order
    db.add(unit)
    await db.commit()
    return {"id": str(unit.id), "code": unit.code, "name": unit.name, "is_active": unit.is_active}


@router.delete("/org-units/{unit_id}")
async def delete_org_unit(
    unit_id: UUID,
    ctx: AdminContext = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """하위 팀이나 소속 참여자가 있으면 지우지 않는다(사용 중지로 막으면 된다)."""
    unit = await db.get(OrgUnit, unit_id)
    if unit is None:
        raise HTTPException(status_code=404, detail="조직을 찾을 수 없습니다.")
    if (await db.execute(select(OrgUnit.id).where(OrgUnit.parent_id == unit.id))).first():
        raise HTTPException(status_code=409, detail="소속 팀이 있어 삭제할 수 없습니다. 팀을 먼저 지우거나 사용 중지하세요.")
    if (await db.execute(select(Participant.id).where(Participant.org_unit_id == unit.id))).first():
        raise HTTPException(status_code=409, detail="이 코드로 참여한 사람이 있어 삭제할 수 없습니다. 사용 중지하세요.")
    await db.delete(unit)
    await db.commit()
    return {"deleted": True}
