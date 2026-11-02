"""(2026-11-02 핫픽스) 게이트의 일반화 판정은 '습관 표지 + 시점 없음' 원칙만 — 시점 표지 없는 한 문장 근거를 탈락시키지 않는다.
10/29 P1-3 에서 대화 탐침용 is_generalized_answer 를 넓혔는데 level_gate.split_generalized 가 그것을 써서 근거 측정이 25 → 7~10 으로 무너졌다."""
from diag_project.services.level_gate import split_generalized
from diag_project.services.avoidance_detector import is_generalized_evidence, is_generalized_answer


def test_gate_generalized_rule_is_the_original_narrow_one():
    ev = ["팀원들에게 변경 이유와 결정 사항을 바로 공유했어요.", "보통 제가 먼저 정리해서 공유하는 편입니다.", "지난달에 일정을 다시 잡았습니다."]
    keep, gen = split_generalized(ev)
    assert keep == [ev[0], ev[2]] and gen == [ev[1]]
    assert not is_generalized_evidence(ev[0]) and is_generalized_answer(ev[0])
