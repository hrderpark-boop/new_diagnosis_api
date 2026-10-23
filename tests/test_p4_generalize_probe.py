"""(2026-10-23, 4번) 대화 2건 — 일반화 답변 → 구체 사례 탐침 1회(generalize_probe) · 챕터 전환 다리 중복 금지 · Claude refusal 재시도."""
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.services import traversal as T  # noqa: E402
from diag_project.services.avoidance_detector import is_generalized_answer as G  # noqa: E402
from diag_project.services.intro_messages import PERSONA_LINES, persona_line  # noqa: E402
from diag_project.services.output_guard import is_question, strip_transition_sentences  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_generalized_answer_detection():
    # cbd5210b 운영 발화 — 게이트가 '일반화'로 떨어뜨린 두 건
    assert G("일정이 빠듯한 프로젝트일수록 전체 일정을 무작정 세우기보다, 반드시 달성해야 하는 최소한의 핵심 목표(MVP)부터 명확히 정의했습니다.")
    assert G("예상치 못한 변수가 발생했을 때는 전체 수정을 피하고, 당장 영향을 받는 핵심 과제와 부차적 과제를 즉시 분리했습니다.")
    assert G("보통 제가 먼저 정리해서 공유하는 편입니다.")
    # 시점이 있으면 일반화가 아니다
    assert not G("지난달 LMS 교체 때는 벤더 일정이 두 번 밀려서 내부 테스트를 먼저 돌렸어요.")
    assert not G("올해 초에 교육 만족도 4.5 목표가 내려왔을 때 과정별로 쪼갰습니다.")
    assert not G("3월에 신청률이 떨어졌을 때는 수강생 10명에게 전화로 물어봤어요.")
    # 습관 표지가 없으면 일반화가 아니다(짧은 단답·구체 사례)
    assert not G("팀원들이 불평했어요.") and not G("") and not G(None)


def test_generalize_ledger_once_per_target():
    st = {}
    assert not T.generalize_probed(st, "organization_management", "전략적 사고")
    st = T.mark_generalize_probed(st, "organization_management", "전략적 사고")
    assert T.generalize_probed(st, "organization_management", "전략적 사고")
    assert not T.generalize_probed(st, "organization_management", "혁신적 사고")
    assert T.mark_generalize_probed(st, "organization_management", None) == st


def test_persona_generalize_lines_six_variants():
    lines = {p: d["generalize"] for p, d in PERSONA_LINES.items()}
    assert len(lines) == 6 and len(set(lines.values())) == 6
    for p, q in lines.items():
        assert is_question(q) and "최근" in q and ("언제" in q), (p, q)
    # 한 문장이어야 한다 — 두 문장이면 8-o/되받기 상한이 앞 문장("그중 가장 최근 일 하나만요.")을 지운다(g4b 재생 10턴에서 확인)
    from diag_project.services.output_guard import split_sentences
    for p, q in lines.items():
        assert len([x for x in split_sentences(q) if x.strip()]) == 1, (p, q)
    assert persona_line("Ella", "generalize") == "그중 가장 최근 일 하나만요 — 어떤 일이었고 언제쯤이었어요?"
    # 가드가 자르지 않는다: 되받기 1문장 + 이 줄 → 한 턴 한 질문·되받기 상한(Jessica 1)을 거쳐도 그대로
    from diag_project.services.output_guard import keep_last_question, cap_leads_persona
    t = "신중하게 가시는 편이군요. " + persona_line("Ella", "generalize")
    assert keep_last_question(t)[0] == t and cap_leads_persona(t, 1, "큰 변화는 늘 조심스럽게 가는 편이에요")[0] == t
    assert persona_line("Michael", "generalize").startswith("좋습니다,") and persona_line("Jessica", "generalize").endswith("습니까?")


def test_transition_variants_stripped_so_fixed_bridge_is_not_duplicated():
    body = "HR 진단 플랫폼 도입 때 파일럿으로 수치를 확인하셨다고 들었습니다."
    for tail in ("이제 '성과관리'로 이어가 보겠습니다.", "이제 성과관리 영역으로 넘어가 볼게요.", "다음은 '성과관리'입니다.",
                 "그럼 성과관리로 넘어가 보죠.", "'성과관리'로 들어가 볼까요."):
        out, n = strip_transition_sentences(f"{body} {tail}")
        assert n == 1 and out == body, tail
    # 전환 문장이 없으면 그대로
    assert strip_transition_sentences(body) == (body, 0)


def test_route_and_prompt_wiring():
    src = open(os.path.join(ROOT, "diag_project", "routes", "diagnoses.py"), encoding="utf-8").read()
    assert 'state["force_generalize_probe"] = _force_g' in src and "_tot_g == 2" in src
    assert '"generalize")]).strip()' in src and '"generalize_probe": int(_tm.get("generalize") or 0)' in src
    assert "mark_generalize_probed as _mgp_g" in src
    l3 = open(os.path.join(ROOT, "diag_project", "prompts", "phase3a", "layer3_state.py"), encoding="utf-8").read()
    assert "[🧭 일반화 답변 — 시스템 계산, 반드시 준수]" in l3
    # Claude refusal 재시도
    from diag_project import llm_service as L
    gsrc = inspect.getsource(L.GeminiService._generate_claude)
    assert 'stop_reason", None) == "refusal"' in gsrc and "_ref_attempt < 2" in gsrc
