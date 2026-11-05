"""P0-3 산식 단위 테스트 — 순수 함수 계층 정합성.

케이스: 상한 초과 입력, 미측정 전량, 미측정 일부, 가점 최대치, ZeroDiv 방어.
실행: python -m pytest tests/test_scoring.py -q  (또는 직접 실행)
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.services.scoring import (  # noqa: E402
    SubLedger,
    clamp,
    is_measured,
    competency_behavior_score,
    competency_final_score,
    overall_score,
    coverage,
    competency_is_reference,
)


def test_is_measured_ghost_prevention():
    # T1 재발 방지: asked 와 evidence 는 독립. AND 게이트 강제.
    assert is_measured(asked=False, evidence_count=3) is False  # 유령 차단
    assert is_measured(asked=True, evidence_count=0) is False   # 근거 미확보
    assert is_measured(asked=True, evidence_count=1) is True    # 정상 측정
    # LLM 이 measured=true 로 응답해도 asked=False 면 코드가 False 로 덮어씀
    llm_said_measured = True  # noqa: F841 (의미 명시용)
    assert is_measured(asked=False, evidence_count=2) is False


def test_sub_ledger_uses_is_measured():
    # asked=False, evidence 3 → 유령 차단
    s = SubLedger("x", asked=False, evidence_utterances=["a", "b", "c"], level=3)
    assert s.measured is False and s.score is None


def test_sub_ledger_measured_and_clamp():
    # 미질문 → 미측정 → None
    s = SubLedger("전략적 사고", asked=False, evidence_utterances=[], level=3)
    assert s.measured is False and s.score is None
    # 질문했으나 근거 0 → 미측정
    s = SubLedger("변화관리", asked=True, evidence_utterances=[], level=2)
    assert s.measured is False and s.score is None
    # 측정됨 → 레벨 1~4 클램프
    s = SubLedger("비전", asked=True, evidence_utterances=["발화"], level=3)
    assert s.measured is True and s.score == 3.0


def test_sub_score_hard_clamp_upper():
    # 상한 초과 레벨(잘못된 5) → 4.0 하드 클램프
    s = SubLedger("x", asked=True, evidence_utterances=["e"], level=5)
    assert s.score == 4.0


def test_competency_behavior_mean_and_zero_div():
    # 미측정 전량 → None (ZeroDivision 방어)
    assert competency_behavior_score([None, None, None]) is None
    # 미측정 일부 → measured 만 평균
    assert competency_behavior_score([2.0, None, 4.0]) == 3.0
    assert competency_behavior_score([1.0, 2.0]) == 1.5


def test_competency_final_gates_and_clamp():
    """(2026-11-05 P4-7) 최종점수 = 행동지표 + STAR 가점. 확신도 인자는 받되 점수에 넣지 않는다."""
    # 미측정 → None
    assert competency_final_score(None, 0.5, 0.5) is None
    # STAR 가점 최대치 반영 — 확신도는 더하지 않는다(4.0 + 0.5)
    assert competency_final_score(4.0, 0.5, 0.5) == 4.5
    # STAR 가점은 0.5 로 클램프, 확신도 무시
    assert competency_final_score(4.0, 0.9, 0.9) == 4.5
    # 하한 1.0 — 음의 확신도가 점수를 깎지 않는다
    assert competency_final_score(1.0, 0.0, -0.9) == 1.0
    # 운영 Michael 세션(11/5) 성과관리: 2.0 + 0.3 (+0.2 확신도 제거) = 2.3
    assert competency_final_score(2.0, 0.3, 0.2) == 2.3
    assert competency_final_score(2.5, 0.2, 0.1) == 2.7


def test_confidence_display_is_stars_only():
    from diag_project.services.scoring import confidence_display, confidence_stars
    assert confidence_stars(0.3) == 3 and confidence_stars(0.2) == 2 and confidence_stars(0.0) == 2 and confidence_stars(-0.1) == 1
    d = confidence_display(0.4)
    assert d == {"confidence_stars": 3, "confidence_label": "AI 판정 확신도 ★★★"}
    assert confidence_display(None)["confidence_label"] == "AI 판정 확신도 ★★☆"


def test_rescore_without_confidence_recomputes_saved_report():
    """저장된 리포트(확신도 포함 점수)를 읽을 때 행동지표+STAR 로 다시 계산한다 — 운영 Michael 세션 5대역량 전후."""
    from diag_project.services.report_ledger import rescore_without_confidence
    saved = {
        "organization_management": {"score": 2.9, "measured_count": 4, "score_breakdown": {"rubric_base": 2.5, "star_depth_bonus": 0.4, "confidence_adj": 0.0, "final": 2.9}},
        "performance_management": {"score": 2.5, "measured_count": 5, "score_breakdown": {"rubric_base": 2.0, "star_depth_bonus": 0.3, "confidence_adj": 0.2, "final": 2.5}},
        "people_management": {"score": 2.9, "measured_count": 9, "score_breakdown": {"rubric_base": 2.3, "star_depth_bonus": 0.4, "confidence_adj": 0.2, "final": 2.9}},
        "work_management": {"score": 3.1, "measured_count": 5, "score_breakdown": {"rubric_base": 2.6, "star_depth_bonus": 0.3, "confidence_adj": 0.2, "final": 3.1}},
        "self_management": {"score": 2.7, "measured_count": 3, "score_breakdown": {"rubric_base": 2.3, "star_depth_bonus": 0.3, "confidence_adj": 0.1, "final": 2.7}},
    }
    rs = rescore_without_confidence(saved)
    assert rs["changed"] and rs["radar"] == {"organization_management": 2.9, "performance_management": 2.3, "people_management": 2.7,
                                              "work_management": 2.9, "self_management": 2.6}
    assert rs["total_score"] == 2.7                                   # 2.8 → 2.7
    assert saved["work_management"]["score"] == 2.9 and saved["work_management"]["score_breakdown"]["final"] == 2.9
    assert saved["work_management"]["score_breakdown"]["confidence_stars"] == 2
    # 미측정 대역량(rubric_base 없음)은 건너뛴다
    rs2 = rescore_without_confidence({"x": {"score": None, "score_breakdown": {"rubric_base": None}}})
    assert rs2["changed"] is False and rs2["total_score"] is None


def test_overall_score():
    assert overall_score([None, None]) is None
    assert overall_score([2.0, None, 4.0]) == 3.0


def test_coverage_and_reference():
    c = coverage(9, 26)
    assert c["label"] == "측정 9 / 26" and c["is_low_confidence"] is True
    c2 = coverage(12, 26)
    assert c2["is_low_confidence"] is False  # 12/26 ≈ 0.46 >= 0.40
    # 대역량 50% 미만 → 참고치
    assert competency_is_reference(1, 4) is True    # 25%
    assert competency_is_reference(3, 5) is False   # 60%
    assert competency_is_reference(0, 3) is True


def _run():
    fns = [v for k, v in globals().items() if k.startswith("test_")]
    p = f = 0
    for fn in fns:
        try:
            fn()
            print(f"  [PASS] {fn.__name__}")
            p += 1
        except AssertionError as e:
            print(f"  [FAIL] {fn.__name__}: {e}")
            f += 1
    print(f"\n{p} PASS / {f} FAIL")
    return f


if __name__ == "__main__":
    sys.exit(1 if _run() else 0)
