"""asked·anchored 원장과 우선순위 정렬 — 순수 함수(LLM/DB 없음).

(2026-11-04 BEI) 하위역량 단위 앵커 루프(select_next_target·apply_probe_turn·3턴 상한·넓이 게이트·서킷브레이커·결과/행동/일반화/
사다리 원장)는 사례 상태기계(services/bei_engine)로 대체돼 삭제됐다. 남긴 것:
  asked_subs     {chapter: [sub_name]} — 분석(reports._build_asked_subcompetencies)·self_eval·admin 이 읽는 파생 원장.
                 BEI 에서는 covered(strong) ∪ SWEEP 앵커 ∪ 여는 앵커 하위역량을 bei_engine 이 써넣는다.
  anchored_subs  {chapter: [sub_name]} — 여는 앵커·SWEEP 앵커가 실제로 나간 하위역량(report_ledger.anchor_delivered 참고용).
  order_by_priority — 정의 순서 첫 항목 고정 + priority(ALIGN 키워드) 우선.
상태는 호출자가 session.self_assessment_data 에 영속화한다.
"""
from __future__ import annotations


def order_by_priority(all_subs: list[str], priority: list[str]) -> list[str]:
    """우선순위 큐 — 순서만 바꾼다(집합은 그대로). 원래 순서의 첫 항목(정의 순서 sub[0])을 맨 앞에 고정,
    그 뒤로 priority 에 든 항목, 그 뒤로 나머지(원래 순서). 중복 제거(순서 보존)."""
    if not all_subs:
        return []
    anchor_free = all_subs[0]
    prio = [s for s in priority if s in all_subs and s != anchor_free]
    rest = [s for s in all_subs if s != anchor_free and s not in prio]
    seen, out = set(), []
    for s in [anchor_free] + prio + rest:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


def record_asked(store: dict, chapter: str, sub: str) -> dict:
    """asked_subs[chapter] 에 sub 를 (중복 없이) 추가한 새 store 반환."""
    store = dict(store or {})
    asked = dict(store.get("asked_subs") or {})
    lst = list(asked.get(chapter) or [])
    if sub and sub not in lst:
        lst.append(sub)
    asked[chapter] = lst
    store["asked_subs"] = asked
    return store


def record_anchored(store: dict, chapter: str, sub: str) -> dict:
    """실제로 앵커 질문이 나간 하위역량 원장(asked 와 분리 — asked 는 사례 매핑으로 증명된 것도 포함)."""
    store = dict(store or {})
    anc = dict(store.get("anchored_subs") or {})
    lst = list(anc.get(chapter) or [])
    if sub and sub not in lst:
        lst.append(sub)
    anc[chapter] = lst
    store["anchored_subs"] = anc
    return store


def asked_for_chapter(store: dict, chapter: str) -> list[str]:
    """이 챕터의 asked 원장. LLM 응답과 무관."""
    return list(((store or {}).get("asked_subs") or {}).get(chapter) or [])


def asked_all(store: dict) -> dict[str, list[str]]:
    return dict((store or {}).get("asked_subs") or {})
