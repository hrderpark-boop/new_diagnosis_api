# diag_project/routes/admin.py
#
# B2B SaaS 어드민 API.
#
# 권한 모델
#   - super_admin  : 전 고객사 데이터 + 시스템 전체 통계
#   - client_admin : 자사(company_id) 데이터만. 요청 파라미터로 우회 불가
#
# 모든 엔드포인트는 get_current_admin 을 통과해야 하며, 회사 격리는
# AdminContext.scope_query() 로 질의 단계에서 강제된다.

import io
import logging
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select

from diag_project.database import get_db
from diag_project.models.admin_user import AdminUser, UserRole
from diag_project.models.company import Company
from diag_project.models.diagnosis_report import DiagnosisReport
from diag_project.models.diagnosis_session import DiagnosisSession
from diag_project.models.participant import Participant
from diag_project.services.auth import (
    AdminContext,
    create_access_token,
    generate_temp_password,
    get_current_admin,
    hash_password,
    require_super_admin,
    verify_password,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["Admin"])


# ===========================================================================
# 스키마
# ===========================================================================
class AdminLoginRequest(BaseModel):
    email: str
    password: str


class AdminLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    admin_id: str
    name: Optional[str]
    email: str
    role: str
    company_id: Optional[str]
    company_name: Optional[str]


class AdminMeResponse(BaseModel):
    admin_id: str
    name: Optional[str]
    email: str
    role: str
    company_id: Optional[str]
    company_name: Optional[str]


class PasswordChangeRequest(BaseModel):
    current_password: str
    new_password: str
    confirm_password: str


class CompanyCreateRequest(BaseModel):
    name: str
    code: str
    contact_email: Optional[str] = None


class AdminCreateRequest(BaseModel):
    email: str
    # 미지정 시 서버가 안전한 임시 비밀번호를 생성해 1회 응답으로만 반환한다.
    # (해시만 저장되므로 이후 어떤 경로로도 다시 조회할 수 없다)
    password: Optional[str] = None
    name: Optional[str] = None
    role: str = UserRole.CLIENT_ADMIN.value
    company_id: Optional[str] = None


class PaginatedResponse(BaseModel):
    items: List[Dict[str, Any]]
    total: int
    page: int
    page_size: int
    total_pages: int


# ===========================================================================
# 내부 헬퍼
# ===========================================================================
async def _company_name(db: AsyncSession, company_id: Optional[UUID]) -> Optional[str]:
    if not company_id:
        return None
    result = await db.execute(select(Company.name).where(Company.id == company_id))
    return result.scalars().first()


async def _company_map(db: AsyncSession) -> Dict[UUID, str]:
    """company_id → 고객사명 조회용 맵 (목록 응답에 회사명을 붙이기 위함)."""
    result = await db.execute(select(Company.id, Company.name))
    return {row[0]: row[1] for row in result.all()}


# 조직 DNA 키워드에서 제외할 '방법론·시스템 용어'.
# LLM 이 평가 방법론 자체를 키워드로 뱉는 경우가 있어(STAR, BEI 등),
# 조직의 행동·성향을 나타내는 키워드만 남기도록 걸러낸다.
_KEYWORD_BLOCKLIST = {
    "star", "star 방법론", "star방법론", "bei", "bei 인터뷰", "행동사건면접",
    "루브릭", "rubric", "리더십 진단", "진단", "평가", "분석", "리포트",
    "인터뷰", "코칭", "코치", "ai", "gpt", "프롬프트", "역량", "역량 진단",
    "행동 지표", "행동지표", "채점", "점수", "메타인지", "자가진단",
    "situation", "action", "result", "task", "상황", "행동", "결과",
    "리더십", "리더", "조직", "구성원", "피드백",
}

# 방법론 용어가 부분 문자열로 섞인 경우까지 차단 (예: "STAR 기법 활용")
_KEYWORD_BLOCK_SUBSTRINGS = (
    "star", "bei", "루브릭", "rubric", "프롬프트", "방법론",
    "행동사건", "인터뷰", "채점", "진단 도구",
)


def _is_valid_keyword(word: str) -> bool:
    """조직 DNA 키워드로 채택할 만한 값인지 판정한다."""
    if not word:
        return False
    normalized = str(word).strip()
    if not normalized:
        return False
    # 지나치게 길면 키워드가 아니라 문장이다
    if len(normalized) > 20:
        return False
    lowered = normalized.lower()
    if lowered in _KEYWORD_BLOCKLIST:
        return False
    if any(bad in lowered for bad in _KEYWORD_BLOCK_SUBSTRINGS):
        return False
    # 숫자·기호만으로 이루어진 값 제외
    if not any(ch.isalnum() for ch in normalized):
        return False
    return True


def _avg(values: List[float]) -> Optional[float]:
    return round(sum(values) / len(values), 2) if values else None


def _correlation_matrix(series: Dict[str, List[float]]) -> List[Dict[str, Any]]:
    """역량 간 피어슨 상관계수를 실제 리포트 점수로 계산한다.

    표본이 3건 미만이거나 한쪽 분산이 0이면 상관계수가 의미를 갖지 못하므로
    해당 쌍은 결과에서 제외한다(임의값으로 채우지 않는다).
    """
    names = sorted(series.keys())
    result: List[Dict[str, Any]] = []

    for i, a in enumerate(names):
        for b in names[i + 1:]:
            xs, ys = series[a], series[b]
            n = min(len(xs), len(ys))
            if n < 3:
                continue
            xs, ys = xs[:n], ys[:n]
            mx, my = sum(xs) / n, sum(ys) / n
            cov = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
            var_x = sum((x - mx) ** 2 for x in xs)
            var_y = sum((y - my) ** 2 for y in ys)
            if var_x <= 0 or var_y <= 0:
                continue
            result.append(
                {
                    "a": a,
                    "b": b,
                    "coefficient": round(cov / ((var_x ** 0.5) * (var_y ** 0.5)), 2),
                    "sample_size": n,
                }
            )

    return sorted(result, key=lambda r: -abs(r["coefficient"]))


def _paginate(page: int, page_size: int) -> tuple[int, int]:
    page = max(1, page)
    page_size = min(max(1, page_size), 200)  # 과도한 페이지 크기 방어
    return page, page_size


# ===========================================================================
# 1. 인증
# ===========================================================================
@router.post("/auth/login", response_model=AdminLoginResponse)
async def admin_login(body: AdminLoginRequest, db: AsyncSession = Depends(get_db)):
    """관리자 로그인. 이메일/비밀번호 검증 후 JWT 발급."""
    result = await db.execute(
        select(AdminUser).where(AdminUser.email == body.email.strip().lower())
    )
    admin = result.scalars().first()

    # 계정 존재 여부를 노출하지 않도록 실패 메시지를 통일한다.
    if not admin or not verify_password(body.password, admin.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="이메일 또는 비밀번호가 올바르지 않습니다.",
        )
    if not admin.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="비활성화된 계정입니다. 운영자에게 문의하세요.",
        )

    admin.last_login_at = datetime.now(timezone.utc)
    db.add(admin)
    await db.commit()
    await db.refresh(admin)

    return AdminLoginResponse(
        access_token=create_access_token(admin),
        admin_id=str(admin.id),
        name=admin.name,
        email=admin.email,
        role=admin.role,
        company_id=str(admin.company_id) if admin.company_id else None,
        company_name=await _company_name(db, admin.company_id),
    )


@router.get("/auth/me", response_model=AdminMeResponse)
async def admin_me(
    ctx: AdminContext = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """현재 토큰의 관리자 정보. 프론트 라우트 가드가 권한 확인에 사용한다."""
    return AdminMeResponse(
        admin_id=str(ctx.admin.id),
        name=ctx.admin.name,
        email=ctx.admin.email,
        role=ctx.admin.role,
        company_id=str(ctx.company_id) if ctx.company_id else None,
        company_name=await _company_name(db, ctx.company_id),
    )


@router.patch("/users/me/password")
async def change_my_password(
    body: PasswordChangeRequest,
    ctx: AdminContext = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """본인 비밀번호 변경 — super_admin / client_admin 공통.

    대상 계정은 요청 본문이 아니라 '항상 JWT 토큰의 주체'로 결정된다.
    (본문으로 대상을 받으면 남의 비밀번호를 바꾸는 통로가 되므로 절대 받지 않는다)

    발급받은 임시 비밀번호를 최초 로그인 후 교체하는 것이 주 용도다.
    """
    admin = ctx.admin

    # 1) 현재 비밀번호 확인 — 토큰이 탈취된 상태에서의 계정 탈취를 막는 마지막 관문
    if not verify_password(body.current_password, admin.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="현재 비밀번호가 올바르지 않습니다.",
        )

    # 2) 새 비밀번호 정책 검증
    new_password = body.new_password
    if new_password != body.confirm_password:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="새 비밀번호와 확인 값이 일치하지 않습니다.",
        )
    if len(new_password) < 8:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="새 비밀번호는 8자 이상이어야 합니다.",
        )
    # bcrypt 는 72바이트까지만 검증에 사용하므로, 그 이상은 잘린 부분이
    # 무시돼 사용자가 기대한 것과 다르게 동작한다. 미리 막는다.
    if len(new_password.encode("utf-8")) > 72:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="새 비밀번호가 너무 깁니다. (최대 72바이트)",
        )
    if verify_password(new_password, admin.password_hash):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="현재 비밀번호와 다른 비밀번호를 사용하세요.",
        )

    # 3) 해시 갱신
    admin.password_hash = hash_password(new_password)
    db.add(admin)
    await db.commit()

    logger.info("관리자 비밀번호 변경: %s", admin.email)
    return {
        "success": True,
        "message": "비밀번호가 성공적으로 변경되었습니다.",
    }


# ===========================================================================
# 2. 참여자 관리 — 검색 + 페이지네이션 + 회사 격리
# ===========================================================================
@router.get("/participants", response_model=PaginatedResponse)
async def list_participants(
    search: Optional[str] = Query(None, description="이름/이메일/부서(그룹코드) 검색어"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    company_id: Optional[UUID] = Query(None, description="Super Admin 전용 고객사 필터"),
    ctx: AdminContext = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    page, page_size = _paginate(page, page_size)

    base = select(Participant)
    # 회사 격리: client_admin 은 자사로 고정, super_admin 만 선택적 필터 허용
    base = ctx.scope_query(base, Participant.company_id)
    if company_id and ctx.is_super_admin:
        base = base.where(Participant.company_id == company_id)

    if search:
        kw = f"%{search.strip()}%"
        base = base.where(
            or_(
                Participant.name.ilike(kw),
                Participant.email.ilike(kw),
                Participant.group_code.ilike(kw),
            )
        )

    # 전체 건수 (페이지네이션 메타)
    count_result = await db.execute(
        select(func.count()).select_from(base.subquery())
    )
    total = count_result.scalar() or 0

    result = await db.execute(
        base.order_by(Participant.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    participants = result.scalars().all()

    # 세션 통계를 참여자별로 한 번에 집계 (N+1 방지)
    p_ids = [p.id for p in participants]
    session_stats: Dict[UUID, Dict[str, Any]] = defaultdict(
        lambda: {"total": 0, "completed": 0, "last_status": "미시작", "last_at": None}
    )
    if p_ids:
        s_result = await db.execute(
            select(DiagnosisSession).where(DiagnosisSession.user_id.in_(p_ids))
        )
        for s in s_result.scalars().all():
            stat = session_stats[s.user_id]
            stat["total"] += 1
            if s.status == "completed":
                stat["completed"] += 1
            if stat["last_at"] is None or (s.created_at and s.created_at > stat["last_at"]):
                stat["last_at"] = s.created_at
                stat["last_status"] = s.status

    cmap = await _company_map(db)
    items = []
    for p in participants:
        stat = session_stats[p.id]
        items.append(
            {
                "id": str(p.id),
                "name": p.name or "-",
                "email": p.email,
                "group_code": p.group_code or "-",
                "company_id": str(p.company_id) if p.company_id else None,
                "company_name": cmap.get(p.company_id, "미지정") if p.company_id else "미지정",
                "gender": p.gender or "-",
                "age_group": p.age_group or "-",
                "total_sessions": stat["total"],
                "completed_sessions": stat["completed"],
                "last_status": stat["last_status"],
                "joined_at": p.created_at,
            }
        )

    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=max(1, (total + page_size - 1) // page_size),
    )


# ===========================================================================
# 3. 리포트 목록 — 검색 + 페이지네이션 + 회사 격리
# ===========================================================================
@router.get("/reports", response_model=PaginatedResponse)
async def list_reports(
    search: Optional[str] = Query(None, description="대상자 이름/이메일 검색어"),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    company_id: Optional[UUID] = Query(None, description="Super Admin 전용 고객사 필터"),
    ctx: AdminContext = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """리포트는 company 컬럼이 없으므로 participants 와 조인해 격리한다."""
    page, page_size = _paginate(page, page_size)

    base = select(DiagnosisReport, Participant).join(
        Participant, DiagnosisReport.user_id == Participant.id
    )
    base = ctx.scope_query(base, Participant.company_id)
    if company_id and ctx.is_super_admin:
        base = base.where(Participant.company_id == company_id)

    if search:
        kw = f"%{search.strip()}%"
        base = base.where(
            or_(Participant.name.ilike(kw), Participant.email.ilike(kw))
        )

    count_result = await db.execute(select(func.count()).select_from(base.subquery()))
    total = count_result.scalar() or 0

    result = await db.execute(
        base.order_by(DiagnosisReport.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    rows = result.all()

    cmap = await _company_map(db)
    items = [
        {
            "id": str(r.id),
            "session_id": str(r.session_id),
            "user_id": str(r.user_id),
            "user_name": p.name or "익명",
            "user_email": p.email,
            "company_name": cmap.get(p.company_id, "미지정") if p.company_id else "미지정",
            "group_code": p.group_code or "-",
            "total_score": r.total_score,
            "scores": r.scores or {},
            "summary": r.summary,
            "top_competency": r.top_competency,
            "bottom_competency": r.bottom_competency,
            "created_at": r.created_at,
            # 관리자 검수 여부 — 목록에서 교정 완료 건을 구분한다
            "is_human_edited": r.is_human_edited,
            "edited_at": r.edited_at,
            "edited_by": r.edited_by,
        }
        for r, p in rows
    ]

    return PaginatedResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
        total_pages=max(1, (total + page_size - 1) // page_size),
    )


@router.get("/reports/{report_id}")
async def get_report_detail(
    report_id: UUID,
    ctx: AdminContext = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """리포트 단건 상세 (관리자 교정 화면용).

    프론트 리포트 뷰어는 session_id 로 조회하지만, 어드민 목록에서는
    report_id 를 키로 다루므로 별도 엔드포인트를 둔다. 회사 격리 적용.
    """
    report = (
        await db.execute(select(DiagnosisReport).where(DiagnosisReport.id == report_id))
    ).scalars().first()
    if not report:
        raise HTTPException(status_code=404, detail="리포트를 찾을 수 없습니다.")

    participant = await db.get(Participant, report.user_id)
    ctx.assert_can_access_company(participant.company_id if participant else None)

    # 자가진단은 세션에 저장돼 있다
    session = await db.get(DiagnosisSession, report.session_id)

    saved = report.scores or {}
    return {
        "id": str(report.id),
        "session_id": str(report.session_id),
        "user_name": participant.name if participant else "알 수 없음",
        "user_email": participant.email if participant else None,
        "company_name": await _company_name(
            db, participant.company_id if participant else None
        ),
        "total_score": report.total_score,
        "summary": report.summary,
        "radar_chart": saved.get("radar_chart", {}),
        "details": saved.get("details", {}),
        "top_keywords": saved.get("top_keywords", []),
        "blind_spot": saved.get("blind_spot"),
        "idp": saved.get("idp", []),
        "created_at": report.created_at,
        # Human-in-the-Loop 상태
        "is_human_edited": report.is_human_edited,
        "edited_at": report.edited_at,
        "edited_by": report.edited_by,
        "has_ai_original": report.ai_original is not None,
        # 대상자가 대화 시작 전 스스로 매긴 평가 (메타인지 비교용)
        "self_assessment": session.self_assessment_data if session else None,
    }


@router.get("/reports/{report_id}/ai-original")
async def get_report_ai_original(
    report_id: UUID,
    ctx: AdminContext = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """교정 전 AI 원본 스냅샷. 교정 결과와 나란히 비교할 때 사용한다."""
    report = (
        await db.execute(select(DiagnosisReport).where(DiagnosisReport.id == report_id))
    ).scalars().first()
    if not report:
        raise HTTPException(status_code=404, detail="리포트를 찾을 수 없습니다.")

    participant = await db.get(Participant, report.user_id)
    ctx.assert_can_access_company(participant.company_id if participant else None)

    if not report.ai_original:
        raise HTTPException(
            status_code=404, detail="이 리포트에는 저장된 AI 원본이 없습니다(교정 이력 없음)."
        )

    original = report.ai_original
    return {
        "summary": original.get("summary"),
        "details": (original.get("scores") or {}).get("details", {}),
        "snapshot_at": original.get("snapshot_at"),
    }


# ===========================================================================
# 4. 집계 통계 API (하드코딩 Mock 대체)
# ===========================================================================
@router.get("/stats/overview")
async def stats_overview(
    company_id: Optional[UUID] = Query(None),
    ctx: AdminContext = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """KPI 카드용 요약 지표 — 권한 범위에 따라 전사 또는 자사 기준으로 집계."""
    p_query = ctx.scope_query(select(Participant.id), Participant.company_id)
    if company_id and ctx.is_super_admin:
        p_query = p_query.where(Participant.company_id == company_id)
    p_ids = [row[0] for row in (await db.execute(p_query)).all()]

    if not p_ids:
        return {
            "scope": "all" if ctx.is_super_admin else "company",
            "total_participants": 0,
            "total_sessions": 0,
            "completed_sessions": 0,
            "in_progress_sessions": 0,
            "completion_rate": 0.0,
            "total_reports": 0,
            "average_score": 0.0,
            "total_companies": 0,
        }

    s_result = await db.execute(
        select(DiagnosisSession.status, func.count())
        .where(DiagnosisSession.user_id.in_(p_ids))
        .group_by(DiagnosisSession.status)
    )
    status_counts = {row[0]: row[1] for row in s_result.all()}
    total_sessions = sum(status_counts.values())
    completed = status_counts.get("completed", 0)

    r_result = await db.execute(
        select(func.count(DiagnosisReport.id), func.avg(DiagnosisReport.total_score))
        .where(DiagnosisReport.user_id.in_(p_ids))
    )
    total_reports, avg_score = r_result.one()

    total_companies = 0
    if ctx.is_super_admin:
        c_result = await db.execute(select(func.count(Company.id)))
        total_companies = c_result.scalar() or 0

    return {
        "scope": "all" if ctx.is_super_admin else "company",
        "total_participants": len(p_ids),
        "total_sessions": total_sessions,
        "completed_sessions": completed,
        "in_progress_sessions": status_counts.get("in_progress", 0),
        "completion_rate": round(completed / total_sessions * 100, 1) if total_sessions else 0.0,
        "total_reports": total_reports or 0,
        "average_score": round(float(avg_score), 2) if avg_score else 0.0,
        "total_companies": total_companies,
    }


@router.get("/stats/daily")
async def stats_daily(
    days: int = Query(7, ge=1, le=90, description="조회할 최근 일수"),
    company_id: Optional[UUID] = Query(None),
    ctx: AdminContext = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """최근 N일 일별 추이 (기존 CHART_DATA Mock 을 대체).

    날짜 집계는 DB 방언(Postgres/SQLite)에 따라 date 함수 동작이 달라
    이식성 문제가 생기므로, 기간 데이터를 가져와 파이썬에서 버킷팅한다.
    (진단 세션 규모상 전체 스캔 비용이 문제되지 않는다)
    """
    p_query = ctx.scope_query(select(Participant.id), Participant.company_id)
    if company_id and ctx.is_super_admin:
        p_query = p_query.where(Participant.company_id == company_id)
    p_ids = [row[0] for row in (await db.execute(p_query)).all()]

    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=days - 1)
    buckets = {
        (start + timedelta(days=i)): {"sessions": 0, "completed": 0}
        for i in range(days)
    }

    if p_ids:
        s_result = await db.execute(
            select(DiagnosisSession).where(DiagnosisSession.user_id.in_(p_ids))
        )
        for s in s_result.scalars().all():
            if not s.created_at:
                continue
            d = s.created_at.date()
            if d in buckets:
                buckets[d]["sessions"] += 1
                if s.status == "completed":
                    buckets[d]["completed"] += 1

    return [
        {
            "date": d.isoformat(),
            "name": d.strftime("%m/%d"),
            "진단참여": v["sessions"],
            "진단완료": v["completed"],
        }
        for d, v in sorted(buckets.items())
    ]


@router.get("/stats/competencies")
async def stats_competencies(
    company_id: Optional[UUID] = Query(None),
    ctx: AdminContext = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """역량별 평균 점수 + 상관관계 (레이더/네트워크 Mock 대체)."""
    base = select(DiagnosisReport, Participant).join(
        Participant, DiagnosisReport.user_id == Participant.id
    )
    base = ctx.scope_query(base, Participant.company_id)
    if company_id and ctx.is_super_admin:
        base = base.where(Participant.company_id == company_id)

    rows = (await db.execute(base)).all()

    sums: Dict[str, float] = defaultdict(float)
    counts: Dict[str, int] = defaultdict(int)
    total_scores: List[float] = []
    keyword_freq: Dict[str, int] = defaultdict(int)
    # 상관계수 계산용: 역량명 → 참여자별 점수 벡터
    series: Dict[str, List[float]] = defaultdict(list)
    # 전사 아코디언용 누적기: 역량 → 세부지표/산출근거/분포/발췌
    sub_scores_acc: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
    breakdown_acc: Dict[str, Dict[str, List[float]]] = defaultdict(lambda: defaultdict(list))
    distribution_acc: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    strength_samples: Dict[str, List[str]] = defaultdict(list)
    growth_samples: Dict[str, List[str]] = defaultdict(list)

    for report, _p in rows:
        if report.total_score:
            total_scores.append(float(report.total_score))

        # 리포트의 scores JSON 은 {radar_chart, details, top_keywords} 구조.
        # 역량 점수는 radar_chart 에 들어 있고, 구버전은 최상위에 평평하게 있다.
        saved = report.scores or {}
        radar = saved.get("radar_chart") or {
            k: v for k, v in saved.items()
            if k not in ("radar_chart", "details", "top_keywords") and isinstance(v, (int, float))
        }

        for comp, score in (radar or {}).items():
            try:
                value = float(score)
            except (TypeError, ValueError):
                continue
            sums[comp] += value
            counts[comp] += 1
            series[comp].append(value)

        # 실제 리포트에서 추출된 핵심 키워드 빈도 (조직 DNA 키워드의 근거)
        # 평가 방법론 용어(STAR/BEI 등)는 조직의 특성이 아니므로 걸러낸다.
        for kw in saved.get("top_keywords") or []:
            word = kw.get("keyword") if isinstance(kw, dict) else kw
            if _is_valid_keyword(word):
                keyword_freq[str(word).strip()] += 1

        # ── 역량별 세부 지표 집계 (전사 단위 아코디언용) ──
        for comp, block in (saved.get("details") or {}).items():
            if not isinstance(block, dict):
                continue

            # 세부 역량(sub_scores) 평균
            for sub_name, sub_score in (block.get("sub_scores") or {}).items():
                try:
                    sub_scores_acc[comp][str(sub_name)].append(float(sub_score))
                except (TypeError, ValueError):
                    continue

            # 점수 산출 근거(score_breakdown) 평균
            for field, value in (block.get("score_breakdown") or {}).items():
                try:
                    breakdown_acc[comp][str(field)].append(float(value))
                except (TypeError, ValueError):
                    continue

            # 점수 분포 (상/중/하 인원)
            try:
                comp_score = float(block.get("score"))
            except (TypeError, ValueError):
                comp_score = None
            if comp_score is not None:
                bucket = "high" if comp_score >= 4.0 else ("low" if comp_score < 3.0 else "mid")
                distribution_acc[comp][bucket] += 1

            # 강점·개선점은 개인별 자유 서술이라 '평균'을 낼 수 없다.
            # 대신 익명 발췌를 모아 조직 차원의 경향을 읽을 수 있게 한다.
            sp = (block.get("strength_point") or "").strip()
            gp = (block.get("growth_point") or "").strip()
            if sp:
                strength_samples[comp].append(sp)
            if gp:
                growth_samples[comp].append(gp)

    competencies = []
    for comp in sorted(sums.keys()):
        sub_avg = {
            name: _avg(values)
            for name, values in sorted(sub_scores_acc.get(comp, {}).items())
        }
        bd = breakdown_acc.get(comp, {})
        dist = distribution_acc.get(comp, {})
        competencies.append({
            "competency": comp,
            "average": round(sums[comp] / counts[comp], 2),
            "sample_size": counts[comp],
            # 전사 평균 세부 역량 (스파이더 차트 + 막대)
            "sub_scores": sub_avg,
            # 전사 평균 점수 산출 근거
            "score_breakdown": {
                "rubric_base": _avg(bd.get("rubric_base", [])),
                "star_depth_bonus": _avg(bd.get("star_depth_bonus", [])),
                "confidence_adj": _avg(bd.get("confidence_adj", [])),
                "final": _avg(bd.get("final", [])),
            },
            # 점수 분포: 4.0 이상 / 3.0~3.9 / 3.0 미만
            "distribution": {
                "high": dist.get("high", 0),
                "mid": dist.get("mid", 0),
                "low": dist.get("low", 0),
            },
            # 익명 발췌 (최대 3건). 평균 낼 수 없는 서술형의 대안.
            "strength_samples": strength_samples.get(comp, [])[:3],
            "growth_samples": growth_samples.get(comp, [])[:3],
        })

    # ── 인식의 차이(Gap Analysis): 자가진단 평균 vs AI 분석 평균 ──
    # 리포트가 있는 세션 중 '자가진단을 제출한' 건만 대상으로 한다.
    # (미제출 건을 0점으로 섞으면 갭이 왜곡되므로 표본에서 제외)
    session_ids = [r.session_id for r, _p in rows]
    self_sums: Dict[str, float] = defaultdict(float)
    self_counts: Dict[str, int] = defaultdict(int)
    self_averages: List[float] = []
    ai_averages_paired: List[float] = []

    if session_ids:
        s_rows = (
            await db.execute(
                select(DiagnosisSession).where(DiagnosisSession.id.in_(session_ids))
            )
        ).scalars().all()
        self_by_session = {
            s.id: s.self_assessment_data for s in s_rows if s.self_assessment_data
        }

        for report, _p in rows:
            sa = self_by_session.get(report.session_id)
            if not sa:
                continue
            sa_scores = sa.get("scores") or {}
            if not sa_scores:
                continue

            for comp, value in sa_scores.items():
                try:
                    self_sums[comp] += float(value)
                    self_counts[comp] += 1
                except (TypeError, ValueError):
                    continue

            # 동일 인물의 자가 평균 ↔ AI 총점을 쌍으로 모아야 갭이 의미를 갖는다
            try:
                self_averages.append(float(sa.get("self_average") or 0))
                ai_averages_paired.append(float(report.total_score or 0))
            except (TypeError, ValueError):
                continue

    self_avg = round(sum(self_averages) / len(self_averages), 2) if self_averages else 0.0
    ai_avg_paired = (
        round(sum(ai_averages_paired) / len(ai_averages_paired), 2)
        if ai_averages_paired else 0.0
    )

    gap_by_competency = []
    for comp in sorted(set(list(sums.keys()) + list(self_sums.keys()))):
        ai_value = round(sums[comp] / counts[comp], 2) if counts[comp] else None
        self_value = (
            round(self_sums[comp] / self_counts[comp], 2) if self_counts[comp] else None
        )
        gap_by_competency.append({
            "competency": comp,
            "ai_score": ai_value,
            "self_score": self_value,
            # 양수 = 실제보다 자신을 높게 평가(과대 인식)
            "gap": round(self_value - ai_value, 2)
            if (ai_value is not None and self_value is not None) else None,
        })

    return {
        "participants_count": len(rows),
        "total_average": round(sum(total_scores) / len(total_scores), 2) if total_scores else 0.0,
        "competencies": competencies,
        "correlations": _correlation_matrix(series),
        "keywords": [
            {"keyword": k, "count": v}
            for k, v in sorted(keyword_freq.items(), key=lambda x: -x[1])[:12]
            if v > 0
        ],
        "gap_analysis": {
            # 자가진단을 제출한 표본 수. 0 이면 프론트는 '데이터 없음'을 표시한다.
            "sample_size": len(self_averages),
            "self_average": self_avg,
            "ai_average": ai_avg_paired,
            "gap": round(self_avg - ai_avg_paired, 2) if self_averages else 0.0,
            "by_competency": gap_by_competency,
        },
    }


# ===========================================================================
# 5. 고객사 관리 (Super Admin 전용)
# ===========================================================================
@router.get("/companies")
async def list_companies(
    ctx: AdminContext = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """전 고객사 목록 + 고객사별 참여자/세션 규모."""
    companies = (await db.execute(select(Company).order_by(Company.name))).scalars().all()

    p_rows = (
        await db.execute(
            select(Participant.company_id, func.count(Participant.id)).group_by(
                Participant.company_id
            )
        )
    ).all()
    p_counts = {row[0]: row[1] for row in p_rows}

    return [
        {
            "id": str(c.id),
            "name": c.name,
            "code": c.code,
            "contact_email": c.contact_email,
            "is_active": c.is_active,
            "participant_count": p_counts.get(c.id, 0),
            "created_at": c.created_at,
        }
        for c in companies
    ]


@router.post("/companies", status_code=status.HTTP_201_CREATED)
async def create_company(
    body: CompanyCreateRequest,
    ctx: AdminContext = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    exists = (
        await db.execute(select(Company).where(Company.code == body.code.strip()))
    ).scalars().first()
    if exists:
        raise HTTPException(status_code=409, detail="이미 존재하는 고객사 코드입니다.")

    company = Company(
        name=body.name.strip(),
        code=body.code.strip(),
        contact_email=body.contact_email,
    )
    db.add(company)
    await db.commit()
    await db.refresh(company)
    return {"id": str(company.id), "name": company.name, "code": company.code}


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_admin_user(
    body: AdminCreateRequest,
    ctx: AdminContext = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """관리자 계정 발급 — 운영자(Super Admin) 전용.

    require_super_admin 의존성이 role 을 검증하므로, client_admin 토큰으로는
    이 엔드포인트에 도달할 수 없다(403).

    비밀번호를 생략하면 서버가 안전한 임시 비밀번호를 생성해 응답에 1회만
    담아 돌려준다. DB 에는 bcrypt 해시만 남으므로 이후 재조회는 불가능하며,
    운영자는 이 값을 담당자에게 전달한 뒤 변경을 안내해야 한다.
    """
    if body.role not in (UserRole.SUPER_ADMIN.value, UserRole.CLIENT_ADMIN.value):
        raise HTTPException(status_code=400, detail="허용되지 않는 role 입니다.")
    if body.role == UserRole.CLIENT_ADMIN.value and not body.company_id:
        raise HTTPException(
            status_code=400, detail="client_admin 은 소속 고객사(company_id)가 필요합니다."
        )

    email = body.email.strip().lower()
    exists = (
        await db.execute(select(AdminUser).where(AdminUser.email == email))
    ).scalars().first()
    if exists:
        raise HTTPException(status_code=409, detail="이미 등록된 이메일입니다.")

    company = None
    if body.company_id:
        try:
            company_uuid = UUID(body.company_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="company_id 형식이 올바르지 않습니다.")
        company = (
            await db.execute(select(Company).where(Company.id == company_uuid))
        ).scalars().first()
        if not company:
            raise HTTPException(status_code=404, detail="존재하지 않는 고객사입니다.")

    # 비밀번호 미지정 → 서버 생성 (평문은 이 응답에만 존재)
    generated = None
    if body.password:
        if len(body.password) < 8:
            raise HTTPException(status_code=400, detail="비밀번호는 8자 이상이어야 합니다.")
        raw_password = body.password
    else:
        raw_password = generate_temp_password()
        generated = raw_password

    admin = AdminUser(
        email=email,
        name=body.name,
        role=body.role,
        password_hash=hash_password(raw_password),
        company_id=company.id if company else None,
    )
    db.add(admin)
    await db.commit()
    await db.refresh(admin)

    return {
        "id": str(admin.id),
        "email": admin.email,
        "name": admin.name,
        "role": admin.role,
        "company_id": str(admin.company_id) if admin.company_id else None,
        "company_name": company.name if company else None,
        # 자동 생성한 경우에만 채워진다. 화면에서 1회 노출 후 다시 볼 수 없다.
        "generated_password": generated,
    }


# 하위 호환: 이전 경로(/admins)로 들어오는 호출도 동일하게 처리한다.
@router.post("/admins", status_code=status.HTTP_201_CREATED, include_in_schema=False)
async def create_admin_legacy(
    body: AdminCreateRequest,
    ctx: AdminContext = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    return await create_admin_user(body, ctx, db)


@router.get("/users")
async def list_admin_users(
    company_id: Optional[UUID] = Query(None),
    ctx: AdminContext = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """발급된 관리자 계정 목록 (운영자 전용). 비밀번호는 어떤 형태로도 반환하지 않는다."""
    query = select(AdminUser)
    if company_id:
        query = query.where(AdminUser.company_id == company_id)

    admins = (await db.execute(query.order_by(AdminUser.created_at.desc()))).scalars().all()
    cmap = await _company_map(db)

    return [
        {
            "id": str(a.id),
            "email": a.email,
            "name": a.name,
            "role": a.role,
            "company_id": str(a.company_id) if a.company_id else None,
            "company_name": cmap.get(a.company_id) if a.company_id else None,
            "is_active": a.is_active,
            "last_login_at": a.last_login_at,
            "created_at": a.created_at,
        }
        for a in admins
    ]


@router.post("/companies/sync-participants")
async def sync_participants_company(
    ctx: AdminContext = Depends(require_super_admin),
    db: AsyncSession = Depends(get_db),
):
    """기존 참여자의 group_code 를 companies.code 와 대조해 company_id 를 채운다.

    RBAC 도입 이전에 쌓인 데이터에는 company_id 가 비어 있어, Client Admin
    화면에서 보이지 않는다. 운영자가 1회 실행해 소급 매핑하기 위한 유틸.
    """
    companies = (await db.execute(select(Company))).scalars().all()
    code_map = {c.code: c.id for c in companies}

    participants = (
        await db.execute(select(Participant).where(Participant.company_id.is_(None)))
    ).scalars().all()

    updated = 0
    for p in participants:
        cid = code_map.get(p.group_code)
        if cid:
            p.company_id = cid
            db.add(p)
            updated += 1

    if updated:
        await db.commit()

    return {"scanned": len(participants), "updated": updated}


# ===========================================================================
# 6. 엑셀 내보내기 (권한 범위 내 데이터만)
# ===========================================================================
@router.get("/export_excel")
async def export_diagnosis_data(
    ctx: AdminContext = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    base = select(DiagnosisSession, Participant).join(
        Participant, DiagnosisSession.user_id == Participant.id
    )
    base = ctx.scope_query(base, Participant.company_id)
    rows = (await db.execute(base.order_by(DiagnosisSession.created_at.desc()))).all()

    cmap = await _company_map(db)
    export_list = [
        {
            "Session ID": str(s.id),
            "Date": s.created_at.strftime("%Y-%m-%d %H:%M") if s.created_at else "-",
            "Company": cmap.get(p.company_id, "미지정") if p.company_id else "미지정",
            "User Name": p.name or "Unknown",
            "Email": p.email,
            "Group Code": p.group_code or "-",
            "Coach ID": str(s.coach_id),
            "Status": s.status,
        }
        for s, p in rows
    ]

    df = pd.DataFrame(export_list)
    stream = io.BytesIO()
    with pd.ExcelWriter(stream, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Diagnosis_Logs")
    stream.seek(0)

    filename = f"diagnosis_export_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return StreamingResponse(
        stream,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )
