"""T-E: 중단·재개 실증 — 원장(self_assessment_data) 복원.

김보통 세션은 무중단 완주해 재개 경로가 실제로는 검증되지 않았다. 영속화
코드가 있는 것과 복원이 동작하는 것은 다르다. 여기서는 프로덕션과 '동일한'
순회 스텝(traversal.apply_probe_turn)을 돌리다가 챕터 중간에서 store 를
JSON 으로 직렬화(=DB 영속) 후 다시 로드(=재개)하고, 계속 진행했을 때:
  · asked_subs / current_target / turns_on_target 이 정확히 복원되는가
  · 재개 세션의 최종 원장이 무중단 세션과 '동일'한가
를 결정론적으로 검증한다.
"""
import copy
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.services.traversal import (  # noqa: E402
    apply_probe_turn, asked_for_chapter,
)

P = [0, 0]
CH = "people_management"
SUBS = ["갈등관리", "신뢰형성", "팀워크 촉진(협업)", "코칭 및 피드백",
        "권한위임", "동기부여", "공감(감성지능)", "의사소통", "인재육성"]
# 각 턴의 event_done 시퀀스(대부분 미완성, 가끔 완성) — 15턴
EVENTS = [False, False, False, False, True, False, False, False,
          True, False, False, False, False, True, False]


def ck(label, ok, extra=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label} {extra}")
    P[0] += ok
    P[1] += (not ok)


def _run(store, turns):
    """turns 개의 프로브 턴을 순차 적용, (store, targets[]) 반환."""
    targets = []
    for i in range(turns):
        store, cur = apply_probe_turn(store, CH, SUBS, EVENTS[i], priority=[])
        targets.append(cur)
    return store, targets


def test_uninterrupted_vs_resumed_identical():
    # (A) 무중단 15턴
    full_store, full_targets = _run({}, len(EVENTS))

    # (B) 7턴 진행 → JSON 직렬화(영속) → 로드(재개) → 나머지 8턴
    part_store, part_targets = _run({}, 7)
    persisted = json.dumps(part_store, ensure_ascii=False)          # DB 저장
    resumed_store = json.loads(persisted)                          # 재개 로드

    # 복원 검증
    ck("재개: asked_subs 복원",
       asked_for_chapter(resumed_store, CH)
       == asked_for_chapter(part_store, CH))
    ck("재개: current_target 복원",
       resumed_store.get("current_target", {}).get(CH)
       == part_store.get("current_target", {}).get(CH))
    ck("재개: turns_on_target 복원",
       resumed_store.get("turns_on_target", {}).get(CH)
       == part_store.get("turns_on_target", {}).get(CH))

    # 나머지 8턴 이어서
    for i in range(7, len(EVENTS)):
        resumed_store, cur = apply_probe_turn(
            resumed_store, CH, SUBS, EVENTS[i], priority=[])
        part_targets.append(cur)

    # 최종 원장이 무중단과 동일한가
    ck("최종 asked 동일",
       asked_for_chapter(resumed_store, CH) == asked_for_chapter(full_store, CH))
    ck("최종 current_target 동일",
       resumed_store.get("current_target") == full_store.get("current_target"))
    ck("최종 turns_on_target 동일",
       resumed_store.get("turns_on_target") == full_store.get("turns_on_target"))
    ck("타겟 시퀀스 동일", part_targets == full_targets)


def test_resume_does_not_duplicate_asked():
    """재개 직후 첫 턴이 이미 기록된 하위역량을 '중복' 기록하지 않는지."""
    store, _ = _run({}, 5)
    before = list(asked_for_chapter(store, CH))
    store2 = json.loads(json.dumps(store, ensure_ascii=False))
    # 재개 후 한 턴(전진이 아닌 turns 증가 케이스 유도: event_done=False)
    store2, _ = apply_probe_turn(store2, CH, SUBS, False, priority=[])
    after = asked_for_chapter(store2, CH)
    ck("재개 후 asked 무중복", len(after) == len(set(after))
       and after[:len(before)] == before)


def test_abort_midway_keeps_partial_ledger():
    """의심형 중도 이탈처럼 3턴만에 끊겨도 부분 원장이 온전히 남는가."""
    store, _ = _run({}, 3)
    persisted = json.loads(json.dumps(store, ensure_ascii=False))
    asked = asked_for_chapter(persisted, CH)
    ck("중도 이탈 부분 원장 보존", 1 <= len(asked) <= 3
       and persisted.get("current_target", {}).get(CH) in SUBS)


def _main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            print(f"— {name}")
            fn()
    print(f"\n=== T-E 재개 실증: {P[0]} PASS / {P[1]} FAIL ===")
    return P[1]


if __name__ == "__main__":
    sys.exit(1 if _main() else 0)
