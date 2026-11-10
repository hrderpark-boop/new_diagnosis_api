"""(2026-11-04 BEI) 사례 상태기계(services/bei_engine) — 순수 함수 단위 테스트(LLM·DB 없음).

설계: docs/design_bei_2026-11.md §1~§4. 예산 B 16/18/20/18/16, 사례 종료 6/6 또는 리더 턴 8, 3번째 사례 조건(미커버 ≥2 ∧ 남은 턴 − 미커버 ≥ 5),
SWEEP 후속 ≤1(행동+결과가 이미 차면 생략), covered 는 strong 만, 미탐색 = covered·sweep_asked·unconfirmed 어디에도 없음.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.services import bei_engine as B  # noqa: E402

CH = "organization_management"
SUBS = ["비전 제시 및 공유", "전략적 사고", "변화관리(변화지향)", "혁신적 사고"]
LEADER = "작년 3월 교육 개편 때 선임 둘이 반대했어요. 제가 먼저 파일럿을 돌리자고 했고, 그 뒤로 두 사람이 먼저 자료를 가져왔습니다."


def _judged(**status):
    base = {k: {"status": "empty", "quote": ""} for k in B.SLOT_KEYS}
    for k, (st, q) in status.items():
        base[k] = {"status": st, "quote": q}
    return base


def test_budget_and_states():
    assert [B.chapter_budget(c) for c in ("organization_management", "performance_management", "people_management",
                                          "work_management", "self_management")] == [16, 18, 24, 18, 16]   # (P9-1) 사람관리 24
    st: dict = {}
    assert B.chapter_state(st, CH) == "confirm" and B.remaining(st, CH) == 16
    st = B.set_chapter_state(st, CH, B.STATE_EPISODE)
    assert B.chapter_state(st, CH) == "episode"


def test_open_episode_records_opener_in_asked_and_anchored():
    st, ep = B.new_episode({}, CH, SUBS[0], "vision_sharing")
    assert ep["idx"] == 1 and ep["status"] == "open" and B.current_episode(st, CH) == ep
    assert st["asked_subs"][CH] == [SUBS[0]] and st["anchored_subs"][CH] == [SUBS[0]]
    st, ep = B.record_leader_turn(st, CH, ep, turn_index=7)
    assert B.bei_turns(st, CH) == 1 and ep["leader_turns"] == 1 and ep["first_turn_index"] == 7


def test_merge_slots_sticky_and_verbatim_check():
    old = B.empty_slots()
    new = B.merge_slots(old, _judged(context=("filled", "작년 3월 교육 개편"), action=("filled", "지어낸 인용")), LEADER)
    assert new["context"]["status"] == "filled"
    assert new["action"]["status"] == "partial"          # 원문에 없는 인용 → filled 를 인정하지 않는다
    again = B.merge_slots(new, _judged(context=("empty", "")), LEADER)
    assert again["context"]["status"] == "filled"        # filled 는 되돌리지 않는다(sticky)


def test_unfilled_order_gates_reflection_on_result():
    ep = {"slots": _judged(context=("filled", "a"), action=("filled", "b"))}
    assert B.unfilled_slots(ep) == ["reaction", "result", "criterion"]     # result 전에는 reflection 을 묻지 않는다
    ep = {"slots": _judged(context=("filled", "a"), action=("filled", "b"), reaction=("filled", "c"), result=("filled", "d"))}
    assert B.unfilled_slots(ep) == ["criterion", "reflection"]


def test_episode_done_reasons():
    st, ep = B.new_episode({}, CH, SUBS[0], "vision_sharing")
    assert B.episode_done_reason(ep, st, CH) is None
    full = dict(ep, slots={k: {"status": "filled", "quote": "x"} for k in B.SLOT_KEYS})
    assert B.episode_done_reason(full, st, CH) is None                        # (판정 1) 6/6 이어도 리더 턴 4 전에는 닫지 않는다
    assert B.episode_done_reason(dict(full, leader_turns=4), st, CH) == "slots"
    assert "그대로 한 마디" in B.detail_probe_hint(full)                     # 상대 말 인용이 없으면 그 말부터
    full2 = dict(full); full2["slots"] = dict(full["slots"]); full2["slots"]["reaction"] = {"status": "filled", "quote": "'느리다'고 했어요"}
    assert "숫자나 기간" in B.detail_probe_hint(full2)
    assert B.episode_done_reason(dict(ep, leader_turns=8), st, CH) == "turns"
    st["bei_turns"] = {CH: 16}
    assert B.episode_done_reason(ep, st, CH) == "budget"


def test_close_episode_strong_covers_weak_hints_and_asked_derivation():
    st, ep = B.new_episode({}, CH, SUBS[0], "vision_sharing")
    st, ep = B.record_leader_turn(st, CH, ep)
    labels = [{"sub": SUBS[0], "strength": "strong", "quote": "파일럿을 돌리자고"}, {"sub": SUBS[2], "strength": "weak", "quote": ""},
              {"sub": "없는 하위역량", "strength": "strong", "quote": "x"}]
    st = B.close_episode(st, CH, ep, "done", labels, SUBS)
    assert B.covered_set(st, CH) == {SUBS[0]} and B.weak_map(st, CH) == {SUBS[2]: [1]}
    assert st["asked_subs"][CH] == [SUBS[0]]
    assert B.uncovered(st, CH, SUBS) == [SUBS[1], SUBS[2], SUBS[3]]
    assert B.pick_opener(st, CH, SUBS) == SUBS[1]
    assert B.current_episode(st, CH) is None and B.counted_episodes(st, CH) == 1   # status done 이면 턴 수와 무관하게 사례로 센다
    assert B.episodes(st, CH)[0]["status"] == "done"


def test_plan_after_episode_budget_rules():
    st, ep = B.new_episode({}, CH, SUBS[0], "vision_sharing")
    st = B.close_episode(st, CH, dict(ep, leader_turns=6), "done", [{"sub": SUBS[0], "strength": "strong", "quote": "q"}], SUBS)
    st["bei_turns"] = {CH: 6}
    assert B.counted_episodes(st, CH) == 1
    assert B.plan_after_episode(st, CH, SUBS) == "episode"            # 사례 수 < 2
    st, ep2 = B.new_episode(st, CH, SUBS[1], "strategic_thinking")
    st = B.close_episode(st, CH, dict(ep2, leader_turns=6), "done", [{"sub": SUBS[1], "strength": "strong", "quote": "q"}], SUBS)
    st["bei_turns"] = {CH: 12}
    # 사례 2개, 미커버 2개(변화관리·혁신), 남은 4 − 2 < 5 → SWEEP
    assert B.plan_after_episode(st, CH, SUBS) == "sweep"
    st["bei_turns"] = {CH: 8}
    # 남은 8 − 2 = 6 ≥ 5 → 3번째 사례
    assert B.plan_after_episode(st, CH, SUBS) == "episode"
    st["bei_turns"] = {CH: 16}
    # (2026-11-10 P9-1) 예산이 0 이어도 미질문(변화관리·혁신)이 남아 있으면 SWEEP — 종료 조건은 '모든 하위역량 asked' 하나
    assert B.plan_after_episode(st, CH, SUBS) == "sweep"
    for s_ in SUBS[2:]:
        st, sw_ = B.new_episode(st, CH, s_, s_, kind="sweep")
        st = B.close_episode(st, CH, sw_, "no_case", [], SUBS)
        st = B.mark_unconfirmed(st, CH, s_)
    assert B.unasked(st, CH, SUBS) == [] and B.plan_after_episode(st, CH, SUBS) == "close"


def test_sweep_target_followup_and_unconfirmed():
    st: dict = {"bei_turns": {CH: 12}}
    st["covered"] = {CH: {SUBS[0]: [{"episode": 1}], SUBS[1]: [{"episode": 2}]}}
    assert B.sweep_target(st, CH, SUBS) == SUBS[2]
    st, sw = B.new_episode(st, CH, SUBS[2], "change_management", kind="sweep")
    assert st["sweep_asked"][CH] == [SUBS[2]] and B.sweep_target(st, CH, SUBS) == SUBS[3]
    st, sw = B.record_leader_turn(st, CH, sw)
    sw["slots"] = _judged(action=("filled", "a"), result=("filled", "b"))
    assert B.sweep_followup_allowed(st, CH, SUBS, sw) is False           # 행동+결과가 이미 찼으면 후속 생략
    sw["slots"] = _judged(action=("partial", "a"))
    assert B.sweep_followup_allowed(st, CH, SUBS, sw) is True            # 남은 턴 3 > 남은 미커버 1
    st["bei_turns"] = {CH: 17}
    assert B.sweep_followup_allowed(st, CH, SUBS, sw) is False           # 예산이 남은 미커버 수보다 많지 않다
    st = B.mark_unconfirmed(st, CH, SUBS[3])
    cov = B.coverage_summary(st, CH, SUBS)
    assert cov["unconfirmed"] == [SUBS[3]] and cov["not_explored"] == [] and cov["sweep_asked"] == [SUBS[2]]


def test_not_explored_and_no_case():
    st: dict = {"covered": {CH: {SUBS[0]: [{"episode": 1}]}}}
    st = B.mark_no_case(st, CH, SUBS[1])
    cov = B.coverage_summary(st, CH, SUBS)
    assert cov["not_explored"] == [SUBS[2], SUBS[3]] and SUBS[1] in cov["unconfirmed"]
    assert B.pick_opener(st, CH, SUBS) == SUBS[2]                        # no_case 하위역량은 다시 열지 않는다


def test_snapshot_restore_roundtrip():
    st, ep = B.new_episode({"anchor_variant": 1}, CH, SUBS[0], "vision_sharing")
    snap = B.snapshot(st)
    st, ep = B.record_leader_turn(st, CH, ep)
    st = B.close_episode(st, CH, ep, "done", [{"sub": SUBS[0], "strength": "strong", "quote": "q"}], SUBS)
    st = B.restore(st, snap)
    assert B.bei_turns(st, CH) == 0 and B.covered_set(st, CH) == set() and B.current_episode(st, CH)["status"] == "open"
    assert st["anchor_variant"] == 1                                     # 원장 밖 키는 건드리지 않는다


def test_no_case_text_heuristic():
    assert B.is_no_case_text("딱히 그런 일은 없었어요.") and B.is_no_case_text("기억이 잘 안 나네요")
    assert not B.is_no_case_text(LEADER)
