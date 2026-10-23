"""(2026-10-23, 5번 P3) 레벨 사다리 탐침 — 사전 52개 · 사다리 선택 · 원장 · 라우트/지시 배선(LLM·DB 없음)."""
import inspect
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.data.competencies import COMPETENCY_FRAMEWORK as F  # noqa: E402
from diag_project.data.ladder_questions import LADDER_QUESTIONS, ladder_question  # noqa: E402
from diag_project.services import traversal as T  # noqa: E402
from diag_project.services.output_guard import is_question, find_sub_names  # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ALL_NAMES = [v["name"] for c in F.values() for v in (c.get("indicators") or {}).values()]


def test_dictionary_covers_26_subs_with_one_question_each():
    keys = {k for ch, v in F.items() if ch != "supplementary" for k in v["indicators"]}
    assert set(LADDER_QUESTIONS) == keys
    for k, q in LADDER_QUESTIONS.items():
        for step in ("2_3", "3_4"):
            t = q[step]
            assert t.count("?") == 1 and is_question(t), (k, step, t)
            assert not find_sub_names(t, ALL_NAMES), (k, step, "역량명 노출")
            assert not any(w in t for w in ("루브릭", "레벨", "Lv", "역량")), (k, step)
    assert LADDER_QUESTIONS["delegation"]["2_3"] == "결과까지 책임지게 맡기신 일이 있었어요?"
    assert LADDER_QUESTIONS["centrality"]["2_3"] == "주변 압박에도 처음 세운 기준을 그대로 지키신 일이 있었어요?"
    assert LADDER_QUESTIONS["change_management"]["2_3"] == "반발을 미리 예상하고 준비해 두신 게 있었어요?"
    assert LADDER_QUESTIONS["kpi_management"]["2_3"] == "그 지표를 보고 실제로 뭘 고치셨어요?"


def test_ladder_question_selection():
    assert ladder_question("kpi_management", 1)[1] == "2_3" and ladder_question("kpi_management", 2)[1] == "2_3"   # Lv.1 → 2_3 은 명시 규칙(사전에 1→2 없음)
    assert ladder_question("kpi_management", 3)[1] == "3_4"
    assert ladder_question("kpi_management", 4) == (None, None) and ladder_question("없음", 2) == (None, None)
    assert ladder_question("kpi_management", None) == (None, None)


def test_ladder_ledger_once_per_target():
    st = {}
    assert not T.ladder_probed(st, "organization_management", "전략적 사고")
    st = T.mark_ladder_probed(st, "organization_management", "전략적 사고")
    assert T.ladder_probed(st, "organization_management", "전략적 사고") and not T.ladder_probed(st, "organization_management", "혁신적 사고")


def test_route_and_prompt_wiring():
    src = open(os.path.join(ROOT, "diag_project", "routes", "diagnoses.py"), encoding="utf-8").read()
    # 추가가 아니라 교체: S-A-R 완비 블록 안에서만 사다리를 만들고, 그 턴의 질문을 사전 질문으로 바꾼다
    assert 'state["force_ladder_probe"] = {"q": _lq_text' in src and 'clean_reply = " ".join(_lead_l + [_lp["q"]]).strip()' in src
    assert '"ladder_probe": _tm.get("ladder")' in src and "mark_ladder_probed as _mlp_g" in src
    # 감정 질문은 S-A-R 미완일 때만
    assert 'or state.get("sar_complete_answer") or state.get("force_ladder_probe")' in src
    l3 = open(os.path.join(ROOT, "diag_project", "prompts", "phase3a", "layer3_state.py"), encoding="utf-8").read()
    assert "[🪜 사다리 탐침 — 시스템 계산, 반드시 준수]" in l3
    from diag_project.services import llm_judge as J
    jsrc = inspect.getsource(J.judge_rubric_level)
    assert "judge_level" in jsrc and "일부 결락이면 한 단계 아래" in jsrc
