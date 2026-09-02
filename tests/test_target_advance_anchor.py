"""T2 기록=발화 결합 회귀 테스트.

버그(3/26 사고의 반대 방향): apply_probe_turn 이 3턴 상한마다 타겟을 전진시켜
asked_subs 에 '기록'하지만, 그 턴의 instruction 이 STAR 심화형이면 LLM 이 새
하위역량 앵커로 피벗하지 않아 '기록만 있고 발화 없는' 허수가 쌓였다. 넓이
게이트가 허수를 보고 챕터를 조기 종료 → 조직관리 1개만 실측정.

수정: 타겟이 '새' 하위역량으로 전진하면(advanced_to_new_target) 그 턴 instruction
을 앵커 발화형(STAR_COMPLETE_NEW_EVENT)으로 오버라이드 → 기록=발화 결합.
불변식: (챕터 첫 앵커 1) + (전진 오버라이드 수) == asked_subs 기록 수.
"""

from diag_project.services.traversal import (
    apply_probe_turn, asked_for_chapter, advanced_to_new_target,
    breadth_satisfied, min_explored_for,
)

CH = "organization_management"
ORG_SUBS = ["비전 제시 및 공유", "전략적 사고", "변화관리(변화지향)", "혁신적 사고"]


def _emitted_anchor(cur_before, cur_after):
    """이 프로브 턴에 실제 앵커가 '지시'되는가.

    diagnoses.py 흐름과 동일: 첫 타겟 설정(cur_before=None) = CHAPTER_OPENING
    앵커, 이후 새 타겟 전진 = STAR_COMPLETE_NEW_EVENT 오버라이드 앵커.
    """
    if cur_before is None and cur_after:
        return True
    return advanced_to_new_target(cur_before, cur_after)


def _simulate(all_subs, chapter, turns, event_done=False):
    """프로브 턴을 turns 회 돌리며 (store, 앵커 발화 수 누계 목록) 반환."""
    store = {}
    anchor_count = 0
    trace = []
    for _ in range(turns):
        cur_before = (store.get("current_target") or {}).get(chapter)
        store, cur_after = apply_probe_turn(
            store, chapter, all_subs, event_done, priority=[]
        )
        if _emitted_anchor(cur_before, cur_after):
            anchor_count += 1
        asked = len(asked_for_chapter(store, chapter))
        trace.append((cur_before, cur_after, anchor_count, asked))
    return store, anchor_count, trace


# ── 1) 타겟 전진 감지 순수 함수 ──
def test_advanced_detection():
    assert advanced_to_new_target(None, "a") is False        # 챕터 첫 앵커
    assert advanced_to_new_target("a", "a") is False          # 같은 타겟 심화
    assert advanced_to_new_target("a", "b") is True           # 새 타겟 전진
    assert advanced_to_new_target("a", None) is False         # 전량 탐색(전진 X)


# ── 2) 불변식: 앵커 발화 수 == asked_subs 기록 수 (매 턴) ──
def test_record_equals_anchor_invariant():
    _, anchors, trace = _simulate(ORG_SUBS, CH, turns=20, event_done=False)
    for cur_before, cur_after, anchor_ct, asked in trace:
        assert anchor_ct == asked, (
            f"허수 발생: 앵커 {anchor_ct} != 기록 {asked} "
            f"({cur_before}->{cur_after})"
        )


# ── 3) 조직관리에서 3개 이상 앵커가 지시된다(넓이 확보) ──
def test_org_emits_at_least_three_anchors():
    # 상한(3턴)마다 전진하므로 넓이 하한(3)을 채우려면 최소 ~7턴.
    _, anchors, _ = _simulate(ORG_SUBS, CH, turns=9, event_done=False)
    assert anchors >= 3, f"조직관리 앵커가 {anchors}개뿐 — 넓이 미달"
    # 하위역량 4개 전부는 12턴이면 커버.
    _, anchors_full, _ = _simulate(ORG_SUBS, CH, turns=12, event_done=False)
    assert anchors_full == 4


# ── 4) 스톤월러(STAR 무수확)에서도 넓이 기반 종료가 작동한다 ──
def test_stonewaller_breadth_close_still_works():
    # event_done 이 끝까지 False(강한 STAR 0)여도, 상한 전진으로 asked 가
    # 쌓여 min_explored 를 채운다 → breadth_satisfied True(챕터 종료 가능).
    store, anchors, _ = _simulate(ORG_SUBS, CH, turns=9, event_done=False)
    asked = len(asked_for_chapter(store, CH))
    min_exp = min_explored_for(len(ORG_SUBS))   # = 3
    assert breadth_satisfied(asked, min_exp) is True
    # 그리고 허수가 아니라 '실제 앵커가 지시된' 만큼만 종료 근거가 된다.
    assert anchors == asked


# ── 5) 3턴 이내엔 전진하지 않아 진행 중 STAR 를 끊지 않는다 ──
def test_no_premature_advance_within_three_turns():
    store = {}
    # 턴1: 첫 타겟 설정(비전), 턴2·3: 같은 타겟 심화(전진 없음).
    seen = []
    for _ in range(3):
        cb = (store.get("current_target") or {}).get(CH)
        store, ca = apply_probe_turn(store, CH, ORG_SUBS, False, priority=[])
        seen.append((cb, ca))
    # 3턴 모두 동일 타겟(비전) — 새 타겟 전진(오버라이드) 없음.
    assert seen[0] == (None, ORG_SUBS[0])
    assert seen[1] == (ORG_SUBS[0], ORG_SUBS[0])
    assert seen[2] == (ORG_SUBS[0], ORG_SUBS[0])
    assert not advanced_to_new_target(*seen[1])
    assert not advanced_to_new_target(*seen[2])
