"""(2026-11-04 BEI) 사례 카드·BEI 가이드·슬롯 판정/매핑 스텁·구조화 출력 스키마·리포트 세 갈래 — LLM·DB 없음."""
import re
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
    assert "시스템이 붙일 여는 문장: \"그런 일, 최근에 있으셨어요?\"" in card and "질문" in card and "쓰지 않는다" in card   # (P4-4) 여는 문장 = 왜 묻는지 + 있었는지 질문
    card2 = EC.build_episode_card(instruction="SWEEP_ANCHOR", chapter=CH, ep=None, bei_turns=12, budget=16, anchor_text="Q?",
                                  weak_hint="아까 1번째 사례에서 이쪽 이야기가 살짝 나왔다")
    assert "다리 힌트: 아까 1번째 사례" in card2
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
    assert labels == [{"sub": "전략적 사고", "strength": "strong", "quote": "작년 3월에 개편이 있었어요.", "confidence": 1.0}]


def test_sub_defs_have_action_cues():
    defs = SJ.sub_defs_for(CH)
    assert [d["name"] for d in defs] == ["비전 제시 및 공유", "전략적 사고", "변화관리(변화지향)", "혁신적 사고"]
    assert all(d["action_cue"] and d["lv2_example"] and d["description"] for d in defs)


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
    # (2026-11-06 P7-2) 미탐색도 1.0 '사례 미확인' — 같은 라벨·같은 점수. status/unconfirmed_kind 는 관리자·린트 구분용으로 남는다
    assert led["혁신적 사고"]["status"] == "not_explored" and led["혁신적 사고"]["score"] == 1.0 and led["혁신적 사고"]["level_label"] == UNCONFIRMED_LABEL
    assert led["혁신적 사고"]["unconfirmed"] is True and led["혁신적 사고"]["unconfirmed_kind"] == "not_explored" and "이어서 진행하면" in led["혁신적 사고"]["unconfirmed_text"]
    assert NOT_EXPLORED_LABEL  # 관리자용 라벨 상수는 유지
    assert led["전략적 사고"]["unconfirmed_kind"] == "gate_dropped" and led["변화관리(변화지향)"]["unconfirmed_kind"] == "no_case"
    assert led["전략적 사고"]["level_label"] == UNCONFIRMED_LABEL and led["전략적 사고"]["score"] == 1.0
    assert tot["not_explored_total"] == 1 and tot["gate_dropped_total"] == 1 and tot["no_case_total"] == 1 and tot["probe_deficit_unconfirmed"] == 0
    assert tot["unconfirmed_total"] == 3                                                       # 게이트 탈락 1 + 없음 1 + 미탐색 1
    assert results[CH]["sub_scores"]["혁신적 사고"] == 1.0 and results[CH]["not_explored_count"] == 1 and results[CH]["measured_count"] == 4
    assert results[CH]["behavior_score"] == round((3.0 + 1.0 + 1.0 + 1.0) / 4, 2)   # 26칸 전부 점수 — 미탐색 1.0 포함 평균


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


def test_leading_choice_question_detection():
    from diag_project.services.output_guard import is_leading_choice_question as L
    assert L("자료를 보셨군요. 그때 직접 밀어붙이셨나요, 아니면 한 발 물러서셨나요?")
    assert L("두 분이 반대하셨다면 어떻게 하셨을까요?")
    assert not L("자료를 보셨군요. 그 자리에서 처음 꺼낸 말은 무엇이었나요?")
    assert not L("다시 한다면 어떻게 하고 싶으세요?")   # 돌아보기 질문(가정형 금지 대상 아님)


def test_daniel_observation_is_rendered_not_fixed():
    """(2026-11-11 P10-2) Daniel 선배 관찰은 고정 문장 5종이 아니라 사례 내용을 넣어 쓰는 슬롯(observation)이다."""
    from diag_project.services import intro_messages as M
    assert not hasattr(M, "DANIEL_OBSERVATIONS") and not hasattr(M, "next_daniel_observation")
    assert M.slot_kind_for("Daniel", 0) == "observation" == M.slot_kind_for("Daniel", 3)


def test_cross_chapter_evidence_tagged_with_source_chapter():
    from diag_project.llm_service import GeminiService
    svc = GeminiService.__new__(GeminiService)
    svc._analysis_user_turns = [("organization_management", "운영 보고서를 그 도구로 자동으로 만드는 방법을 제가 먼저 만들어 보여드렸고"),
                                ("work_management", "열두 건을 난이도별로 나눠 강사 둘에게 운영 일부를 넘겼습니다")]
    out = svc._tag_cross_chapter_evidence("work_management", ["운영 보고서를 그 도구로 자동으로 만드는 방법을 제가 먼저 만들어", "열두 건을 난이도별로 나눠 강사 둘에게"])
    assert out[0].startswith("(조직관리 대화에서) ") and out[1].startswith("열두 건")
    assert svc._tag_cross_chapter_evidence("work_management", out) == out   # 두 번 붙이지 않는다
    assert svc._tag_cross_chapter_evidence("work_management", ["원문에 없는 인용"]) == ["원문에 없는 인용"]


# ── (2026-11-05 P4) 운영 Michael 완주 세션 검토 반영 ───────────────────────────────────────────────────


def test_p4_1_slot_variants_rotate_per_session_and_caps():
    """(P10-2 로 갱신) 슬롯은 고정 문구 풀이 아니라 종류표(코치마다 무엇을 하는가) + 상한 · 정의 질문 5종 · ALIGN 안내·다리 3종."""
    from diag_project.services import intro_messages as M
    from diag_project.services.intro_messages import (
        ALIGN_GUIDE_VARIANTS, ALIGN_OPEN_VARIANTS, DEFINITION_VARIANTS, MICHAEL_WILL_SESSION_CAP, SLOT_KIND_TARGET, SLOT_KINDS,
        SLOT_SESSION_CAP, align_guide_line, align_open_line, definition_question, definition_question_variants, slot_kind_for,
    )
    assert SLOT_SESSION_CAP == 5 and MICHAEL_WILL_SESSION_CAP == 3
    for gone in ("PERSONA_SLOT_VARIANTS", "MICHAEL_WILL_QUESTIONS", "next_slot_sentence", "michael_will_question", "slot_variants_for"):
        assert not hasattr(M, gone), gone                       # 고정 슬롯 문장·순환 함수는 전부 삭제
    assert set(SLOT_KINDS) == {"Jessica", "Lucas", "Olivia", "Michael", "Daniel"} and slot_kind_for("Ella", 0) is None
    assert slot_kind_for("Jessica", 0) == "criterion" and slot_kind_for("Lucas", 2) == "reason" and slot_kind_for("Michael", 1) == "cheer"
    assert [slot_kind_for("Olivia", i) for i in range(5)] == ["counterfactual", "other_side", "counterfactual", "counterfactual", "other_side"]
    assert SLOT_KIND_TARGET["other_side"] == "reaction" and SLOT_KIND_TARGET["counterfactual"] == "criterion" and "cheer" not in SLOT_KIND_TARGET
    # 정의 질문 5종 — 코치마다 5개 서로 다르고 {cn_eul} 자리 포함
    for k, pool in DEFINITION_VARIANTS.items():
        assert len(pool) == 5 == len(set(pool)) and all(("{cn_eul}" in v or "{cn_eun}" in v or "{cn_iga}" in v or "{cn}" in v) for v in pool), k
    vs = definition_question_variants("일관리", "Michael (마이클)")
    assert len(set(vs)) == 5 and definition_question("일관리", "Michael (마이클)", 3) == vs[3] and "'일관리'" in vs[3]
    # (2026-11-11 P10-2) 완결 문장 5종 — 생략형('~풀면요?', '~하면요?', '뭐가 먼저 떠올라요?') 폐기
    assert definition_question("조직관리", "Ella (엘라)", 0) == "'조직관리'를 리더님은 어떤 일이라고 생각하세요?"
    assert definition_question("일관리", "Jessica", 1) == "리더님이 보시기에 '일관리'는 무엇을 하는 일입니까?"
    assert definition_question("자기관리", "Daniel", 4) == "리더님께 '자기관리'는 어떤 의미입니까?"
    for pool in DEFINITION_VARIANTS.values():
        assert not any(re.search(r"(풀면요|하면요|떠올라요|떠오르세요|한 문장으로)", v) or "챙긴다" in v for v in pool)
        assert all(re.search(r"(세요|나요|가요|어요|예요|니까)\?$", v) for v in pool)        # 서술어로 끝나는 완결 문장
    for k in ALIGN_GUIDE_VARIANTS:
        assert len(ALIGN_GUIDE_VARIANTS[k]) == 3 and len(ALIGN_OPEN_VARIANTS[k]) == 3
        assert len({align_guide_line("네", k, i) for i in range(3)}) == 3 and len({align_open_line(k, i) for i in range(3)}) == 3
    assert "네 가지" in align_guide_line("네", "Jessica", 1)


def test_p4_2_praise_lead_detected_and_regenerated_not_capped():
    """'좋습니다/좋은 방향/좋은 흐름/잘하셨/인상적' 류는 상한이 아니라 전면 제거 — find_praise 가 잡고 8-i 재생성 키에 들어 있다. 문두 리드만 있는 문장은 리드만 뗀다."""
    import inspect
    from diag_project.services.output_guard import find_praise, strip_praise
    from diag_project.services.persona_voice import PROBE_PREFERENCE, michael_lead_guard
    from diag_project.services.intro_messages import PERSONA_LINES
    from diag_project.routes import diagnoses as d
    assert find_praise("좋습니다, 참여율을 핵심으로 보셨군요.") == ["좋습니다(문두)"]
    assert find_praise("그 방향이 좋은 흐름이네요. 정말 잘하셨어요.") == ["잘하셨", "좋은 흐름"]
    assert find_praise("오늘은 여기서 잠시 쉬어가셔도 좋습니다.") == []          # 문장 가운데의 허용 표현
    assert find_praise("운영 공수 30% 감소까지 확인하셨다는 건 정량적으로도 분명한 성과입니다.") == ["분명한 성과"]   # (11/06 덧붙임) p4b Michael
    assert find_praise("숫자로 설득이 확실한 결과로 이어졌네요.") == ["확실한 결과"]
    assert strip_praise("좋습니다, 참여율을 핵심으로 보셨군요. 좋은 방향이에요. 그 뒤에는요?") == ("참여율을 핵심으로 보셨군요. 그 뒤에는요?", 2)
    assert '"praise"}' in inspect.getsource(d._submit_message_phase3a)
    # Michael '좋습니다' — 꼬리 풀·선호·고정 문장에서 삭제, 가드는 떼기만
    assert "질문 앞에 '좋습니다,'" not in PROBE_PREFERENCE["Michael"]
    assert not any(v.startswith("좋습니다") for v in PERSONA_LINES["Michael"].values())
    assert michael_lead_guard("좋습니다, 그 뒤에는요?", False, add=False) == ("그 뒤에는요?", False)


def test_p4_3_scar_sentences_are_deleted_not_replaced():
    """운영 Michael 세션(11/5)의 흉터 2건 꼴 — '…게 인데요'(서술어 없음)·'리더님.'(호칭만) — 고정. 삭제 뒤 되받기가 0이면 8-w 가 재생성(no_receive)."""
    from diag_project.services.output_guard import delete_broken_statements, is_broken_sentence
    from diag_project.services.receive_check import check_receive
    scar1 = "두 분을 따로 불러 이유부터 들으셨다는 게 인데요."
    scar2 = "리더님."
    assert is_broken_sentence(scar1) and is_broken_sentence(scar2) and is_broken_sentence("박기진 리더님.") and is_broken_sentence("그 결정의 기준.")
    for ok in ("그 선택, 응원합니다.", "먼저 하나부터.", "그때가 3월이었고요.", "그 부분은 분명합니다.", "그 뒤에는 어떻게 됐어요?"):
        assert not is_broken_sentence(ok) or ok == "먼저 하나부터.", ok      # '먼저 하나부터.'(Lucas 고정 다리)는 keep 으로 보호
    out, n = delete_broken_statements(f"{scar1} {scar2} 그 자리에서 처음 꺼내신 말이 뭐였어요?")
    assert n == 2 and out == "그 자리에서 처음 꺼내신 말이 뭐였어요?"
    assert check_receive(out, "두 사람을 따로 불러서 이유를 들었어요") == (False, False)     # 되받기 0 → 8-w no_receive 재생성
    out2, n2 = delete_broken_statements("먼저 하나부터. 그 자리에서요?", keep=["먼저 하나부터."])
    assert n2 == 0 and out2.startswith("먼저 하나부터.")
    out3, n3 = delete_broken_statements(f"참여율을 핵심으로 보셨군요. {scar2} 그 뒤에는요?")
    assert n3 == 1 and out3 == "참여율을 핵심으로 보셨군요. 그 뒤에는요?"


def test_p4_4_opener_shape_why_plus_existence_question():
    """사례 여는 문장 = [왜 묻는지 1문장] + [있었는지 질문]. 전제형('~받으셨을 때 어떻게')·선택지·이름 노출·질문 2개는 불합격 → 사전 앵커 폴백."""
    from diag_project.services.anchor_render import opener_shape_ok
    ok, _ = opener_shape_ok("맡길 일과 직접 할 일을 어떻게 가르시는지 보는 쪽인데요. 최근에 '이건 맡겨 보자' 하신 일이 있으셨어요? 작은 일이어도요.")
    assert ok
    ok, _ = opener_shape_ok("팀의 방향을 어떻게 다시 세우셨는지 보려고요, 근래에 방향을 바꿔 잡으셨던 일이 있으셨어요?")   # 쉼표 결합형
    assert ok
    assert opener_shape_ok("최근에 팀원 피드백을 받으셨을 때 어떻게 하셨어요?") == (False, "no_why")
    assert opener_shape_ok("남의 평가를 어떻게 받아들이는지 보는 쪽이에요. 피드백을 받으셨을 때 어떻게 하셨어요?") == (False, "presupposes")
    assert opener_shape_ok("맡기는 쪽을 볼게요. 어떤 일이었나요? 결과는요?")[1] == "questions=2"
    assert opener_shape_ok("권한위임을 보는 쪽인데요. 최근에 맡겨 보신 일이 있으셨어요?")[1] == "name_or_metaphor"
    assert opener_shape_ok("맡기는 쪽을 볼게요. 그 일을 어떻게 나누셨어요?")[1] == "not_existence_question"


def test_p4_5_sweep_cap_three_per_chapter_and_bridge_rule():
    """(2026-11-10 P9-1) SWEEP 챕터당 상한 삭제 — 미질문이 남아 있으면 끝까지 묻는다 · 연속 SWEEP 순번 · 다리 표지 판정 · 카드가 2개째부터 다리 필수를 지시."""
    from diag_project.services import bei_engine as B
    from diag_project.services.output_guard import has_sweep_bridge
    from diag_project.prompts.phase3a.episode_card import build_episode_card
    CH = "people_management"
    subs = [f"s{i}" for i in range(9)]
    st: dict = {"bei_turns": {CH: 10}, "covered": {CH: {"s0": [{"episode": 1}]}}}
    opened = []
    for _ in range(12):
        t = B.sweep_target(st, CH, subs)
        if t is None:
            break
        st, _ep = B.new_episode(st, CH, t, t, kind="sweep")
        opened.append(t)
    assert opened == [f"s{i}" for i in range(1, 9)] and B.sweep_target(st, CH, subs) is None      # 상한 없이 8개 전부
    assert B.consecutive_sweeps(st, CH) == 8
    cov = B.coverage_summary(st, CH, subs)
    assert cov["not_explored"] == [] and B.unasked(st, CH, subs) == []
    assert has_sweep_bridge("아까 공통 양식 얘기에서 살짝 나왔는데, 그쪽을 하나 더 여쭙고 싶어요.") and not has_sweep_bridge("교안을 먼저 확보하는 쪽이 과정을 살린다고 보셨군요.")
    card = build_episode_card(instruction="SWEEP_ANCHOR", chapter=CH, ep=None, bei_turns=10, budget=20, anchor_text="그런 일, 최근에 있으셨어요?",
                              sweep_seq=2, bridge_material="'하루를 비워서 두 분을 한자리에 앉혔어요'")
    assert "연속 2번째" in card and "다리 1문장이 필수" in card and "하루를 비워서" in card
    card1 = build_episode_card(instruction="SWEEP_ANCHOR", chapter=CH, ep=None, bei_turns=10, budget=20, anchor_text="그런 일, 최근에 있으셨어요?", sweep_seq=1)
    assert "필수" not in card1


def test_p4_6_close_summary_material_strips_leading_conjunction_and_template_gone():
    """종료 요약 재료의 인용은 접속사 없이 — '그래서 …' 로 시작한 인용이 코치 문장을 접속사로 시작하게 했다. 템플릿('첫 사례에서는 … 하셨고')은 폐지."""
    import inspect
    from diag_project.services.output_guard import strip_leading_conjunction
    from diag_project.prompts.phase3a.layer3_state import _get_instruction_guide
    from diag_project.routes import diagnoses as d
    assert strip_leading_conjunction("그래서 그다음에 두 명만 먼저 쓰자고 했어요") == "두 명만 먼저 쓰자고 했어요"
    assert strip_leading_conjunction("근데, 파일럿을 먼저 돌렸어요") == "파일럿을 먼저 돌렸어요"
    assert strip_leading_conjunction("그날 저녁에 원인부터 쪼개 봤어요") == "그날 저녁에 원인부터 쪼개 봤어요"
    g = _get_instruction_guide("CHAPTER_READY_TO_END", {"chapter": "organization_management",
                                                       "bei_close_episodes": [{"idx": 1, "action": "그래서 두 사람을 따로 불렀어요", "context": "", "result": ""},
                                                                              {"idx": 2, "action": "그리고 파일럿을 먼저 돌렸어요", "context": "", "result": ""}]})
    # (2026-11-10 P9-9) 재료는 사례 + 보완 답, 합쳐 2~3문장
    assert "합쳐서 2~2문장으로" in g and "'파일럿을 먼저 돌렸어요'" in g and "'두 사람을 따로 불렀어요'" in g and "'그래서 두 사람" not in g
    src = inspect.getsource(d._submit_message_phase3a)
    assert "첫 사례에서는 '" not in src and "close_summary_mode" in src


def test_p4_7_score_breakdown_carries_confidence_stars_everywhere():
    """score_breakdown 조립 3곳(분석·병합·원장 확정) 모두 확신도를 점수에 넣지 않고 ★ 표시 필드를 싣는다."""
    import inspect
    from diag_project import llm_service as L
    from diag_project.services import outer_merge as OM, report_ledger as RL
    for mod in (L, OM, RL):
        assert "confidence_display" in inspect.getsource(mod), mod.__name__
    from diag_project.services.scoring import competency_final_score
    assert competency_final_score(2.6, 0.3, 0.2) == 2.9        # 운영 일관리 3.1 → 2.9


def test_p4_8_lv3_design_rule_in_rubric_and_gate():
    from diag_project.llm_service import LV3_DESIGN_RULE, _build_rubric_block, _DEEP_PROMPT_VERSION_CLAUDE
    from diag_project.services.level_gate import GATE_SYSTEM, GATE_PROMPT_VERSION
    blk = _build_rubric_block("performance_management", ["목표설정 및 공유", "성과지표 관리(KPI)"])
    assert LV3_DESIGN_RULE in blk and "직접 제안해 팀이 채택" in LV3_DESIGN_RULE and "성과지표 관리(KPI)" in LV3_DESIGN_RULE
    assert "6. (설계 = Lv.3)" in GATE_SYSTEM and "강등하지 말 것" in GATE_SYSTEM
    assert GATE_PROMPT_VERSION >= "2026-11-05" and _DEEP_PROMPT_VERSION_CLAUDE >= "2026-11-05"   # P4-8 이후 버전(P6 에서 다시 올림)


def test_p4_1_definition_turn_scope_line_fallback_per_chapter():
    from diag_project.services.intro_messages import CHAPTER_SCOPE_LINES, chapter_scope_line
    from diag_project.data.competencies import COMPETENCY_FRAMEWORK
    for ch in (k for k in COMPETENCY_FRAMEWORK if k != "supplementary"):
        assert chapter_scope_line(ch).endswith("함께 짚어볼 거예요.") and len(CHAPTER_SCOPE_LINES[ch]) > 20
    assert "시간과 자원" in chapter_scope_line("work_management")


def test_p4_6_close_render_pure_checks_and_numbering_strip():
    """종료 요약: 번호 매기기('사례 1에서는') 제거 · 사례별 겹침 수 · 질문·예고 문장 제거. 운영 전문의 요약 꼴로 검사한다."""
    from diag_project.services.close_render import clean_close_summary, episodes_matched
    from diag_project.services.output_guard import strip_case_numbering
    eps = [{"idx": 1, "action": "두 사람을 따로 불러서 먼저 이유부터 들었어요", "context": "", "result": "두 분이 개편 TF에 자원했습니다"},
           {"idx": 2, "action": "대표님께 운영팀 2명만 먼저 쓰자는 안을 숫자와 함께 가져갔어요", "context": "", "result": "운영 공수가 30% 줄었어요"}]
    llm = "사례 1에서는 두 강사를 따로 불러 먼저 이유를 들으셨고 두 분이 TF에 자원하셨습니다. 사례 2에서는 운영팀 2명 먼저 쓰는 안을 숫자와 함께 내셨고 운영 공수가 30% 줄었습니다. 이제 성과관리로 넘어가 보겠습니다."
    out = clean_close_summary(llm, 2)
    assert out.startswith("두 강사를") and "사례 1" not in out and "사례 2" not in out and "넘어가" not in out
    assert episodes_matched(out, eps) == 2
    # 질문만 이어 쓴 본 호출 출력(p4a Michael)은 0 — 집중 렌더로 넘어간다
    assert clean_close_summary("네, 그럼 파일럿 얘기를 조금 더 이어가 볼게요. 두 달 파일럿 과정을 고르실 때, 어떤 기준으로 그 과정을 택하셨어요?", 2) == ""
    assert episodes_matched("운영팀 2명만 먼저 쓰자는 안을 숫자와 함께 가져가셨습니다.", eps) == 1      # 사례 2만 되짚음
    assert strip_case_numbering("첫 번째 사례에서는 파일럿을 돌리셨습니다.") == "파일럿을 돌리셨습니다."
    assert strip_case_numbering("마지막 사례에서 교안을 먼저 받으셨습니다.") == "교안을 먼저 받으셨습니다."


def test_p4_leading_choice_includes_hogeun_and_lint_align_allows_tail():
    from diag_project.services.output_guard import is_leading_choice_question
    from tools import transcript_lint as tl
    assert is_leading_choice_question("대표님께 되물으셨는지, 팀원을 먼저 모으셨는지, 혹은 혼자 정리하셨는지요?")
    assert is_leading_choice_question("직접 하셨나요, 또는 맡기셨나요?") and not is_leading_choice_question("그때 무엇을 먼저 하셨어요?")
    org = "조직관리를 '방향'이라고 하셨군요.\n\n저희는 조직관리를 '…'으로 봐요.\n· 비전 제시 및 공유\n· 전략적 사고\n· 변화관리(변화지향)\n· 혁신적 사고\n\n네 가지를 들어볼게요. 먼저 하나부터요.\n\n팀이 갈 방향을 어떻게 세우셨는지 보는 쪽인데요. 최근에 방향을 다시 잡으셨던 일이 있으셨어요? 작은 일이어도요."
    ok, reasons = tl.check_align_turn(org, "organization_management")
    assert ok, reasons

