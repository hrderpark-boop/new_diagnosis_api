"""(2026-10-23 E-2·E-3) 게이트 사유 검증(결락 → n-1) · 일반화 결정론 전처리."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.services import level_gate as LG  # noqa: E402


def test_concession_fix_downgrades_when_lack_is_stated_for_awarded_level():
    # cbd5210b D·E run 에서 실제로 나온 사유들 — 결락을 적고 Lv.3 을 줬다 → 2
    for reason in ("임시 조치 후 근본 원인을 추적해 시스템을 보완함으로써 재발 방지를 실행했다. 효과 측정이나 문서화는 없지만 대안 탐색 수준(Lv.2)보다 Lv.3 서술에 더 잘 맞는다.",
                   "재발 방지 중심의 Lv.3에 부합. 효과 측정·문서화 근거는 부족하나 Lv.2의 원인 파악·대안 비교보다 Lv.3가 더 맞음.",
                   "원인 분석과 선행지표 근거는 약하지만 단순 점검·공유(Lv.2)보다 지표 설정·개선 활동(Lv.3)에 가깝다.",
                   "Lv.3 '도전적 과업을 권한·책임과 함께 위임'에 부합하며, 사후 피드백은 확인되지 않지만 Lv.2 서술보다 Lv.3가 더 맞다.",
                   "Lv.3의 '구성원 참여 유도'에 부합하나 세부 실행계획·일정 수립 근거는 없음. 그래도 목표 공유 중심의 Lv.2보다 Lv.3 이 맞다."):
        v, fixed, note = LG.concession_fix(3, reason)
        assert (v, fixed) == (2, True), (reason, v, note)


def test_concession_fix_keeps_level_when_lack_is_about_higher_level():
    for reason in ("Lv.3의 장애 극복·우선순위 조정에 부합하며 Lv.4 수준의 다자 조율이나 도구 활용은 보이지 않지만 Lv.3 이다.",
                   "주간 회의를 재설계했으므로 Lv.3에 부합하며, 조직 차원의 제도화(Lv.4) 근거는 없음.",
                   "도전 과제를 통한 내재적 동기 강화(Lv.3)에 부합하며 제도 설계는 없어 Lv.4는 아님.",
                   "도입 목적을 공유하고 파일럿으로 동기를 부여한 행동은 Lv.2(공유·동기부여)에 부합한다."):
        v, fixed, _ = LG.concession_fix(3 if "Lv.3" in reason else 2, reason)
        assert not fixed, reason
    # n-1 이 Lv.1 이면 2 에 둔다(규칙 4)
    assert LG.concession_fix(2, "조직 목표 연결은 없지만 중장기 흐름을 고려해 Lv.2 가 맞다.") == (2, False, "")
    assert LG.concession_fix(None, "x") == (None, False, "") and LG.concession_fix(3, "") == (3, False, "")


def test_gate_prompt_e2_rules():
    p = LG._build_gate_prompt([{"sub_name": "문제해결", "evidence": ["e"], "claimed_level": 3, "ref": LG.level_reference("performance_management", "문제해결")}])
    assert "Lv.n 요건이 일부라도" in p and "결락이면 Lv.n-1" in p and "사유에 결락을 적었으면 레벨은 n-1" in p
    assert "n-1 이 Lv.1 이면" in p and "아니면 2 다" in p
    assert LG.GATE_PROMPT_VERSION_CLAUDE == "2026-10-23.v3" and LG.GATE_PROMPT_VERSION == "2026-08-17.v1"


def test_split_generalized_matches_probe_dictionary():
    ev = ["일정이 빠듯한 프로젝트일수록 전체 일정을 무작정 세우기보다, 반드시 달성해야 하는 최소한의 핵심 목표(MVP)부터 명확히 정의했습니다.",
          "예상치 못한 변수가 발생했을 때는 전체 수정을 피하고, 당장 영향을 받는 '핵심 과제와 부차적 과제'를 즉시 분리했습니다.",
          "지난달 LMS 교체 때는 벤더 일정이 두 번 밀려서 내부 테스트를 먼저 돌렸어요."]
    keep, gen = LG.split_generalized(ev)
    assert len(gen) == 2 and keep == [ev[2]]
    v = LG.deterministic_generalization_verdict(gen)
    assert v["dropped"] and v["category"] == "일반화" and v["deterministic"] and v["verified_level"] is None


def test_pipeline_wiring_e3():
    import inspect
    from diag_project import llm_service as L
    src = inspect.getsource(L.GeminiService._run_level_gate)
    assert "split_generalized" in src and "deterministic_generalization_verdict" in src and "gate.update(await gate_verify_levels" in src
    src2 = inspect.getsource(L.GeminiService._reselect_dropped_evidence)
    assert "_split_gen(new_ev)" in src2
