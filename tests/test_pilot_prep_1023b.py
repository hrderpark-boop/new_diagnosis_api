"""(2026-10-23 파일럿 전, 두 번째 묶음) 자가진단 5개 값 강제(400) · 하위역량 이름 불일치 로그 · run 별 게이트 판정 원장(gate_runs)."""
import logging
import os
import sys
import uuid

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.llm_service import _normalize_sub_assessments  # noqa: E402
from diag_project.services.outer_merge import gate_run_summary, merge_competency  # noqa: E402

ELLA = uuid.UUID("00000000-0000-0000-0000-000000000011")


def test_normalize_logs_unmatched_name(caplog):
    subs = ["전략적 사고", "비전 제시 및 공유"]
    with caplog.at_level(logging.WARNING, logger="diag_project.llm_service"):
        out = _normalize_sub_assessments([{"name": "비전 제시", "measured": True, "level": 3, "evidence": ["a"]},
                                          {"name": "없는 이름", "measured": True, "level": 2, "evidence": ["b"]}], subs)
    assert set(out) == {"비전 제시 및 공유"}                 # 부분 일치(공백·괄호 무시)는 맞추고
    assert any("이름 불일치" in r.message and "없는 이름" in r.message for r in caplog.records)   # 못 맞춘 건 로그


def _run(measured, level, gate):
    return {"sub_ledger": {"전략적 사고": {"measured": measured, "level": level, "evidence": ["q"] if measured else [],
                                        "gate_status": "passed" if measured else "failed", "asked": True, "claimed_level": 3}},
            "level_gate": {"전략적 사고": gate},
            "score": 2.0, "behavior_score": 2.0}


def test_gate_runs_recorded_per_run_for_weak_sub():
    runs = [_run(True, 1, {"verified_level": 1, "category": "구체행동", "reason": "Lv.3 미달", "dropped": False, "pending": False}),
            _run(False, None, {"verified_level": None, "category": "일반화", "reason": "평소 방식 서술", "dropped": True, "pending": False}),
            _run(False, None, {"verified_level": None, "category": "일반화", "reason": "시점·상황 없음", "dropped": True, "pending": False})]
    merged = merge_competency(runs, "organization_management", 3)
    row = merged["sub_ledger"]["전략적 사고"]
    assert row["stability"] == "weak" and row["measured"] is False and row["gate_status"] == "failed"
    gr = row["gate_runs"]
    assert len(gr) == 3 and gr[0]["verified_level"] == 1 and gr[0]["measured"] is True
    assert gr[1]["dropped"] is True and gr[1]["category"] == "일반화" and gr[1]["reason"] == "평소 방식 서술"
    assert gr[2]["claimed_level"] == 3
    # 게이트가 안 돈 run(근거 후보 없음)
    assert gate_run_summary({"sub_ledger": {}, "level_gate": {}}, "전략적 사고")["verified_level"] is None


def test_self_eval_requires_all_five_scores(client):
    from diag_project.database import async_session
    from diag_project.models.diagnosis_session import DiagnosisSession
    from diag_project.models.participant import Participant

    async def _mk():
        async with async_session() as db:
            p = Participant(email=f"se-{uuid.uuid4().hex[:8]}@test.local", name="자가진단")
            db.add(p); await db.flush()
            s = DiagnosisSession(user_id=p.id, coach_id=ELLA, status="in_progress")
            db.add(s); await db.commit()
            return str(s.id)
    sid = client.portal.call(_mk)
    r = client.patch(f"/api/v1/sessions/{sid}/self-eval", json={"scores": {"organization_management": 3, "people_management": 4}})
    assert r.status_code == 400 and "누락" in r.json()["detail"]
    r2 = client.patch(f"/api/v1/sessions/{sid}/self-eval", json={"scores": {}})
    assert r2.status_code == 400
    full = {k: 3.5 for k in ("organization_management", "performance_management", "people_management", "work_management", "self_management")}
    r3 = client.patch(f"/api/v1/sessions/{sid}/self-eval", json={"scores": full})
    assert r3.status_code == 200 and r3.json()["self_assessment"]["self_average"] == 3.5
    assert client.get(f"/api/v1/sessions/{sid}/self-eval").json()["submitted"] is True
