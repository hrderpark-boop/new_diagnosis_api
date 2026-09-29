"""item6: 리포트 분석 진행 상태(analysis_progress) 단위 테스트. 실행: pytest."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.services import analysis_progress as AP  # noqa: E402

KEYS = ["self_management", "work_management", "people_management",
        "performance_management", "organization_management"]


def test_unknown_session_is_none():
    assert AP.get("no-such-session") is None
    assert AP.is_running("no-such-session") is False


def test_start_snapshot_shape():
    p = AP.start("s-shape", KEYS, 3)
    snap = AP.get("s-shape")
    for k in ("stage", "done", "total", "label", "started_at", "elapsed_s"):
        assert k in snap
    assert snap["stage"] == "queued" and snap["total"] == 5
    assert not any(k.startswith("_") for k in snap)   # 내부 필드 비노출
    assert AP.is_running("s-shape")
    p.stage("done")


def test_unit_counting_competency_and_outer():
    p = AP.start("s-count", KEYS, 3)
    p.start_analyze()
    assert AP.get("s-count")["label"] == "5개 영역 분석 중 0/5 · 교차검증 0/3"
    # 한 대역량이 outer 3회를 모두 마쳐야 영역 1개 완료
    p.unit_done("self_management", 0)
    p.unit_done("self_management", 1)
    assert AP.get("s-count")["done"] == 0
    p.unit_done("self_management", 2)
    snap = AP.get("s-count")
    assert snap["stage"] == "analyze" and snap["done"] == 1
    assert snap["label"].startswith("5개 영역 분석 중 1/5")
    # 같은 단위 중복 보고는 세지 않는다
    p.unit_done("self_management", 2)
    assert AP.get("s-count")["done"] == 1
    # outer run 0 이 5개 대역량을 다 마치면 교차검증 1/3
    for k in KEYS[1:]:
        p.unit_done(k, 0)
    snap = AP.get("s-count")
    assert snap["outer_done"] == 1 and snap["done"] == 1
    for k in KEYS:
        for o in range(3):
            p.unit_done(k, o)
    snap = AP.get("s-count")
    assert snap["done"] == 5 and snap["outer_done"] == 3
    assert snap["label"] == "5개 영역 분석 중 5/5 · 교차검증 3/3"


def test_single_outer_label_has_no_crosscheck():
    p = AP.start("s-one", KEYS, 1)
    p.start_analyze()
    p.unit_done("work_management", 0)
    assert AP.get("s-one")["label"] == "5개 영역 분석 중 1/5"


def test_stages_and_terminal_states():
    p = AP.start("s-stage", KEYS, 3)
    p.stage("summary")
    assert AP.get("s-stage")["label"] == "종합 정리 중"
    p.stage("recommend")
    assert AP.get("s-stage")["label"] == "추천 생성 중"
    assert AP.is_running("s-stage")
    p.stage("done")
    assert not AP.is_running("s-stage")
    e1 = AP.get("s-stage")["elapsed_s"]
    assert AP.get("s-stage")["elapsed_s"] == e1     # 종료 후 경과 시간 고정


def test_fail_records_error_and_allows_restart():
    p = AP.start("s-fail", KEYS, 3)
    p.fail("RuntimeError: boom")
    snap = AP.get("s-fail")
    assert snap["stage"] == "failed" and "boom" in snap["error"]
    assert not AP.is_running("s-fail")
    AP.start("s-fail", KEYS, 3)                      # 재시도 = 새 상태
    assert AP.get("s-fail")["stage"] == "queued"
    assert AP.get("s-fail")["error"] is None
