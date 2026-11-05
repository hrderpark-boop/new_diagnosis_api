"""(2026-10-29 P2-2·P2-3) 레벨 라벨 · 근거 미확보 → 1.0('사례 미확인') 정책."""
from diag_project.services.scoring import level_label, competency_level_label, UNCONFIRMED_LABEL
from diag_project.services.report_ledger import apply_unconfirmed_policy, is_unmeasured


def test_level_labels():
    assert [level_label(i) for i in (1, 2, 3, 4)] == ["Lv.1 인식", "Lv.2 수행", "Lv.3 관리·설계", "Lv.4 조직 확산"]
    assert level_label(None) is None and competency_level_label(2.4) == "Lv.2 수행" and competency_level_label(2.6) == "Lv.3 관리·설계"


def _comp(rows):
    return {"sub_ledger": rows, "score_breakdown": {"star_depth_bonus": 0.2, "confidence_adj": 0.0}}




def test_unconfirmed_banner_at_six():
    rows = {f"s{i}": {"asked": True, "measured": False, "status": "evidence_missing", "gate_status": "failed"} for i in range(6)}
    t = apply_unconfirmed_policy({"people_management": _comp(rows)}, {})
    assert t["unconfirmed_total"] == 6 and t["unconfirmed_banner"]




