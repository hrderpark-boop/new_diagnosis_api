"""(2026-10-29 P2-2·P2-3) 레벨 라벨 · 근거 미확보 → 1.0('사례 미확인') 정책."""
from diag_project.services.scoring import level_label, competency_level_label, UNCONFIRMED_LABEL
from diag_project.services.report_ledger import apply_unconfirmed_policy, is_unmeasured
from diag_project.services.traversal import apply_probe_turn, MAX_TURNS_PER_SUB


def test_level_labels():
    assert [level_label(i) for i in (1, 2, 3, 4)] == ["Lv.1 인식", "Lv.2 수행", "Lv.3 관리·설계", "Lv.4 조직 확산"]
    assert level_label(None) is None and competency_level_label(2.4) == "Lv.2 수행" and competency_level_label(2.6) == "Lv.3 관리·설계"


def _comp(rows):
    return {"sub_ledger": rows, "score_breakdown": {"star_depth_bonus": 0.2, "confidence_adj": 0.0}}


def test_unconfirmed_policy_fills_cells_and_labels():
    res = {"organization_management": _comp({
        "비전 제시 및 공유": {"asked": True, "measured": True, "level": 3, "score": 3.0, "status": "measured", "gate_status": "passed"},
        "전략적 사고": {"asked": True, "measured": False, "level": None, "score": None, "status": "evidence_missing", "gate_status": "failed"},
        "변화관리(변화지향)": {"asked": False, "measured": False, "level": None, "score": None, "status": "unexplored", "gate_status": "n_a"},
        "혁신적 사고": {"asked": True, "measured": False, "level": None, "score": None, "status": "measured", "gate_status": "pending"},
    })}
    meta = {"generalized": {"organization_management": ["전략적 사고"]},
            "generalized_text": {"organization_management": {"전략적 사고": "보통 숫자를 먼저 보고 결정하는 편입니다."}},
            "generalize_probed": {"organization_management": ["전략적 사고"]},
            "probes_on_sub": {"organization_management": {"전략적 사고": 3, "비전 제시 및 공유": 3}}}
    t = apply_unconfirmed_policy(res, meta)
    led = res["organization_management"]["sub_ledger"]
    assert led["비전 제시 및 공유"]["level_label"] == "Lv.3 관리·설계" and led["비전 제시 및 공유"]["evidence_measured"]
    g = led["전략적 사고"]
    assert g["score"] == 1.0 and g["measured"] and not g["evidence_measured"] and g["unconfirmed"] and g["level_label"] == UNCONFIRMED_LABEL
    assert g["unconfirmed_kind"] == "generalized" and "평소 방식은 말씀하셨으나" in g["unconfirmed_text"] and "보통 숫자를 먼저" in g["unconfirmed_text"]
    assert g["probe_deficit"] is False
    u = led["변화관리(변화지향)"]
    assert u["score"] == 1.0 and u["unconfirmed_kind"] == "no_answer" and "사례가 확인되지 않아" in u["unconfirmed_text"] and u["probe_deficit"] is True
    p = led["혁신적 사고"]
    assert p["score"] is None and not p.get("unconfirmed")          # 검증 미완료는 도구 상태 — 보류 유지
    comp = res["organization_management"]
    assert comp["measured_count"] == 3 and comp["evidence_measured_count"] == 1 and comp["unconfirmed_count"] == 2
    assert comp["behavior_score"] == round((3.0 + 1.0 + 1.0) / 3, 2) and comp["level_label"] == "Lv.2 수행"
    assert t == {"unconfirmed_total": 2, "probe_deficit_unconfirmed": 1, "evidence_measured_total": 1, "pending_total": 1, "unconfirmed_banner": False}
    assert not is_unmeasured(comp)
    # 근거 측정 0 대역량은 정책 뒤에도 '미측정'으로 식별된다(서술 중립화 유지)
    res2 = {"self_management": _comp({"자기인식": {"asked": True, "measured": False, "status": "evidence_missing", "gate_status": "failed"}})}
    apply_unconfirmed_policy(res2, {})
    assert res2["self_management"]["sub_ledger"]["자기인식"]["score"] == 1.0 and is_unmeasured(res2["self_management"])


def test_unconfirmed_banner_at_six():
    rows = {f"s{i}": {"asked": True, "measured": False, "status": "evidence_missing", "gate_status": "failed"} for i in range(6)}
    t = apply_unconfirmed_policy({"people_management": _comp(rows)}, {})
    assert t["unconfirmed_total"] == 6 and t["unconfirmed_banner"]


def test_probes_on_sub_ledger():
    subs = ["a", "b"]
    store, cur = apply_probe_turn({}, "work_management", subs, event_done=False)
    assert cur == "a" and store["probes_on_sub"]["work_management"]["a"] == 1
    store, _ = apply_probe_turn(store, "work_management", subs, event_done=False)
    store, _ = apply_probe_turn(store, "work_management", subs, event_done=False)
    assert store["probes_on_sub"]["work_management"]["a"] == MAX_TURNS_PER_SUB
    store, cur = apply_probe_turn(store, "work_management", subs, event_done=False)
    assert cur == "b" and store["probes_on_sub"]["work_management"] == {"a": 3, "b": 1}
