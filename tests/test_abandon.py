"""2단계 '새로 시작': 기존 세션은 abandoned 로 '보관'(삭제 아님), 재개 대상 아님.

- mark_abandoned: 재개 가능한 세션만 abandoned 로, completed/aborted 등은 그대로.
- RESUMABLE_STATUSES 에 abandoned 없음 → /active·/start 가 재개하지 않음.
- status_after_analyze 는 abandoned 를 덮어쓰지 않음(미완주 analyze 부활 방지).
- DiagnosisStartRequest.force_new 기본 False, /start 는 force_new 면 Case A(재개) 전에 보관.
- submit_message 가드: abandoned 세션은 상태 머신에 재진입하지 않음.
"""
import inspect
from types import SimpleNamespace as NS

from diag_project.routes import diagnoses as D
from diag_project.routes.reports import status_after_analyze


def test_mark_abandoned_only_resumable():
    ss = [NS(status="in_progress"), NS(status="paused"), NS(status="aborted_disengaged"),
          NS(status="completed"), NS(status="aborted"), NS(status="abandoned")]
    n = D.mark_abandoned(ss)
    assert n == 3
    assert [s.status for s in ss] == [
        "abandoned", "abandoned", "abandoned", "completed", "aborted", "abandoned"]
    assert all(hasattr(s, "updated_at") for s in ss[:3])
    assert D.mark_abandoned([]) == 0 and D.mark_abandoned(None) == 0


def test_abandoned_is_not_resumable():
    assert D.ABANDONED == "abandoned"
    assert D.ABANDONED not in D.RESUMABLE_STATUSES


def test_analyze_preserves_abandoned():
    for done in (0, 2, 4):
        assert status_after_analyze("abandoned", done) == "abandoned"
    assert status_after_analyze("abandoned", 5) == "completed"


def test_start_request_force_new_default_false():
    import uuid
    req = D.DiagnosisStartRequest(coach_id=uuid.uuid4(), participant_id=uuid.uuid4(),
                                  template_id=uuid.uuid4())
    assert req.force_new is False


def test_start_handles_force_new_before_resume():
    src = inspect.getsource(D.start_diagnosis)
    i_force = src.index("request.force_new")
    i_resume = src.index("# [Case A] 진행 중인 세션이 있다")
    assert i_force < i_resume
    assert "mark_abandoned(" in src[i_force:i_resume]


def test_abandon_endpoint_exists_and_guard_blocks_abandoned():
    routes = {getattr(r, "path", "") for r in D.router.routes}
    assert "/abandon" in routes
    src = inspect.getsource(D._submit_message_phase3a)
    assert 'in ("aborted", ABANDONED)' in src
