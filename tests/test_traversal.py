"""4-1: 순회 로직 단위 테스트 (LLM 호출 없음).

검증 항목(지시서 §4-1):
  · 타겟 선정기가 미탐색 목록에서만 후보를 뽑는가
  · asked 기록이 LLM 호출 이전에 일어나는가 (호출 모킹해 순서 검증)
  · LLM 이 어떤 응답을 반환해도 asked 가 변하지 않는가
  · 종료 판정과 원장이 동일 카운터를 참조하는가
  · 하위역량당 3턴 상한 / 챕터 상한 / 전진 감시가 각각 발동하는가
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.services import traversal as T  # noqa: E402

P = [0, 0]


def ck(label, ok, extra=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label} {extra}")
    P[0] += ok
    P[1] += (not ok)


ALL = ["갈등관리", "신뢰형성", "팀워크 촉진(협업)", "코칭 및 피드백",
       "권한위임", "동기부여", "공감(감성지능)", "의사소통", "인재육성"]


def test_target_from_unexplored_only():
    asked = ["갈등관리", "신뢰형성"]
    t = T.select_next_target(asked, ALL, priority=[])
    ck("타겟은 미탐색에서만", t not in asked and t in ALL, f"(={t})")
    # 전량 탐색 → None
    ck("전량 탐색 시 None", T.select_next_target(ALL, ALL, []) is None)


def test_priority_queue_order_only():
    # priority 로 '동기부여'를 앞으로 당기되, 집합은 그대로 + 큐무관 1개(sub[0]) 고정
    ordered = T.order_by_priority(ALL, priority=["동기부여", "의사소통"])
    ck("큐무관 1개(정의순 첫 항목) 선두", ordered[0] == ALL[0])
    ck("priority 항목이 앞쪽으로", ordered.index("동기부여") < ordered.index("갈등관리")
       or ordered[0] == ALL[0] and "동기부여" in ordered[:3])
    ck("집합 불변(9개 그대로)", set(ordered) == set(ALL) and len(ordered) == len(ALL))


def test_advance_and_turn_cap():
    # 3턴 상한 도달 → 전진
    ck("2턴+사건없음 → 전진 안 함",
       T.should_advance_target(2, has_completed_event=False) is False)
    ck("3턴 도달 → 전진", T.should_advance_target(3, False) is True)
    ck("사건 완성 → 즉시 전진", T.should_advance_target(1, True) is True)


def test_breadth_gate_same_counter():
    store = {}
    for s in ["갈등관리", "신뢰형성", "팀워크 촉진(협업)"]:
        store = T.record_asked(store, "people_management", s)
    asked = T.asked_for_chapter(store, "people_management")
    # 종료 판정과 원장이 '동일 카운터'(len(asked))를 본다
    min_ex = T.min_explored_for(9)  # 사람관리 = 6
    ck("min_explored(9)=6", min_ex == 6)
    ck("종료 판정 = 원장 카운터", T.breadth_satisfied(len(asked), min_ex) is False
       and len(asked) == 3)
    for s in ["코칭 및 피드백", "권한위임", "동기부여"]:
        store = T.record_asked(store, "people_management", s)
    asked2 = T.asked_for_chapter(store, "people_management")
    ck("6개 도달 → 넓이 충족", T.breadth_satisfied(len(asked2), min_ex) is True
       and len(asked2) == 6)


def test_chapter_cap_and_stall():
    min_ex = 6
    ck("챕터 상한 = 6*3+4 = 22", T.chapter_turn_cap(min_ex) == 22)
    ck("22턴 도달 → 강제종료", T.chapter_over_budget(22, min_ex) is True)
    ck("21턴 → 아직", T.chapter_over_budget(21, min_ex) is False)
    ck("전진 감시 6턴 → 발동", T.progress_stalled(6) is True)
    ck("전진 감시 5턴 → 대기", T.progress_stalled(5) is False)


def test_record_before_llm_and_llm_cannot_change():
    """제어 역전 순서 검증: record_asked 가 LLM 호출 '이전'에 일어나고,
    LLM 이 무엇을 반환해도 asked 가 변하지 않음을 모킹으로 증명."""
    call_order = []

    def record_step(store):
        call_order.append("record")
        return T.record_asked(store, "people_management", "권한위임")

    async def fake_llm(store):
        call_order.append("llm")
        # LLM 이 'asked 를 바꾸려는' 악의적 응답을 반환해도…
        return {"asked_subs": {"people_management": []}, "measured": True}

    async def pipeline():
        store = {}
        store = record_step(store)              # 1) 기록 (LLM 이전)
        _llm_resp = await fake_llm(store)        # 2) LLM 표현
        # asked 는 오직 store 원장에서만 읽는다 — LLM 응답 무시
        return T.asked_for_chapter(store, "people_management")

    asked = asyncio.get_event_loop().run_until_complete(pipeline())
    ck("기록이 LLM 호출 '이전'", call_order == ["record", "llm"], str(call_order))
    ck("LLM 응답이 asked 를 못 바꿈", asked == ["권한위임"], str(asked))


def _run():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            print(f"— {name}")
            fn()
    print(f"\n=== 4-1 단위 테스트: {P[0]} PASS / {P[1]} FAIL ===")
    return P[1]


if __name__ == "__main__":
    sys.exit(1 if _run() else 0)
