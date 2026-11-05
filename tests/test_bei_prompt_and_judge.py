"""(2026-11-04 BEI) 사례 카드·BEI 가이드·슬롯 판정/매핑 스텁·구조화 출력 스키마·리포트 세 갈래 — LLM·DB 없음."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project import llm_schemas as S  # noqa: E402
from diag_project.prompts.phase3a import episode_card as EC  # noqa: E402
from diag_project.prompts.phase3a.layer3_state import format_turn_state_for_llm  # noqa: E402
from diag_project.services import bei_engine as B  # noqa: E402
from diag_project.services import slot_judge as SJ  # noqa: E402

CH = "organization_management"


def _ep(**kw):
    ep = {"idx": 2, "kind": "episode", "opener_sub": "전략적 사고", "status": "open", "leader_turns": 3, "retry": 0, "slot_used": False,
          "slots": B.empty_slots(), "labels": []}
    ep.update(kw)
    return ep


def test_chapter_context_is_compact_and_internal():
    ctx = EC.chapter_context_bei(CH)
    assert ctx.startswith("# 현재 챕터: 조직관리") and "리더에게 이름·분류를 말하지 않는다" in ctx
    for name in ("비전 제시 및 공유", "전략적 사고", "변화관리(변화지향)", "혁신적 사고"):
        assert f"- {name}:" in ctx
    assert "시작 스크립트" not in ctx and "Backup" not in ctx and "최대 턴" not in ctx
    assert EC.chapter_context_bei(None) == ""


def test_episode_card_probe_lists_filled_missing_and_next_slot():
    ep = _ep()
    ep["slots"]["context"] = {"status": "filled", "quote": "작년 3월 교육 개편"}
    ep["slots"]["action"] = {"status": "partial", "quote": "팀에서 파일럿"}
    card = EC.build_episode_card(instruction="EPISODE_PROBE", chapter=CH, ep=ep, bei_turns=5, budget=16, signal="직전 답 짧음")
    assert "2번째 / 이 사례 리더 턴 3/8 / 이 영역 리더 턴 5/16" in card
    assert "채워진 것: 상황·시점 — \"작년 3월 교육 개편\"(리더 말)" in card
    assert "반쯤 나온 것" in card and "리더 행동 — \"팀에서 파일럿\"" in card
    assert "아직 없는 것(이 순서로 하나씩): 리더 행동 → 상대 반응 → 결과 → 판단 기준" in card   # reflection 은 결과 뒤에만
    assert "이번 턴: '리더 행동' 하나를 묻는다" in card and "신호: 직전 답 짧음" in card


def test_episode_card_open_and_sweep_carry_system_anchor():
    card = EC.build_episode_card(instruction="EPISODE_OPEN", chapter=CH, ep=None, bei_turns=8, budget=16, anchor_text="그런 일, 최근에 있으셨어요?")
    assert "시스템이 붙일 여는 질문: \"그런 일, 최근에 있으셨어요?\"" in card and "질문은 쓰지 않는다" in card
    card2 = EC.build_episode_card(instruction="SWEEP_ANCHOR", chapter=CH, ep=None, bei_turns=12, budget=16, anchor_text="Q?",
                                  weak_hint="아까 1번째 사례에서 이쪽 이야기가 살짝 나왔다")
    assert "다리 힌트(선택): 아까 1번째 사례" in card2
    ep = _ep(kind="sweep", leader_turns=1)
    card3 = EC.build_episode_card(instruction="SWEEP_FOLLOWUP", chapter=CH, ep=ep, bei_turns=13, budget=16)
    assert "이번 턴: '리더 행동' 하나" in card3 and "마무리한다" in card3


def test_bei_turn_text_has_persona_card_guide_and_rules():
    state = {"instruction_for_this_turn": "EPISODE_PROBE", "coach_persona": {"name": "Jessica (제시카)", "coaching_style": "구조적", "tags": "#냉철"},
             "bei_card": "# 지금 듣고 있는 사례 (1번째)"}
    txt = format_turn_state_for_llm(state)
    assert txt.index("[🎭 페르소나 유지] 당신은 Jessica") < txt.index("# 지금 듣고 있는 사례") < txt.index("[Instruction for this turn]\nEPISODE_PROBE")
    assert "되받기 1~3문장 + 질문 1개" in txt and "[금지]" in txt and "[Turn State]" not in txt
    for instr in EC.BEI_GUIDES:
        assert EC.is_bei_instruction(instr)
    assert not EC.is_bei_instruction("COMPETENCY_ALIGN")


def test_slot_schemas_are_claude_compatible():
    S.assert_claude_compatible(S.slot_judge_schema())
    S.assert_claude_compatible(S.episode_map_schema())
    assert set(S.slot_judge_schema()["properties"]["slots"]["properties"]) == set(B.SLOT_KEYS)


def test_slot_judge_stub_fills_one_slot_per_leader_turn(monkeypatch):
    monkeypatch.setenv("FM_LLM_STUB", "1")
    tr = [("model", "그런 일 최근에 있으셨어요?"), ("user", "작년 3월에 개편이 있었어요."), ("model", "그때 뭘 하셨어요?"), ("user", "제가 파일럿을 돌렸습니다.")]
    out = asyncio.run(SJ.judge_slots(None, transcript=tr, prev_slots=None))
    assert out["stub"] and [k for k in B.SLOT_KEYS if out["slots"][k]["status"] == "filled"] == ["context", "action"]
    assert out["no_case"] is False
    out2 = asyncio.run(SJ.judge_slots(None, transcript=tr + [("model", "결과는요?"), ("user", "딱히 없었어요.")], prev_slots=None))
    assert out2["no_case"] is True
    labels = asyncio.run(SJ.map_episode(None, transcript=tr, chapter_name="조직관리", sub_defs=SJ.sub_defs_for(CH), opener_sub="전략적 사고"))
    assert labels == [{"sub": "전략적 사고", "strength": "strong", "quote": "작년 3월에 개편이 있었어요."}]


def test_sub_defs_have_action_cues():
    defs = SJ.sub_defs_for(CH)
    assert [d["name"] for d in defs] == ["비전 제시 및 공유", "전략적 사고", "변화관리(변화지향)", "혁신적 사고"]
    assert all(d["action_cue"] for d in defs)


def test_report_ledger_three_kinds_and_not_explored_blank():
    from diag_project.services.report_ledger import apply_unconfirmed_policy, mark_not_explored
    from diag_project.services.scoring import NOT_EXPLORED_LABEL, UNCONFIRMED_LABEL
    results = {CH: {"sub_ledger": {
        "비전 제시 및 공유": {"asked": True, "measured": True, "level": 3, "score": 3.0, "evidence": ["x"], "gate_status": "passed"},
        "전략적 사고": {"asked": True, "measured": False, "evidence": [], "gate_status": "failed", "candidate_runs": 2},   # 사례 있었으나 게이트 탈락
        "변화관리(변화지향)": {"asked": True, "measured": False, "evidence": [], "gate_status": "n_a"},                   # SWEEP 에서 없음
        "혁신적 사고": {"asked": False, "measured": False, "evidence": [], "gate_status": "n_a"},                         # 예산 소진
    }}}
    meta = {"coverage": {CH: {"covered": ["비전 제시 및 공유", "전략적 사고"], "sweep_asked": ["변화관리(변화지향)"],
                             "unconfirmed": ["변화관리(변화지향)"], "not_explored": ["혁신적 사고"]}},
            "unconfirmed": {CH: ["변화관리(변화지향)"]}}
    ne = mark_not_explored(results, [], meta)
    assert ne == {CH: ["혁신적 사고"]}
    tot = apply_unconfirmed_policy(results, meta)
    led = results[CH]["sub_ledger"]
    assert led["혁신적 사고"]["status"] == "not_explored" and led["혁신적 사고"]["score"] is None and led["혁신적 사고"]["level_label"] == NOT_EXPLORED_LABEL
    assert led["전략적 사고"]["unconfirmed_kind"] == "gate_dropped" and led["변화관리(변화지향)"]["unconfirmed_kind"] == "no_case"
    assert led["전략적 사고"]["level_label"] == UNCONFIRMED_LABEL and led["전략적 사고"]["score"] == 1.0
    assert tot["not_explored_total"] == 1 and tot["gate_dropped_total"] == 1 and tot["no_case_total"] == 1 and tot["probe_deficit_unconfirmed"] == 0
    assert results[CH]["sub_scores"]["혁신적 사고"] is None and results[CH]["not_explored_count"] == 1
    assert results[CH]["behavior_score"] == round((3.0 + 1.0 + 1.0) / 3, 2)   # 미탐색은 평균에서 제외


def test_count_question_markers_catches_compound_questions():
    from diag_project.services.output_guard import count_question_markers as C
    assert C("그 결과를 두 강사에게 어떻게 보여주셨는지, 그리고 그때 가장 크게 배운 점은 무엇이었나요?") == 2
    assert C("그 순간 어떤 판단을 하셨습니까? 그날 이후 무엇을 기준으로 확인하셨는지도 함께 들려주시면 좋겠습니다.") == 2   # 요청형도 질문
    assert C("월별 계획을 보여드리기로 하셨을 때, 어떤 선택지들을 버리고 그 방법을 고르셨나요?") == 1
    assert C("있었다면 언제였고, 어떤 장면이었나요?") == 1


def test_episode_card_first_turn_rule_and_detail_probe():
    ep = _ep(leader_turns=1)
    card = EC.build_episode_card(instruction="EPISODE_PROBE", chapter=CH, ep=ep, bei_turns=1, budget=16)
    assert "첫 턴 규칙: 먼저 리더가 방금 말한 상황을 한 문장으로 받는다" in card
    full = _ep(leader_turns=3)
    full["slots"] = {k: {"status": "filled", "quote": "x"} for k in B.SLOT_KEYS}
    card2 = EC.build_episode_card(instruction="EPISODE_PROBE", chapter=CH, ep=full, bei_turns=3, budget=16)
    assert "장면 구체화" in card2 and "그대로 한 마디" in card2


def test_split_compound_question_keeps_last_clause_and_request_forms_are_questions():
    from diag_project.services.output_guard import is_question, split_compound_question as S
    out, n = S("설득을 하셨는지, 속도를 조절하셨는지, 아니면 다른 방식이었는지 궁금합니다.")
    assert n == 1 and out == "다른 방식이었는지 궁금합니다."
    assert is_question("그렇게 생각하시는 이유도 간단히 부탁드려요.")   # 정의 턴(8-k)이 LLM 요청 문장을 지운다
