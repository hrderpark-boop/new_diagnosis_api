"""4(c) 복원: abandoned → in_progress (상태 전이 표의 유일한 복원 경로).

- 복원 후 재개되는가(in_progress), 복원 시 다른 진행 세션이 보관되는가(abandoned),
  두 번 복원해도 꼬이지 않는가(멱등), completed/aborted 는 복원 불가.
- 라우트: POST /diagnoses/restore(참가자), POST /admin/sessions/{id}/restore(require_admin).
- 원장·메시지·이벤트 무변경(상태·updated_at 만 바뀜).
- docs/session_state_transitions.md 가 존재하고 복원 전이를 명시한다.
"""
import inspect
import os
import uuid
from types import SimpleNamespace as NS

from diag_project.routes import admin as A
from diag_project.routes import diagnoses as D


def _sess(status, **kw):
    return NS(id=uuid.uuid4(), status=status, updated_at=None,
              self_assessment_data={"asked_subs": {"x": ["a"]}}, **kw)


def test_restore_abandoned_resumes_and_parks_other_active():
    old = _sess("abandoned")
    new_empty = _sess("in_progress")
    done = _sess("completed")
    r = D.apply_restore(old, [new_empty, done, old])
    assert r == {"restored": True, "already_in_progress": False, "abandoned_others": 1}
    assert old.status == "in_progress" and old.updated_at is not None
    assert new_empty.status == "abandoned"
    assert done.status == "completed"                       # 완료 세션은 건드리지 않음
    assert old.self_assessment_data == {"asked_subs": {"x": ["a"]}}   # 원장 무변경


def test_restore_twice_is_idempotent():
    old = _sess("abandoned")
    other = _sess("paused")
    D.apply_restore(old, [other])
    r2 = D.apply_restore(old, [other])
    assert r2["already_in_progress"] is True and r2["abandoned_others"] == 0
    assert old.status == "in_progress" and other.status == "abandoned"


def test_restore_rejects_terminal_states():
    import pytest
    for st in ("completed", "aborted"):
        with pytest.raises(ValueError):
            D.apply_restore(_sess(st), [])


def test_restore_paused_and_disengaged_become_in_progress():
    for st in ("paused", "aborted_disengaged"):
        s = _sess(st)
        assert D.apply_restore(s, [])["restored"] and s.status == "in_progress"


def test_restore_routes_exist_and_admin_route_requires_admin():
    assert "/restore" in {getattr(r, "path", "") for r in D.router.routes}
    assert "/admin/sessions/{session_id}/restore" in {getattr(r, "path", "") for r in A.router.routes}
    src = inspect.getsource(A.admin_restore_session)
    assert "get_current_admin" in src and "assert_can_access_company" in src
    assert "restore_session_by_id" in src            # 공용 처리 공유(전이 경로 단일화)


def test_abandon_returns_sessions_for_immediate_undo():
    src = inspect.getsource(D.abandon_resumable_sessions)
    assert '"sessions"' in src and "coach_name" in src


def test_transition_doc_exists_and_lists_restore_path():
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "docs", "session_state_transitions.md")
    assert os.path.exists(path)
    doc = open(path, encoding="utf-8").read()
    assert "abandoned → in_progress" in doc and "/restore" in doc
    assert "in_progress ⇄ paused" in doc or "paused → in_progress" in doc
    # 코드 주석의 표와 문서가 같은 경로를 가리킨다
    assert "docs/session_state_transitions.md" in inspect.getsource(D)
