"""(2026-11-14 P12d) outer 병합이 '최종 레벨을 낸 run' 의 사유·근거·서술을 쓰는지 고정하는 순수 함수 테스트.

종전: 병합 결과의 level_gate·근거 맨 앞·영역 서술이 run0 고정 → 판정 2·3·3 이면 최종 3 인데 사유는 run0("…Lv.2").
지금: 칸별 level_gate·근거 맨 앞 = 최종 레벨을 낸 첫 run, 영역 서술 = 칸별 레벨이 최종과 가장 많이 일치하는 run(동률은 앞 run).
입력 문장은 전부 가짜(서비스 문구·실제 발화와 무관).
"""
import copy
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.services.outer_merge import (  # noqa: E402
    merge_competency, merge_outer_runs, pick_base_run, pick_level_run,
)

_NARR = ("comment", "strength_point", "growth_point", "gap_analysis", "situational_pattern")


def _run(i, levels, narrative=True, eval_subs=None, gate=True):
    """outer run 하나의 대역량 결과. levels: {칸: 레벨 | None(근거 후보 없음) | 'X'(게이트 탈락)}.
    i 는 run 순번 — 사유·근거·서술 문장에 박아 출처를 구분한다. narrative=False 면 판정 전용 run 꼴(서술 빈 문자열)."""
    led, lg = {}, {}
    for s, lv in levels.items():
        ok = lv not in (None, "X")
        led[s] = {"asked": True, "measured": ok, "level": lv if ok else None, "score": float(lv) if ok else None,
                  "evidence": [f"가짜 인용 run{i} {s}: 목요일에 서랍 번호표를 다시 붙였습니다", "공통 인용: 창고 열쇠를 반납했습니다"] if ok else [],
                  "status": "measured" if ok else "evidence_missing",
                  "gate_status": "failed" if lv == "X" else ("passed" if ok else "n_a"),
                  "claimed_level": None if lv is None else 3}
        if lv is not None:
            lg[s] = {"verified_level": lv if ok else None, "dropped": not ok, "pending": False, "category": "구체행동",
                     "reason": f"가짜 사유 run{i} {s}: 번호표 정리를 혼자 끝냄. " + (f"Lv.{lv}." if ok else "탈락."),
                     "votes": [lv if ok else 0] * 2}
    txt = (lambda f: f"가짜 서술 run{i} {f}") if narrative else (lambda f: "")
    r = {"sub_ledger": led, "score_breakdown": {"star_depth_bonus": 0.0, "confidence_adj": 0.0},
         "reasoning_process": {k: {"description": txt(k), "evidence": [f"가짜 발췌 run{i} {k}"]}
                               for k in ("1_situation", "2_action", "3_result")},
         **{f: txt(f) for f in _NARR}}
    if gate:
        r["level_gate"] = lg
    if eval_subs is not None:
        r["_eval_subs"] = list(eval_subs)
    return r


def _merge(runs):
    return merge_competency(runs, "people_management", len(runs))


def _check_cell_from(m, sub, run_idx, level):
    """칸의 최종 레벨·사유·근거 맨 앞이 run_idx 것인지."""
    row = m["sub_ledger"][sub]
    assert row["measured"] and row["level"] == level and row["level_run"] == run_idx
    assert m["level_gate"][sub]["reason"].startswith(f"가짜 사유 run{run_idx} {sub}")
    assert m["level_gate"][sub]["reason"].endswith(f"Lv.{level}.")          # 사유가 최종 레벨로 끝난다
    assert m["level_gate"][sub]["verified_level"] == level
    assert row["evidence"][0].startswith(f"가짜 인용 run{run_idx} {sub}")


def _check_narrative_from(m, run_idx):
    assert m["base_run"] == run_idx
    for f in _NARR:
        assert m[f] == f"가짜 서술 run{run_idx} {f}"
    for k in ("1_situation", "2_action", "3_result"):
        assert m["reasoning_process"][k]["description"] == f"가짜 서술 run{run_idx} {k}"
        assert m["reasoning_process"][k]["evidence"] == [f"가짜 발췌 run{run_idx} {k}"]


# ── 지시된 세 경우 ────────────────────────────────────────────────────────────
def test_233_takes_reason_evidence_narrative_from_run1():
    m = _merge([_run(0, {"A": 2}), _run(1, {"A": 3}), _run(2, {"A": 3})])
    _check_cell_from(m, "A", 1, 3)
    _check_narrative_from(m, 1)
    assert m["sub_ledger"]["A"]["stability"] == "semi" and m["sub_ledger"]["A"]["borderline"]["level_range"] == [2, 3]


def test_322_takes_from_run1():
    m = _merge([_run(0, {"A": 3}), _run(1, {"A": 2}), _run(2, {"A": 2})])
    _check_cell_from(m, "A", 1, 2)
    _check_narrative_from(m, 1)


def test_332_takes_from_run0():
    m = _merge([_run(0, {"A": 3}), _run(1, {"A": 3}), _run(2, {"A": 2})])
    _check_cell_from(m, "A", 0, 3)
    _check_narrative_from(m, 0)


# ── (a) 전부 같은 레벨이면 종전과 같은 결과(run0) ─────────────────────────────
def test_all_same_level_keeps_run0_as_before():
    runs = [_run(0, {"A": 2, "B": None}), _run(1, {"A": 2, "B": None}), _run(2, {"A": 2, "B": None})]
    m = _merge(runs)
    _check_cell_from(m, "A", 0, 2)
    _check_narrative_from(m, 0)
    assert m["level_gate"] == runs[0]["level_gate"]                       # 종전: run0 의 level_gate 그대로
    # 종전: 근거는 run 순서 합집합(중복 제거)
    assert m["sub_ledger"]["A"]["evidence"] == [
        "가짜 인용 run0 A: 목요일에 서랍 번호표를 다시 붙였습니다", "공통 인용: 창고 열쇠를 반납했습니다",
        "가짜 인용 run1 A: 목요일에 서랍 번호표를 다시 붙였습니다", "가짜 인용 run2 A: 목요일에 서랍 번호표를 다시 붙였습니다"]
    assert m["sub_ledger"]["A"]["stability"] == "stable" and m["sub_ledger"]["B"]["level_run"] is None
    assert list(m["sub_ledger"]) == ["A", "B"]


# ── 근거: 고른 run 이 앞, 나머지는 종전 순서·중복 제거 ────────────────────────
def test_evidence_order_lead_run_first_then_previous_order():
    m = _merge([_run(0, {"A": 2}), _run(1, {"A": 3}), _run(2, {"A": 3})])
    assert m["sub_ledger"]["A"]["evidence"] == [
        "가짜 인용 run1 A: 목요일에 서랍 번호표를 다시 붙였습니다", "공통 인용: 창고 열쇠를 반납했습니다",
        "가짜 인용 run0 A: 목요일에 서랍 번호표를 다시 붙였습니다", "가짜 인용 run2 A: 목요일에 서랍 번호표를 다시 붙였습니다"]


def test_dropped_run_contributes_no_evidence_and_dropped_cell_stays_empty():
    # A: 통과 2 · 탈락 · 통과 3 → 통과표 [2,3] 중앙값(낮은 쪽) 2 = run0. 탈락 run 의 인용은 없다.
    m = _merge([_run(0, {"A": 2, "B": 2}), _run(1, {"A": "X", "B": "X"}), _run(2, {"A": 3, "B": "X"})])
    a, b = m["sub_ledger"]["A"], m["sub_ledger"]["B"]
    assert a["level"] == 2 and a["level_run"] == 0 and not any("run1" in e for e in a["evidence"])
    # B: 탈락 2회 → 근거 미확보. 인용 빈 목록·level_run None 은 종전 규칙 그대로.
    assert b["stability"] == "dropped" and b["evidence"] == [] and b["level"] is None and b["level_run"] is None


# ── (b) gate_runs 는 run 순서 그대로 전부 ─────────────────────────────────────
def test_gate_runs_untouched_in_run_order():
    m = _merge([_run(0, {"A": 2}), _run(1, {"A": 3}), _run(2, {"A": 3})])
    gr = m["sub_ledger"]["A"]["gate_runs"]
    assert [g["verified_level"] for g in gr] == [2, 3, 3]
    assert [g["reason"][:11] for g in gr] == ["가짜 사유 run0 ", "가짜 사유 run1 ", "가짜 사유 run2 "]
    assert all(g["evaluated"] for g in gr) and m["sub_ledger"]["A"]["candidate_runs"] == 3


# ── (c) run 원본 dict 불변 ───────────────────────────────────────────────────
def test_run_inputs_not_mutated():
    for levels in ([2, 3, 3], [3, 2, 2], [3, 3, 2]):
        runs = [_run(i, {"A": lv, "B": 2}) for i, lv in enumerate(levels)]
        before = copy.deepcopy(runs)
        m = _merge(runs)
        assert runs == before
        # 병합 결과의 level_gate 는 어느 run 의 객체도 아니다 — 결과를 고쳐도 원본에 번지지 않는다.
        assert all(m["level_gate"] is not r["level_gate"] for r in runs)
        m["level_gate"]["A"]["reason"] = "바꿈"
        m["level_gate"]["Z"] = {}
        assert runs == before


# ── (d) 여러 칸: 일치 칸 수 최다 run, 동률이면 run0 ───────────────────────────
def test_base_is_run_with_most_matching_cells():
    # 최종 A=3(2·3·3) B=2(2·2·2) C=3(3·3·4). 일치 칸 수: run0=2(B,C), run1=3(A,B,C), run2=2(A,B) → run1.
    runs = [_run(0, {"A": 2, "B": 2, "C": 3}), _run(1, {"A": 3, "B": 2, "C": 3}), _run(2, {"A": 3, "B": 2, "C": 4})]
    m = _merge(runs)
    assert [m["sub_ledger"][s]["level"] for s in "ABC"] == [3, 2, 3]
    _check_narrative_from(m, 1)
    _check_cell_from(m, "A", 1, 3)      # 칸별로는 각자 최종 레벨을 낸 첫 run
    _check_cell_from(m, "B", 0, 2)
    _check_cell_from(m, "C", 0, 3)


def test_base_tie_goes_to_run0():
    # 최종 A=3(2·3·3) B=2(2·2·3). 일치: run0=1(B), run1=2, run2=1 → run1. 동률 사례는 아래.
    assert _merge([_run(0, {"A": 2, "B": 2}), _run(1, {"A": 3, "B": 2}), _run(2, {"A": 3, "B": 3})])["base_run"] == 1
    # 최종 A=3(3·2·3) B=2(3·2·2). 일치: run0=1(A), run1=1(B), run2=2 → run2.
    assert _merge([_run(0, {"A": 3, "B": 3}), _run(1, {"A": 2, "B": 2}), _run(2, {"A": 3, "B": 2})])["base_run"] == 2
    # run 2회(적응형에서 3회째 생략 꼴): 최종 A=2(2·3 낮은 쪽) B=2(3·2 낮은 쪽). 일치 run0=1(A), run1=1(B) → 동률 → run0.
    m = merge_outer_runs([{"k": _run(0, {"A": 2, "B": 3})}, {"k": _run(1, {"A": 3, "B": 2})}], 2)["k"]
    _check_narrative_from(m, 0)
    _check_cell_from(m, "A", 0, 2)
    _check_cell_from(m, "B", 1, 2)      # 서술은 run0 이어도 B 칸 사유·근거는 레벨 2 를 낸 run1


def test_both_unmeasured_counts_as_match():
    # B: 통과·탈락·탈락 → 최종 미측정. run0 은 B 를 측정됐다고 본 run 이라 불일치, run1·2 는 일치(둘 다 미측정).
    # 일치: run0=1(A), run1=2(A,B), run2=2 → run1.
    m = _merge([_run(0, {"A": 3, "B": 2}), _run(1, {"A": 3, "B": "X"}), _run(2, {"A": 3, "B": "X"})])
    assert m["sub_ledger"]["B"]["stability"] == "dropped"
    _check_narrative_from(m, 1)
    assert m["level_gate"]["B"]["dropped"] is True and m["level_gate"]["B"]["reason"].startswith("가짜 사유 run1 B")   # 미측정 칸은 바탕 run 것 그대로


# ── (e) 3회째가 갈린 칸만 판정한 부분 run ─────────────────────────────────────
def test_partial_third_run_never_base_but_can_supply_cell():
    # A 가 갈려(2·4) 3회째가 A 만 한정 판정(3). B 는 3회째에서 미판정(measured False·level None).
    r2 = _run(2, {"A": 3, "B": None}, eval_subs=["A"])
    runs = [{"k": _run(0, {"A": 2, "B": 2})}, {"k": _run(1, {"A": 4, "B": 2})}, {"k": r2}]
    m = merge_outer_runs(runs, 3)["k"]
    a, b = m["sub_ledger"]["A"], m["sub_ledger"]["B"]
    assert a["level"] == 3 and b["level"] == 2 and b["stability"] == "stable"     # B 는 앞 두 run 의 2표
    _check_cell_from(m, "A", 2, 3)          # A 칸 사유·근거는 최종 3 을 낸 부분 run 에서
    _check_narrative_from(m, 0)             # 서술은 전체 판정 run 가운데서(일치 run0=1·run1=1 동률 → run0), 부분 run 은 후보 아님
    assert [g["evaluated"] for g in b["gate_runs"]] == [True, True, False] and b["candidate_runs"] == 2
    assert [g["verified_level"] for g in a["gate_runs"]] == [2, 4, 3] and a["candidate_runs"] == 3
    assert m["level_gate"]["B"]["reason"].startswith("가짜 사유 run0 B") and "_eval_subs" not in m


def test_partial_third_run_with_233_picks_run1_for_everything():
    r2 = _run(2, {"A": 3, "B": None}, eval_subs=["A"])
    m = _merge([_run(0, {"A": 2, "B": 2}), _run(1, {"A": 3, "B": 2}), r2])
    _check_cell_from(m, "A", 1, 3)          # 레벨 3 을 낸 '첫' run 은 run1
    _check_narrative_from(m, 1)             # 일치 run0=1(B)·run1=2 → run1. 부분 run(일치 1)은 애초에 제외
    # 부분 run 이 미판정으로 둔 칸은 그 run 의 표가 아니다 — B 를 미측정으로 '낸' run 으로 뽑히지 않는다.
    assert pick_level_run([None, r2], "B", 2) is None and pick_level_run([None, r2], "A", 3) == 1


def test_skipped_third_run():
    m = merge_outer_runs([{"k": _run(0, {"A": 2})}, {"k": _run(1, {"A": 2})}, {"k": None}], 3)["k"]
    _check_cell_from(m, "A", 0, 2)
    _check_narrative_from(m, 0)
    assert [g["evaluated"] for g in m["sub_ledger"]["A"]["gate_runs"]] == [True, True, False]


# ── 운영 기본 꼴: outer≥1 은 판정 전용(서술 빈 문자열) ────────────────────────
def test_judge_only_runs_supply_reason_but_not_narrative():
    runs = [_run(0, {"A": 2, "B": 2}), _run(1, {"A": 3, "B": 2}, narrative=False), _run(2, {"A": 3, "B": 2}, narrative=False)]
    m = _merge(runs)
    _check_cell_from(m, "A", 1, 3)          # 사유·근거는 run1 에서(게이트는 run 마다 돈다)
    _check_narrative_from(m, 0)             # 서술은 run0 — 서술이 빈 run 을 바탕으로 삼지 않는다
    assert m["comment"] and m["reasoning_process"]["2_action"]["description"]
    # run0 이 채운 서술 칸을 하나라도 비운 run 은 후보가 아니다
    half = _run(1, {"A": 3, "B": 2})
    half["gap_analysis"] = "  "
    assert _merge([runs[0], half, runs[2]])["base_run"] == 0


def test_error_fallback_run_is_not_base():
    bad = _run(1, {"A": 3, "B": 2})
    bad["_error_fallback"] = True
    bad["_error_reason"] = "타임아웃"
    m = _merge([_run(0, {"A": 2, "B": 2}), bad, _run(2, {"A": 3, "B": 2})])
    assert m["base_run"] == 2 and m["_error_fallback"] is True and m["_error_reason"] == "타임아웃"
    # run0 이 오류 폴백이면 종전대로 run0
    bad0 = _run(0, {"A": 2, "B": 2})
    bad0["_error_fallback"] = True
    assert pick_base_run([bad0, _run(1, {"A": 3, "B": 2}), _run(2, {"A": 3, "B": 2})], {"A": 3, "B": 2}) == 0


def test_no_level_gate_anywhere_adds_no_key():
    m = _merge([_run(i, {"A": lv}, gate=False) for i, lv in enumerate([2, 3, 3])])
    assert "level_gate" not in m and m["sub_ledger"]["A"]["level_run"] == 1 and m["base_run"] == 1


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn(); print(f"  [PASS] {fn.__name__}")
    print(f"=== outer_merge P12d: {len(fns)} PASS ===")
