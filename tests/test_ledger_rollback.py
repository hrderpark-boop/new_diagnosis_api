"""H5: LLM 호출 실패 턴의 asked 원장 롤백 — '기록=발화' 결합의 예외 구멍 봉합.

apply_probe_turn 은 LLM 호출 '이전'에 asked 를 기록한다(T2 제어 역전). LLM 이
실패하면 사과 폴백만 나가고 앵커는 발화되지 않으므로, 그 턴의 전진을 스냅샷으로
되돌려야 넓이 게이트가 허수를 보지 않는다. 원장 3키만 되돌리고 다른 키는 유지.
"""
from diag_project.services.traversal import (
    LEDGER_KEYS, apply_probe_turn, asked_for_chapter, restore_ledger,
    snapshot_ledger,
)

CH = "organization_management"
SUBS = ["비전 제시 및 공유", "전략적 사고", "변화관리(변화지향)", "혁신적 사고"]


def _advance(store, times):
    for _ in range(times):
        store, _ = apply_probe_turn(store, CH, SUBS, False, priority=[])
    return store


def test_rollback_restores_first_anchor_turn():
    store = {"probe_cycles": 3}                      # 원장 외 키
    snap = snapshot_ledger(store)
    store, cur = apply_probe_turn(store, CH, SUBS, False, priority=[])
    assert asked_for_chapter(store, CH) == [SUBS[0]] and cur == SUBS[0]
    store = restore_ledger(store, snap)
    assert asked_for_chapter(store, CH) == []
    for k in LEDGER_KEYS:
        assert k not in store                        # 없던 키는 없던 대로
    assert store["probe_cycles"] == 3                # 다른 키는 그대로


def test_rollback_restores_target_advance():
    # 3턴 소비 후 4턴째 전진(두 번째 하위역량 기록) → 실패 → 롤백.
    store = _advance({}, 3)
    assert asked_for_chapter(store, CH) == [SUBS[0]]
    snap = snapshot_ledger(store)
    store, cur = apply_probe_turn(store, CH, SUBS, False, priority=[])
    assert cur == SUBS[1] and asked_for_chapter(store, CH) == SUBS[:2]
    store = restore_ledger(store, snap)
    assert asked_for_chapter(store, CH) == [SUBS[0]]
    assert store["current_target"][CH] == SUBS[0]
    assert store["turns_on_target"][CH] == 3


def test_snapshot_is_deep_copy():
    store = _advance({}, 1)
    snap = snapshot_ledger(store)
    store["asked_subs"][CH].append("오염")
    assert "오염" not in snap["asked_subs"][CH]


def test_rollback_does_not_touch_other_keys():
    store = _advance({"disengagement_streak": 2, "last_refusal": False}, 2)
    snap = snapshot_ledger(store)
    store, _ = apply_probe_turn(store, CH, SUBS, False, priority=[])
    store["disengagement_streak"] = 3                # 롤백 사이 다른 키 변경
    store = restore_ledger(store, snap)
    assert store["disengagement_streak"] == 3
    assert store["turns_on_target"][CH] == 2
