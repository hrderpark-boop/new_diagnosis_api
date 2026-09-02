"""하위역량 순회 — 결정론적 asked 신호 (제어 역전).

핵심 원칙(T2 완결 지시서 §0): 관측이 아니라 지시.
  백엔드가 다음 타겟 sub_key 를 결정 → asked 로 기록(LLM 호출 이전) →
  그 앵커를 프롬프트에 주입 → LLM 은 표현만. asked 는 LLM 응답 이전에 확정되며
  LLM 응답이 무엇이든 되돌리거나 덮어쓰지 않는다.

이 모듈은 순수 함수만 담는다(LLM/DB 없음). 상태는 호출자가
session.self_assessment_data 에 영속화한다:
  asked_subs      : {chapter_key: [sub_name, ...]}   ← asked 원장(유일 소스)
  current_target  : {chapter_key: sub_name}
  turns_on_target : {chapter_key: int}
"""

import math

MAX_TURNS_PER_SUB = 3          # 앵커 1 + 구체화 폴백 1 + 심화 1
CHAPTER_TURN_SLACK = 4         # 챕터 상한 = min_explored*3 + 4
STALL_WATCHDOG_TURNS = 6       # 연속 N턴 asked 미증가 → 강제 전진


def min_explored_for(sub_count: int) -> int:
    """넓이 하한 = max(3, ceil(n*0.6))."""
    return max(3, math.ceil(sub_count * 0.6))


def chapter_turn_cap(min_explored: int) -> int:
    """챕터당 턴 상한 = min_explored*3 + 여유."""
    return min_explored * MAX_TURNS_PER_SUB + CHAPTER_TURN_SLACK


def order_by_priority(
    all_subs: list[str], priority: list[str]
) -> list[str]:
    """우선순위 큐 — 순서만 바꾼다(집합은 그대로).

    §1-3: 초반 키워드 편향 방지 — 각 대역량에서 '최소 1개는 큐 순서와 무관하게'.
      → 원래 순서의 첫 항목(정의 순서 sub[0])을 맨 앞에 고정(큐 무관 1개),
        그 뒤로 priority 에 든 항목, 그 뒤로 나머지(원래 순서).
    """
    if not all_subs:
        return []
    anchor_free = all_subs[0]                       # 큐와 무관하게 최소 1개
    prio = [s for s in priority if s in all_subs and s != anchor_free]
    rest = [s for s in all_subs if s != anchor_free and s not in prio]
    ordered = [anchor_free] + prio + rest
    # 중복 제거(순서 보존)
    seen, out = set(), []
    for s in ordered:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def select_next_target(
    asked_subs: list[str], all_subs: list[str], priority: list[str],
) -> str | None:
    """미탐색(asked=False) 하위역량 중 우선순위 순서로 다음 타겟. 없으면 None.

    후보는 '미탐색 목록에서만' 뽑는다(이미 asked 는 제외).
    """
    asked_set = set(asked_subs or [])
    for sub in order_by_priority(all_subs, priority):
        if sub not in asked_set:
            return sub
    return None


def should_advance_target(
    turns_on_target: int, has_completed_event: bool,
    max_turns_per_sub: int = MAX_TURNS_PER_SUB,
) -> bool:
    """현재 타겟에서 다음 타겟으로 넘어갈 시점인가.

    STAR 사건이 완성됐거나(충분히 들음), 하위역량당 턴 상한 도달 시 전진.
    """
    return bool(has_completed_event) or turns_on_target >= max_turns_per_sub


def advanced_to_new_target(cur_before: str | None, cur_after: str | None) -> bool:
    """apply_probe_turn 이 '새' 하위역량으로 타겟을 전진시켰는가.

    True 면 그 턴은 앵커 발화형(STAR_COMPLETE_NEW_EVENT)으로 지시돼야
    한다(§T2 기록=발화 결합 — 기록만 하고 앵커를 안 던지면 넓이 게이트가
    허수를 본다). cur_before is None 이면 챕터 첫 앵커(CHAPTER_OPENING
    템플릿)이므로 전진 오버라이드 대상이 아니다(False).
    """
    return bool(cur_after and cur_before is not None and cur_after != cur_before)


def breadth_satisfied(asked_count: int, min_explored: int) -> bool:
    """넓이 게이트 — 챕터 종료 판정과 원장이 '동일 카운터'를 본다(§1-2)."""
    return asked_count >= min_explored


def chapter_over_budget(chapter_turn_count: int, min_explored: int) -> bool:
    """챕터 턴 상한 초과 → 강제 종료(미탐색은 그대로 남긴다)."""
    return chapter_turn_count >= chapter_turn_cap(min_explored)


def progress_stalled(turns_since_asked_increase: int) -> bool:
    """전진 감시 — 연속 N턴 asked 미증가 → 강제 전진 신호."""
    return turns_since_asked_increase >= STALL_WATCHDOG_TURNS


# ── asked 원장 조작 (순수) — 호출자가 반환값을 영속화한다 ──
LEDGER_KEYS = ("asked_subs", "current_target", "turns_on_target")


def snapshot_ledger(store: dict) -> dict:
    """프로브 스텝 '직전'의 원장 3키를 깊은 복사로 보관한다(H5 롤백용)."""
    import copy
    return {k: copy.deepcopy((store or {}).get(k)) for k in LEDGER_KEYS}


def restore_ledger(store: dict, snapshot: dict) -> dict:
    """H5: LLM 호출이 실패해 앵커가 실제로 발화되지 못한 턴의 원장 전진을 되돌린다.

    '기록=발화' 결합의 예외 구멍: apply_probe_turn 은 LLM 호출 이전에 asked 를
    기록하는데, LLM 이 실패하면 사과 폴백 문장만 나가고 앵커는 나가지 않는다.
    이때 기록을 남기면 넓이 게이트가 허수를 본다. 원장 3키만 스냅샷으로 되돌리고
    나머지 키(참여이탈 카운터 등)는 건드리지 않는다. 텍스트 확인 방식이 아니라
    '호출 실패'라는 시스템 사실에만 반응한다.
    """
    store = dict(store or {})
    for k in LEDGER_KEYS:
        v = (snapshot or {}).get(k)
        if v is None:
            store.pop(k, None)
        else:
            store[k] = v
    return store


def record_asked(store: dict, chapter: str, sub: str) -> dict:
    """asked_subs[chapter] 에 sub 를 (중복 없이) 추가한 새 store 반환.
    반드시 LLM 호출 '이전'에 호출한다."""
    store = dict(store or {})
    asked = dict(store.get("asked_subs") or {})
    lst = list(asked.get(chapter) or [])
    if sub and sub not in lst:
        lst.append(sub)
    asked[chapter] = lst
    store["asked_subs"] = asked
    return store


def asked_for_chapter(store: dict, chapter: str) -> list[str]:
    """이 챕터의 asked 원장(유일 소스). LLM 응답과 무관."""
    return list(((store or {}).get("asked_subs") or {}).get(chapter) or [])


def asked_all(store: dict) -> dict[str, list[str]]:
    return dict((store or {}).get("asked_subs") or {})


def apply_probe_turn(
    store: dict, chapter: str, all_subs: list[str],
    event_done: bool, priority: list[str] | None = None,
) -> tuple[dict, str | None]:
    """프로브 턴 1회의 결정론적 순회 스텝 (제어 역전의 핵심).

    현재 타겟이 없거나 전진 시점이면 다음 미탐색 하위역량을 타겟으로 정해
    asked 로 '기록'(LLM 호출 이전)하고 turns 를 0 으로. 아니면 turns 를 +1.
    반환: (갱신된 store, 현재 타겟 sub_key).

    diagnoses.py 프로브 스텝과 재개 테스트(T-E)가 '동일 로직'을 쓰도록 순수
    함수로 뽑았다. store 는 그대로 self_assessment_data 에 영속화된다.
    """
    store = dict(store or {})
    asked = asked_for_chapter(store, chapter)
    cur = (store.get("current_target") or {}).get(chapter)
    turns = (store.get("turns_on_target") or {}).get(chapter, 0)

    if cur is None or should_advance_target(turns, event_done):
        target = select_next_target(asked, all_subs, priority or [])
        if target:
            store = record_asked(store, chapter, target)
            store.setdefault("current_target", {})[chapter] = target
            # 🧭 앵커(기록) 턴 자체가 이 하위역량의 '1번째 턴'이다. turns=1 로
            #   시작해야 하위역량당 정확히 MAX_TURNS_PER_SUB(3) 프로브 턴을
            #   소비하고 전진한다(0 으로 시작하면 4턴 소비 → 넓이 부족).
            #   → 넓이 우선: 깊이(STAR)가 연속 실패해도 3턴이면 다음 하위역량으로
            #     전진해 커버리지를 확보한다(커버리지 > 깊이).
            store.setdefault("turns_on_target", {})[chapter] = 1
            cur = target
        # target 이 None(전량 탐색)이면 현재 타겟 유지
    else:
        store.setdefault("turns_on_target", {})[chapter] = turns + 1
    return store, cur
