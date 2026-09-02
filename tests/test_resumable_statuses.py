"""H3/M22: 세션 상태 모델 — 재개 대상 집합과 analyze 후 상태 전이.

- RESUMABLE_STATUSES: /active·/start·submit_message 1-b 가 보는 단일 정의.
  aborted_disengaged(A-4 참여 이탈 중단)는 '원장 보존·재개 가능'이므로 포함,
  aborted(3-Strike)는 재개 불가이므로 제외.
- status_after_analyze: 미완주 analyze 가 aborted/aborted_disengaged/paused 를
  in_progress 로 '부활'시키지 않는다.
"""
from diag_project.routes.diagnoses import RESUMABLE_STATUSES
from diag_project.routes.reports import status_after_analyze


def test_resumable_includes_disengaged_but_not_aborted():
    assert "in_progress" in RESUMABLE_STATUSES
    assert "paused" in RESUMABLE_STATUSES
    assert "aborted_disengaged" in RESUMABLE_STATUSES
    assert "aborted" not in RESUMABLE_STATUSES
    assert "completed" not in RESUMABLE_STATUSES


def test_analyze_completed_when_all_five_done():
    for prev in ("in_progress", "paused", "aborted_disengaged", "aborted", None):
        assert status_after_analyze(prev, 5) == "completed"


def test_analyze_preserves_terminal_and_paused_when_incomplete():
    for prev in ("aborted", "aborted_disengaged", "paused"):
        for done in (0, 2, 4):
            assert status_after_analyze(prev, done) == prev, (prev, done)


def test_analyze_incomplete_others_become_in_progress():
    for prev in ("in_progress", "completed", None, "weird"):
        assert status_after_analyze(prev, 3) == "in_progress"
