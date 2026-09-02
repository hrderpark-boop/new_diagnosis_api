import copy
import uuid
import json
import logging
from datetime import datetime
from typing import List, Dict, Any, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from pydantic import BaseModel

from diag_project.database import get_db
from diag_project.models.diagnosis_report import DiagnosisReport
from diag_project.models.diagnosis_session import DiagnosisSession, ChatMessage
from diag_project.models.participant import Participant
from diag_project.models.coach_persona import CoachPersona
from diag_project.models.event import Event
from diag_project.data.competencies import COMPETENCY_FRAMEWORK
from diag_project.llm_service import GeminiService
from diag_project.services.auth import AdminContext, get_current_admin

logger = logging.getLogger(__name__)


def _build_asked_subcompetencies(store: dict) -> Dict[str, set]:
    """T1/T2(§1-2): asked 원장을 '영속 store'(session.self_assessment_data
    ["asked_subs"])에서만 읽는다 — 대화 제어와 분석이 동일 소스를 본다.

    백엔드가 LLM 호출 이전에 결정론적으로 기록한 타겟이 유일 기준.
    텍스트 스캔/Event 태깅에 의존하지 않는다(유령·불일치 방지).
    """
    asked_map = ((store or {}).get("asked_subs") or {})
    asked: Dict[str, set] = {}
    for ck, cv in COMPETENCY_FRAMEWORK.items():
        if ck == "supplementary":
            continue
        subs = {ind["name"] for ind in cv.get("indicators", {}).values()}
        recorded = set(asked_map.get(ck) or [])
        asked[ck] = {s for s in recorded if s in subs}
    return asked


def resolve_completion_status(completed_count: int) -> str:
    """V-6/조정3: analyze 시 세션 상태 — 3종만. 완주(5)면 'completed', 미완주면
    'in_progress'(재개 대상). 'completed_insufficient'·'incomplete' 는 만들지
    않는다. 'aborted_disengaged' 는 이탈 경로에서만 설정된다(여기 아님).
    """
    return "completed" if completed_count >= 5 else "in_progress"


def _build_chapter_transcripts(
    messages: list, events: list
) -> Dict[str, str]:
    """역량(챕터)별로 대화·사건을 결정론적으로 분리 (Map-Reduce 의 Map 입력).

    - ChatMessage.chapter 가 None 인 메시지(라포·INTRO 등 첫 START_CHAPTER
      이전 사담)는 자동 제외 → 채점 노이즈 차단.
    - LLM 분류(환각 위험) 대신, DB 의 chapter 태그로 100% 정확히 필터링.
    - 각 챕터에 수집된 Event(STAR·mapped_subcompetency)도 함께 묶어 근거 강화.
    """
    transcripts: Dict[str, str] = {}
    for key in COMPETENCY_FRAMEWORK.keys():
        if key == "supplementary":
            continue
        chap_msgs = [m for m in messages if getattr(m, "chapter", None) == key]
        lines = [
            f"{'리더' if m.role == 'user' else '코치'}: {m.content}"
            for m in chap_msgs
            if m.content
        ]

        chap_events = [e for e in events if getattr(e, "chapter", None) == key]
        ev_lines = []
        for e in chap_events:
            parts = []
            if e.mapped_subcompetency:
                parts.append(f"하위역량={e.mapped_subcompetency}")
            if e.summary:
                parts.append(f"요약={e.summary}")
            if e.core_action:
                parts.append(f"핵심행동={e.core_action}")
            if e.result:
                parts.append(f"결과={e.result}")
            if parts:
                ev_lines.append("  - " + " | ".join(parts))

        body = "\n".join(lines)
        if ev_lines:
            body += "\n\n[수집된 핵심 사건]\n" + "\n".join(ev_lines)
        transcripts[key] = body.strip() or "이 영역에 대한 대화 기록이 없습니다."
    return transcripts

router = APIRouter(
    tags=["Reports"],
)


# ==========================================================================
# Human-in-the-Loop: 관리자 교정 스키마
# ==========================================================================
class ReasoningStepEdit(BaseModel):
    """STAR 단계별 교정. description 만 수정 대상이며,
    evidence(원문 발췌)는 '리더의 실제 발화'이므로 교정 대상에서 제외한다."""
    description: Optional[str] = None


class CompetencyEdit(BaseModel):
    comment: Optional[str] = None            # 코치 피드백
    strength_point: Optional[str] = None
    growth_point: Optional[str] = None
    gap_analysis: Optional[str] = None
    # 키: "1_situation" | "2_action" | "3_result"
    reasoning_process: Optional[Dict[str, ReasoningStepEdit]] = None


class ReportUpdateRequest(BaseModel):
    """부분 갱신(PATCH 시맨틱)을 따른다.

    None 인 필드는 '변경 없음'으로 간주하고 기존 값을 유지한다.
    전체 치환이 아니므로 관리자가 특정 문단만 고쳐도 나머지가 날아가지 않는다.
    """
    summary: Optional[str] = None
    blind_spot: Optional[str] = None
    details: Optional[Dict[str, CompetencyEdit]] = None


# --------------------------------------------------------------------------
# [신규] 관리자용 전체 리포트 목록 조회 (GET /)
# --------------------------------------------------------------------------
@router.get("/")
async def get_all_reports(db: AsyncSession = Depends(get_db)):
    # 1. 전체 리포트 최신순 조회
    report_query = select(DiagnosisReport).order_by(DiagnosisReport.created_at.desc())
    report_res = await db.execute(report_query)
    reports = report_res.scalars().all()

    # 2. 매핑을 위한 사용자 정보 전체 조회
    user_query = select(Participant)
    user_res = await db.execute(user_query)
    users = {str(u.id): u.name for u in user_res.scalars().all()}

    response_data = []
    for r in reports:
        response_data.append({
            "id": str(r.id),
            "session_id": str(r.session_id),
            "user_name": users.get(str(r.user_id), "알 수 없음"),
            "total_score": round(r.total_score, 2),
            "summary": r.summary,
            "created_at": r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else ""
        })
    return response_data

# --------------------------------------------------------------------------
# [1] 개별 결과 조회 (GET /{session_id}) - 프론트엔드 호출용
# --------------------------------------------------------------------------
@router.get("/{session_id}")
async def get_report(session_id: str, db: AsyncSession = Depends(get_db)):
    try:
        target_uuid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")

    query = select(DiagnosisReport).where(DiagnosisReport.session_id == target_uuid)
    result = await db.execute(query)
    report = result.scalars().first()

    if not report:
        # B: 리포트 부재의 두 상황을 구분한다.
        #   · 분석 중  → 기다리면 나옴 (프론트: 계속 폴링)
        #   · degraded → 기다려도 안 나옴 (프론트: 폴링 중단, 재시도 필요)
        #   세션의 last_analysis 마커를 404 body 에 실어 프론트가 분기하게 한다.
        _sess = await db.get(DiagnosisSession, target_uuid)
        _la = ((getattr(_sess, "self_assessment_data", None) or {})
               .get("last_analysis") or {}) if _sess else {}
        _status = _la.get("status")  # "degraded" | None(분석 중)
        raise HTTPException(
            status_code=404,
            detail={
                "message": "Report not ready",
                "analysis_status": _status or "analyzing",
                "reason": _la.get("error_competencies"),
                # 원장 보존 → 재시도 실패해도 이어하기 가능
                "resumable": True,
            })

    coach_name = "AI Coach"
    user_name = "Leader"
    
    session_res = await db.get(DiagnosisSession, target_uuid)
    if session_res:
        user = await db.get(Participant, session_res.user_id)
        if user: user_name = user.name
        if session_res.coach_id:
            persona_res = await db.execute(select(CoachPersona).where(CoachPersona.coach_id == session_res.coach_id))
            persona = persona_res.scalars().first()
            if persona: coach_name = persona.name
            
    # 🚨 프론트엔드가 요구하는 새로운 JSON 포맷을 그대로 살려서 반환
    saved_scores = report.scores or {}
    return {
        "user_name": user_name,
        "coach_name": coach_name,
        "total_score": report.total_score,
        "summary": report.summary,
        "radar_chart": saved_scores.get("radar_chart", saved_scores),
        "details": saved_scores.get("details", {}),
        "top_keywords": saved_scores.get("top_keywords", []),
        # 🎯 맞춤형 교육과정 추천(성장 처방전) — 프론트 최하단 섹션 렌더용.
        "course_recommendation": saved_scores.get("course_recommendation"),
        # 🔒 P0-1: 측정 커버리지 (측정 n / 26) — 상단 노출용.
        "coverage": saved_scores.get("coverage"),
        "created_at": report.created_at.strftime("%Y-%m-%d") if report.created_at else datetime.now().strftime("%Y-%m-%d")
    }

# --------------------------------------------------------------------------
# [1-b] 관리자 교정 (PUT /{report_id}) — Human-in-the-Loop
# --------------------------------------------------------------------------
def _apply_competency_edit(target: Dict[str, Any], edit: CompetencyEdit) -> List[str]:
    """단일 역량 블록에 교정 내용을 적용하고, 변경된 필드명을 반환한다."""
    changed: List[str] = []

    for field in ("comment", "strength_point", "growth_point", "gap_analysis"):
        value = getattr(edit, field)
        if value is None:
            continue
        new_value = value.strip()
        if target.get(field) != new_value:
            target[field] = new_value
            changed.append(field)

    if edit.reasoning_process:
        rp = target.setdefault("reasoning_process", {})
        for step_key, step_edit in edit.reasoning_process.items():
            if step_key not in ("1_situation", "2_action", "3_result"):
                raise HTTPException(
                    status_code=400,
                    detail=f"알 수 없는 STAR 단계입니다: {step_key}",
                )
            if step_edit.description is None:
                continue
            # 구버전 리포트는 이 값이 문자열일 수 있다 → 객체로 승격
            step = rp.get(step_key)
            if not isinstance(step, dict):
                step = {"description": step or "", "evidence": []}
            new_desc = step_edit.description.strip()
            if step.get("description") != new_desc:
                step["description"] = new_desc
                changed.append(f"reasoning_process.{step_key}")
            rp[step_key] = step

    return changed


@router.put("/{report_id}")
async def update_report(
    report_id: str,
    body: ReportUpdateRequest,
    ctx: AdminContext = Depends(get_current_admin),
    db: AsyncSession = Depends(get_db),
):
    """관리자가 교정한 AI 피드백을 DB 에 덮어쓴다 (골든 데이터셋 구축).

    - 관리자 인증 필수. Client Admin 은 자사 소속 대상자의 리포트만 교정 가능.
    - 최초 교정 시 AI 원본(scores)을 ai_original 에 스냅샷으로 보존한다.
      학습 데이터는 (AI 원본 → 사람 교정본) 쌍에서 나오므로, 원본 없이
      덮어쓰기만 하면 데이터셋으로서의 가치가 사라진다.
    - is_human_edited 를 True 로 올려 '사람이 검수·확정한 샘플'을 식별한다.
    """
    try:
        target_uuid = uuid.UUID(report_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID format")

    report = (
        await db.execute(select(DiagnosisReport).where(DiagnosisReport.id == target_uuid))
    ).scalars().first()
    if not report:
        raise HTTPException(status_code=404, detail="리포트를 찾을 수 없습니다.")

    # 회사 격리: 리포트에는 company 컬럼이 없으므로 대상자를 통해 확인한다.
    participant = await db.get(Participant, report.user_id)
    ctx.assert_can_access_company(participant.company_id if participant else None)

    # SQLAlchemy 는 JSON 컬럼 '내부' 변경을 자동 감지하지 못한다.
    # 깊은 복사본을 수정한 뒤 통째로 재할당해야 UPDATE 가 발생한다.
    scores: Dict[str, Any] = copy.deepcopy(report.scores or {})
    details: Dict[str, Any] = scores.setdefault("details", {})
    changed_fields: List[str] = []

    if body.details:
        for comp_key, edit in body.details.items():
            if comp_key not in details:
                raise HTTPException(
                    status_code=400,
                    detail=f"리포트에 존재하지 않는 역량입니다: {comp_key}",
                )
            block = details[comp_key]
            if not isinstance(block, dict):
                raise HTTPException(
                    status_code=400,
                    detail=f"교정할 수 없는 역량 데이터 구조입니다: {comp_key}",
                )
            for field in _apply_competency_edit(block, edit):
                changed_fields.append(f"details.{comp_key}.{field}")

    if body.blind_spot is not None:
        new_blind = body.blind_spot.strip()
        if scores.get("blind_spot") != new_blind:
            scores["blind_spot"] = new_blind
            changed_fields.append("blind_spot")

    new_summary = report.summary
    if body.summary is not None:
        new_summary = body.summary.strip()
        if new_summary != report.summary:
            changed_fields.append("summary")

    if not changed_fields:
        return {
            "success": True,
            "message": "변경된 내용이 없습니다.",
            "is_human_edited": report.is_human_edited,
            "changed_fields": [],
        }

    # 최초 교정에 한해 AI 원본 스냅샷 보존 (이후 교정에서는 덮어쓰지 않는다)
    if not report.is_human_edited and report.ai_original is None:
        report.ai_original = {
            "scores": copy.deepcopy(report.scores or {}),
            "summary": report.summary,
            "snapshot_at": datetime.now().isoformat(),
        }

    report.scores = scores
    report.summary = new_summary
    report.is_human_edited = True
    report.edited_at = datetime.now()
    report.edited_by = ctx.admin.email

    db.add(report)
    await db.commit()
    await db.refresh(report)

    logger.info(
        "리포트 교정: report_id=%s, by=%s, fields=%s",
        report_id, ctx.admin.email, changed_fields,
    )

    return {
        "success": True,
        "message": "교정 내용이 저장되었습니다.",
        "is_human_edited": report.is_human_edited,
        "edited_at": report.edited_at,
        "edited_by": report.edited_by,
        "changed_fields": changed_fields,
    }


# --------------------------------------------------------------------------
# [2] 결과 분석 요청 (POST) - 진단 종료 시 호출
# --------------------------------------------------------------------------
@router.post("/{session_id}/analyze", status_code=status.HTTP_201_CREATED)
async def analyze_session(
    session_id: str, 
    db: AsyncSession = Depends(get_db),
    llm: GeminiService = Depends(GeminiService)
):
    logger.info(f"🧠 리포트 분석 요청: {session_id}")
    
    try:
        session_uuid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID")

    session = await db.get(DiagnosisSession, session_uuid)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    # 기존 리포트가 있으면 스킵하지 않고 삭제 → 무조건 처음부터 재분석(Overwrite).
    existing_query = select(DiagnosisReport).where(DiagnosisReport.session_id == session_uuid)
    result = await db.execute(existing_query)
    existing_reports = result.scalars().all()
    if existing_reports:
        for _r in existing_reports:
            await db.delete(_r)
        await db.commit()
        logger.info(
            f"♻️ 기존 리포트 {len(existing_reports)}건 삭제 → 강제 재생성: {session_id}"
        )

    user = await db.get(Participant, session.user_id)
    user_name = user.name if user else "리더"

    history_query = select(ChatMessage).where(ChatMessage.session_id == session_uuid).order_by(ChatMessage.created_at.asc())
    history_res = await db.execute(history_query)
    messages = history_res.scalars().all()

    events_res = await db.execute(
        select(Event).where(Event.session_id == session_uuid).order_by(Event.sequence_num.asc())
    )
    events = events_res.scalars().all()

    formatted_history = [{"role": msg.role, "parts": msg.content} for msg in messages]

    # Map-Reduce: 역량별로 대화·사건을 결정론적으로 분리해 주입.
    #  - 통짜 컨텍스트 주입(절단/날조) 방지, 라포 사담(chapter=None) 제외.
    chapter_transcripts = _build_chapter_transcripts(messages, events)

    # 🔒 T1/T2: asked 원장을 영속 store(대화 제어와 동일 소스)에서 읽는다.
    asked_subs = _build_asked_subcompetencies(session.self_assessment_data or {})
    _asked_total = sum(len(v) for v in asked_subs.values())
    logger.info(
        "🧭 asked 원장(탐색률): %d / 26 | 대역량별 %s",
        _asked_total, {k: len(v) for k, v in asked_subs.items()},
    )

    # AI 분석 실행 (chapter_transcripts 제공 시 챕터별 Map 호출 → Reduce)
    analysis_result = await llm.generate_diagnosis_result(
        history=formatted_history,
        user_name=user_name,
        chapter_transcripts=chapter_transcripts,
        asked_subcompetencies=asked_subs,
    )
    if not analysis_result:
        raise HTTPException(status_code=500, detail="AI 분석 결과를 생성하지 못했습니다.")

    # item4: 분석이 광범위 실패(크레딧 소진/장애)로 오염됐으면 garbage 전량0
    #   리포트를 저장하지 않는다. 세션 status·원장은 건드리지 않아 재개 가능하게
    #   남긴다(부분 실행 결과가 정상 리포트로 굳는 것 방지).
    if (analysis_result.get("coverage") or {}).get("analysis_degraded"):
        _cov_d = analysis_result["coverage"]
        _errc = _cov_d.get("error_competencies")
        logger.error(
            "🚨 분석 오염(error-fallback %s/5) → 리포트 미저장, 세션 재개 가능 "
            "유지: %s", _errc, session_id)
        # B: 세션에 분석 상태 마커를 남긴다(마이그레이션 없이 JSONB) — 프론트가
        #   '분석 중(계속 대기)'과 '오염(재시도 필요)'을 구분할 수 있게.
        from sqlalchemy.orm.attributes import flag_modified as _fm_deg
        _sd = dict(session.self_assessment_data or {})
        _sd["last_analysis"] = {
            "status": "degraded",
            "error_competencies": _errc,
            "at": datetime.now().isoformat(),
        }
        session.self_assessment_data = _sd
        _fm_deg(session, "self_assessment_data")
        db.add(session)
        await db.commit()
        raise HTTPException(
            status_code=503,
            detail=("AI 분석이 일시적으로 실패했습니다(크레딧/장애 의심). "
                    "리포트를 저장하지 않았으며 이어서 재분석할 수 있습니다."))

    # total_score 는 파이프라인(scoring.overall_score)이 이미 계산해 준 값만 쓴다.
    #   H2: 과거 폴백 `sum(radar_chart.values())/len` 은 radar 값이 미측정(None)
    #   일 때 TypeError(500)를 냈다 — measured 대역량 0개 세션에서 재현됨.
    #   미측정이면 0.0 (프론트는 coverage.composite_shown 으로 종합 섹션을 게이트).
    total_score = analysis_result.get("total_score") or 0.0

    # 🚨 [수정] DB 스키마 충돌 방지를 위해 전체 JSON을 scores에 캡슐화하여 저장
    new_report = DiagnosisReport(
        id=uuid.uuid4(),
        session_id=session_uuid,
        user_id=session.user_id,
        coach_id=session.coach_id,
        summary=analysis_result.get("feedback_summary", "종합 피드백이 생성되지 않았습니다."),
        scores=analysis_result, # 모든 디테일(reasoning) 보존
        total_score=total_score,
        top_competency="-",
        bottom_competency="-",
        feedback="-",
        recommended_action="-",
        created_at=datetime.now()
    )
    
    db.add(new_report)

    # B: 리포트 정상 저장 → 이전 degraded 마커가 있으면 정리(stale 방지).
    _sd_ok = dict(session.self_assessment_data or {})
    if _sd_ok.get("last_analysis", {}).get("status") == "degraded":
        _sd_ok["last_analysis"] = {"status": "ok",
                                   "at": datetime.now().isoformat()}
        session.self_assessment_data = _sd_ok
        from sqlalchemy.orm.attributes import flag_modified as _fm_ok
        _fm_ok(session, "self_assessment_data")

    # 🚨 [버그 수정] 미완료 세션을 'completed' 로 덮어쓰는 데이터 오염 방지.
    #   기존엔 analyze 만 호출하면 5역량 미완주라도 무조건 completed 가 되어
    #   대시보드가 100% 완주로 오인했다. 실제 완료 역량 수로 분리 판정한다.
    _TOPIC_ORDER = ["조직관리", "성과관리", "사람관리", "일관리", "자기관리"]
    _ct = session.current_topic
    if session.status == "completed" or _ct == "Completed":
        _completed_count = 5
    elif _ct in _TOPIC_ORDER:
        _completed_count = _TOPIC_ORDER.index(_ct)  # 진행 중 = 그 앞까지 완료
    else:
        _completed_count = 0  # General/라포 등 첫 역량 진입 전

    _cov = (analysis_result or {}).get("coverage") or {}
    session.status = resolve_completion_status(_completed_count)
    if _completed_count >= 5:
        # V-6(1): 완주 세션은 전부 'completed'. '종합 섹션 유무'는 상태가 아니라
        #   커버리지 플래그(composite_shown = measured_total ≥ 임계)로 내린다.
        #   completed_insufficient(이분 모드) 제거 — 경계 뒤집힘 소멸.
        session.current_topic = "Completed"
        logger.info(
            "🧭 완주 세션 상태: completed (측정 %s/%s, composite_shown=%s)",
            _cov.get("measured_total", _cov.get("measured")),
            _cov.get("total"), _cov.get("composite_shown"),
        )
    else:
        # V-6/조정3: 미완주는 'incomplete'(신규 상태)를 만들지 않는다 — 이탈
        #   신호가 없으면 '아직 진행 중'인 재개 대상이므로 in_progress 로 남긴다.
        #   current_topic(진행 위치)은 그대로 둬 진행률이 실제 위치를 반영한다.
        session.status = "in_progress"
        logger.warning(
            "⚠️ 미완주 세션 analyze: %d/5 역량만 완료 → status=in_progress "
            "(재개 대상, current_topic=%s 유지)", _completed_count, _ct,
        )

    db.add(session)
    await db.commit()

    logger.info(
        "✅ 리포트 생성 완료: %s (완료역량 %d/5, status=%s)",
        new_report.id, _completed_count, session.status,
    )
    return {
        "status": "success",
        "message": "Analysis completed",
        "report_id": str(new_report.id),
        "completed_competencies": _completed_count,
        "session_status": session.status,
    }