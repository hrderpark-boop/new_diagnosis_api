"""BEI 사례 기반 챕터 상태기계 — 순수 함수 (2026-11-04, docs/design_bei_2026-11.md §1~§4).

챕터 = DIAGNOSIS_CONFIRM → ALIGN → EPISODE(×2~3) → SWEEP → CLOSE.
  · EPISODE: 사례 하나를 6슬롯(상황·시점 / 리더 행동 / 상대 반응 / 결과 / 판단 기준 / 다시 한다면·배운 것)이 찰 때까지 듣는다.
    종료 = 6/6 또는 사례 리더 턴 8 또는 챕터 예산 도달. 종료 시 Haiku 다중 라벨(services/slot_judge.map_episode)로 하위역량에 배정.
  · SWEEP: covered(strong) 가 없는 하위역량만 앵커 1 + 후속 ≤1. (2026-11-10 P9-1) 챕터당 상한 없음 — 종료 조건은 "모든 하위역량 asked" 하나.
  · 예산 B(챕터 리더 턴): 조직 16 / 성과 18 / 사람 24 / 일 18 / 자기 16. 3번째 사례는 미커버 ≥2 이고 남은 턴 − 미질문 수 ≥ 5 일 때만(사람관리는 사례 2개까지).
  · (P9-1) 예약: 미질문 하위역량 수 × 1턴은 항상 남긴다. 사례가 예약을 침범하면 6슬롯 전이라도 닫는다(status=reserve).

상태는 전부 session.self_assessment_data(JSON) 안의 키에 둔다(호출자가 영속화):
  chapter_state[ch]  confirm|align|episode|sweep|close
  bei_turns[ch]      BEI 리더 턴 수(ALIGN 앵커에 대한 첫 답부터)
  episodes[ch]       [{idx, kind: episode|sweep, opener_sub, opener_key, status: open|done|no_case|budget|switched|sweep_done,
                       leader_turns, retry, slot_used, first_turn_index, slots{key:{status,quote}}, labels[{sub,strength,quote}]}]
  covered[ch]        {sub: [{episode, strength, quote}]}   — strong 만. "사례 N 에서 증명"
  weak[ch]           {sub: [episode_idx]}                  — SWEEP 다리 힌트("아까 사례 N 에서 살짝 나왔는데")
  sweep_asked[ch]    [sub]  unconfirmed[ch] [sub]  no_case_subs[ch] [sub]
  asked_subs[ch]     covered(strong) ∪ sweep_asked ∪ 여는 앵커 하위역량 — 분석(reports._build_asked_subcompetencies)이 읽는 파생값
  anchored_subs[ch]  여는 앵커·SWEEP 앵커가 실제로 나간 하위역량
이 모듈은 LLM·DB 를 모르고, 리더 발화 원문 검증(verbatim)만 문자열로 한다.
"""
from __future__ import annotations

import copy
import re

SLOT_KEYS: tuple[str, ...] = ("context", "action", "reaction", "result", "criterion", "reflection")
SLOT_LABELS: dict[str, str] = {
    # (2026-11-13 P12b-4) '상대'·'선택지' 같은 낱말이 출력에 그대로 옮겨졌다("상대인 최운영 씨는", "버리신 다른 선택지") — 그렇게 옮겨 쓸 수 없는 표현으로
    "context": "상황·시점", "action": "리더 행동", "reaction": "반응", "result": "결과",
    "criterion": "판단 기준", "reflection": "다시 한다면·배운 것",
}
# 사례 카드에 주는 '이번 턴 질문 방향' 힌트 — 문장은 LLM 이 쓴다(고정 문장 아님).
SLOT_HINTS: dict[str, str] = {
    "context": "언제, 누구와, 무엇이 걸려 있던 장면이었는지(때와 함께 있던 사람이 둘 다 나오게)",
    # (2026-11-14 P12c-2) 종전 힌트('그때 리더님이 직접 한 말·결정·행동 하나')를 LLM 이 그대로 따라 써 "그 자리에서 리더님이 직접 …" 이 두 번 나갔다(p12b) —
    #   앞의 받는 문장에 기대는 질문이라, 받는 문장이 길이 기준으로 지워지면 무엇을 묻는지 알 수 없었다. 방금 들은 일의 낱말을 질문에 넣게 한다.
    "action": "리더가 방금 말한 일(누가 무엇을 했을 때인지)을 질문 문장 안에 넣고, 그 일에서 리더 본인이 한 말·결정·행동 하나를 묻는다(팀이 한 일·방침 설명이 아니라)",
    # (2026-11-14 P12d-4) 힌트의 낱말('그 사람', '하지 않기로 한 것')이 출력에 옮겨졌다 — 코치가 그대로 말할 수 없는 설명 꼴로 쓰고, 사람은 이름으로 받게 한다
    "reaction": "(들은 쪽이 어떻게 받았는지: 말·행동·태도의 달라짐) 사람을 가리킬 때는 리더가 부른 이름·직함을 그대로 쓰고 대명사로 바꾸지 않는다",
    "result": "그 뒤 무엇이 달라졌는지(정성적 변화도 결과로 받는다)",
    "criterion": "(판단의 근거: 그렇게 정한 까닭, 견주어 본 다른 길) 리더가 내린 결정의 낱말을 넣어 묻는다",
    "reflection": "지금 돌아보면 바꿀 점이나 배운 것 하나",
}
SLOT_STATUSES = ("empty", "partial", "filled")

EPISODE_MAX_LEADER_TURNS = 6          # (2026-11-13 P12b-2) 8 → 6, 전 영역 — 아직 묻지 않은 칸마다 2턴을 남기고도 사례 2개가 들어가게(P12 는 9칸 영역만 6이었다)
RESERVE_PER_UNASKED = 2               # (P12-3) 아직 묻지 않은 칸의 예약 — 칸당 1턴 → 2턴
SLOT_ASK_MAX = 2                      # (P12-2) 같은 것(슬롯)을 채우려는 질문은 사례당 2회까지 — 그래도 안 나오면 다음 것으로
EPISODE_MIN_LEADER_TURNS = 4          # (2026-11-05 2단계 판정 1) 6/6 이 4턴 전에 차도 "장면 구체화" 턴을 더 묻는다
EPISODE_MIN = 2
EPISODE_MAX = 3
EPISODE_OPEN_MIN_REMAINING = 5        # 사례 하나 더 열려면 최소 이만큼 남아야 한다(SWEEP 예비는 별도)
EPISODE_RETRY_MAX = 1                 # (P7-1) 여는 질문에 사례가 없으면(incident=no) 더 작게·다른 각도로 1회만(NO_CASE_REFRAME) — 하위역량당 최대 2턴
EPISODE_STALL_TURNS = 2               # (P7-1) 사례 중 2턴 연속 슬롯 진전 0 이면 8턴 전에 조기 종료(status=stalled)
SWEEP_MAX_PER_CHAPTER = None          # (2026-11-10 P9-1) 챕터당 SWEEP 상한 삭제 — 11/10 Jessica 사람관리에서 동기부여·공감을 묻지 않고 1.0 이 기록됐다
CHAPTER_BUDGET: dict[str, int] = {
    "organization_management": 16, "performance_management": 18, "people_management": 24,   # (P9-1) 사람관리 20 → 24(하위역량 9개)
    "work_management": 18, "self_management": 16,
}
CHAPTER_EPISODE_MAX: dict[str, int] = {"people_management": 2}   # (P9-1) 사람관리는 사례 2개까지 — 나머지 턴은 전수 질문에 쓴다
DEFAULT_BUDGET = 18

STATE_CONFIRM, STATE_ALIGN, STATE_EPISODE, STATE_SWEEP, STATE_CLOSE = "confirm", "align", "episode", "sweep", "close"
BEI_INSTRUCTIONS = frozenset({"EPISODE_OPEN", "EPISODE_PROBE", "NO_CASE_REFRAME", "SWEEP_ANCHOR", "SWEEP_FOLLOWUP"})   # (P7-1) EPISODE_RETRY → NO_CASE_REFRAME
# 이 instruction 의 코치 턴 뒤 리더 답은 BEI 리더 턴이다(ALIGN 앵커 답 포함)
BEI_ANSWER_AFTER = BEI_INSTRUCTIONS | {"COMPETENCY_ALIGN"}
LEDGER_KEYS = ("chapter_state", "bei_turns", "episodes", "covered", "weak", "sweep_asked", "unconfirmed",
               "no_case_subs", "asked_subs", "anchored_subs", "repeat_subs")

_NO_CASE_RE = re.compile(r"(없(어요|습니다|는데요|네요|었어요|었습니다|는 것 같|을 것 같)|기억(이|은)?\s*(안|잘 안|나지 않)|떠오르(지|는 게) 않|딱히|별로 없|생각(이|은) 안 나)")


# ── 기본 조회 ─────────────────────────────────────────────────────────────────
def chapter_budget(chapter: str | None) -> int:
    return CHAPTER_BUDGET.get(chapter or "", DEFAULT_BUDGET)


def chapter_state(store: dict | None, chapter: str | None) -> str:
    return ((store or {}).get("chapter_state") or {}).get(chapter or "", STATE_CONFIRM)


def set_chapter_state(store: dict, chapter: str, state: str) -> dict:
    cs = dict(store.get("chapter_state") or {})
    cs[chapter] = state
    store["chapter_state"] = cs
    return store


def bei_turns(store: dict | None, chapter: str | None) -> int:
    return int(((store or {}).get("bei_turns") or {}).get(chapter or "", 0) or 0)


def remaining(store: dict | None, chapter: str | None) -> int:
    return chapter_budget(chapter) - bei_turns(store, chapter)


def episodes(store: dict | None, chapter: str | None) -> list[dict]:
    return list(((store or {}).get("episodes") or {}).get(chapter or "", []) or [])


def current_episode(store: dict | None, chapter: str | None) -> dict | None:
    """상태가 open 인 마지막 사례(사례·SWEEP 항목 공통). 없으면 None."""
    eps = episodes(store, chapter)
    return next((e for e in reversed(eps) if e.get("status") == "open"), None)


def real_episodes(store: dict | None, chapter: str | None) -> list[dict]:
    """SWEEP 항목을 뺀 사례만(폐기된 no_case 포함)."""
    return [e for e in episodes(store, chapter) if e.get("kind", "episode") == "episode"]


def counted_episodes(store: dict | None, chapter: str | None) -> int:
    """사례 수 — 리더 턴 3 이상 들은 사례(no_case 로 바로 폐기된 것은 세지 않는다)."""
    return sum(1 for e in real_episodes(store, chapter)
               if e.get("status") in ("done", "budget", "switched", "stalled", "reserve", "turns") or int(e.get("leader_turns") or 0) >= 3)


def empty_slots() -> dict:
    return {k: {"status": "empty", "quote": ""} for k in SLOT_KEYS}


def filled_slots(ep: dict | None) -> list[str]:
    return [k for k in SLOT_KEYS if ((ep or {}).get("slots") or {}).get(k, {}).get("status") == "filled"]


def unfilled_slots(ep: dict | None) -> list[str]:
    """아직 안 찬 슬롯(우선순위 순). '다시 한다면·배운 것'은 결과가 찬 뒤(또는 결과를 두 번 물은 뒤)에만 묻는다."""
    slots = (ep or {}).get("slots") or {}
    out = [k for k in SLOT_KEYS if slots.get(k, {}).get("status") != "filled"]
    if "reflection" in out and slots.get("result", {}).get("status") != "filled" and slot_asks(ep, "result") < SLOT_ASK_MAX:
        out.remove("reflection")
    return out


def slot_asks(ep: dict | None, slot: str) -> int:
    return int((((ep or {}).get("slot_asks") or {}).get(slot)) or 0)


def next_slot(ep: dict | None) -> str | None:
    """(P12-2) 이번 턴에 물을 것 — 아직 안 찬 것 가운데 이 사례에서 두 번 묻지 않은 첫 항목. 남은 것을 모두 두 번씩 물었으면 None."""
    return next((k for k in unfilled_slots(ep) if slot_asks(ep, k) < SLOT_ASK_MAX), None)


def bump_slot_ask(ep: dict, slot: str | None) -> dict:
    """이번 턴의 질문이 향하는 것(ask_slot)을 적고 그 횟수를 올린다."""
    ep = dict(ep)
    if slot:
        asks = dict(ep.get("slot_asks") or {})
        asks[slot] = int(asks.get(slot) or 0) + 1
        ep["slot_asks"] = asks
    ep["ask_slot"] = slot
    return ep


def ask_slot(ep: dict | None) -> str:
    """이번 턴 질문이 향하는 것 — 적어 둔 것(ask_slot)이 아직 안 찼으면 그것, 아니면 안 찬 첫 항목."""
    un = unfilled_slots(ep)
    cur = (ep or {}).get("ask_slot")
    return cur if cur in un else (un[0] if un else "reflection")


def episode_turn_max(n_subs: int | None = None) -> int:
    return EPISODE_MAX_LEADER_TURNS          # (P12b-2) 칸 수와 무관하게 6


def reserve_turns(store: dict | None, chapter: str | None, all_subs: list[str] | None) -> int:
    """아직 한 번도 묻지 않은 칸을 위해 남겨 둘 턴 수(칸당 2턴)."""
    return RESERVE_PER_UNASKED * len(unasked(store, chapter, list(all_subs or [])))


def is_no_case_text(text: str | None) -> bool:
    """결정론 보조 판정 — 짧은 답에 '없다·기억 안 난다' 표지. 슬롯 판정(LLM)의 no_case 와 OR."""
    t = (text or "").strip()
    from diag_project.services.short_input import is_decline_word as _idw_b
    if _idw_b(t):                         # (2026-11-12 P11-A2) '놉'·'ㄴㄴ'·'아니' — 있었느냐는 질문에 없다는 답
        return True
    return bool(t) and len(t.replace(" ", "")) <= 40 and bool(_NO_CASE_RE.search(t))


# ── 사례 열기·턴 기록 ─────────────────────────────────────────────────────────
def _set_episodes(store: dict, chapter: str, eps: list[dict]) -> dict:
    all_eps = dict(store.get("episodes") or {})
    all_eps[chapter] = eps
    store["episodes"] = all_eps
    return store


def new_episode(store: dict, chapter: str, opener_sub: str | None, opener_key: str | None, *,
                kind: str = "episode", first_turn_index: int | None = None) -> tuple[dict, dict]:
    """새 사례(또는 SWEEP 항목)를 open 으로 추가하고 (store, ep) 를 돌려준다. 여는 앵커 하위역량은 asked·anchored 에 기록."""
    eps = episodes(store, chapter)
    idx = 1 + sum(1 for e in eps if e.get("kind", "episode") == kind)
    ep = {
        "idx": idx, "kind": kind, "opener_sub": opener_sub, "opener_key": opener_key, "status": "open",
        "leader_turns": 0, "retry": 0, "slot_used": False, "first_turn_index": first_turn_index,
        "slots": empty_slots(), "labels": [],
    }
    eps.append(ep)
    store = _set_episodes(store, chapter, eps)
    if opener_sub:
        store = _add_to_list(store, "anchored_subs", chapter, opener_sub)
        store = _add_to_list(store, "asked_subs", chapter, opener_sub)
        if kind == "sweep":
            store = _add_to_list(store, "sweep_asked", chapter, opener_sub)
    return store, ep


def update_episode(store: dict, chapter: str, ep: dict) -> dict:
    eps = episodes(store, chapter)
    for i, e in enumerate(eps):
        if e.get("idx") == ep.get("idx") and e.get("kind", "episode") == ep.get("kind", "episode"):
            eps[i] = ep
            break
    return _set_episodes(store, chapter, eps)


def record_leader_turn(store: dict, chapter: str, ep: dict | None, *, turn_index: int | None = None) -> tuple[dict, dict | None]:
    """BEI 리더 턴 1 소비: bei_turns +1, 열린 사례 leader_turns +1."""
    bt = dict(store.get("bei_turns") or {})
    bt[chapter] = int(bt.get(chapter, 0) or 0) + 1
    store["bei_turns"] = bt
    if ep is not None:
        ep = dict(ep)
        ep["leader_turns"] = int(ep.get("leader_turns") or 0) + 1
        if ep.get("first_turn_index") is None and turn_index is not None:
            ep["first_turn_index"] = turn_index
        store = update_episode(store, chapter, ep)
    return store, ep


# ── 슬롯 병합 ─────────────────────────────────────────────────────────────────
def _norm(t: str | None) -> str:
    return re.sub(r"[\s\.,!?…:;'\"“”‘’()\[\]{}·\-—–]+", "", t or "")


def quote_in_text(quote: str | None, leader_text: str | None, min_chars: int = 4) -> bool:
    q = _norm(quote)
    return len(q) >= min_chars and q in _norm(leader_text)


def merge_slots(old: dict | None, judged: dict | None, leader_text: str | None) -> dict:
    """판정 결과를 기존 슬롯에 결정론적으로 병합.
    filled 는 되돌리지 않는다(sticky). 인용(quote)이 리더 원문에 없으면 filled → partial 로 강등(지어낸 근거 금지)."""
    out = {k: dict((old or {}).get(k) or {"status": "empty", "quote": ""}) for k in SLOT_KEYS}
    for k in SLOT_KEYS:
        j = (judged or {}).get(k) or {}
        st = str(j.get("status") or "empty").lower()
        if st not in SLOT_STATUSES:
            st = "empty"
        quote = str(j.get("quote") or "").strip()[:160]
        if st == "filled" and quote and not quote_in_text(quote, leader_text):
            st = "partial"
        rank = {"empty": 0, "partial": 1, "filled": 2}
        cur_rank = rank.get(out[k].get("status") or "empty", 0)
        if rank[st] > cur_rank:
            out[k] = {"status": st, "quote": quote}
        elif rank[st] == cur_rank and quote and not out[k].get("quote"):
            out[k]["quote"] = quote
    return out


def update_stall(ep: dict, filled_before: int) -> dict:
    """(P7-1) 이번 턴에 찬 슬롯 수가 늘지 않았으면 stall +1, 늘었으면 0."""
    ep = dict(ep)
    ep["stall"] = 0 if len(filled_slots(ep)) > int(filled_before) else int(ep.get("stall") or 0) + 1
    return ep


def episode_done_reason(ep: dict | None, store: dict | None, chapter: str | None, all_subs: list[str] | None = None) -> str | None:
    """사례 종료 사유: 'slots'(6/6) | 'turns'(리더 턴 8) | 'budget'(챕터 예산) | 'reserve'(미질문 예약 침범) | 'stalled'(2턴 진전 없음) | None."""
    if not ep:
        return None
    turns = int(ep.get("leader_turns") or 0)
    if len(filled_slots(ep)) >= len(SLOT_KEYS) and turns >= EPISODE_MIN_LEADER_TURNS:
        return "slots"                        # 여섯 가지가 다 나왔다 — 턴 상한·예약 때문에 닫히는 것과 구별한다
    if turns >= episode_turn_max(len(all_subs or [])):
        return "turns"
    if remaining(store, chapter) <= 0:
        return "budget"
    if all_subs and remaining(store, chapter) <= reserve_turns(store, chapter, all_subs):
        return "reserve"                      # (P9-1 → P12-3) 미질문 칸 수 × 2턴 예약을 침범 — 6슬롯 전이라도 닫는다
    if int(ep.get("stall") or 0) >= EPISODE_STALL_TURNS and filled_slots(ep):
        return "stalled"                      # (P7-1) 2턴 연속 슬롯 진전 없음 — 들은 것으로 매핑하고 다음으로
    if int(ep.get("stall") or 0) >= EPISODE_STALL_TURNS and not filled_slots(ep):
        # (2026-11-12 P11c-4) 채운 칸이 하나도 없이 리더 턴 2회 연속 진전이 없다 — 사례 없음으로 닫고 다음 칸으로(호출자가 no_case 로 닫는다).
        #   p11b: 한 칸도 못 채운 사례가 8턴까지 가며 같은 질문을 5번 했다(종전의 무진전 종료는 채운 칸이 있을 때만 걸렸다).
        return "stalled_empty"
    if len(filled_slots(ep)) >= len(SLOT_KEYS) and turns >= EPISODE_MIN_LEADER_TURNS:
        return "slots"
    if unfilled_slots(ep) and next_slot(ep) is None:
        return "stalled" if filled_slots(ep) else "stalled_empty"     # (P12-2) 남은 것을 모두 두 번씩 물었다 — 더 캐묻지 않고 닫는다
    return None


_QUOTE_MARK_RE = re.compile(r"[\"“”'‘’]|라고|라는 말|하더라|하시더라|했어요\"")
_DIGIT_RE = re.compile(r"\d|한 달|두 달|세 달|반년|분기|주일|퍼센트|%|배|명|건")


def detail_probe_hint(ep: dict | None) -> str:
    """6/6 이 찼는데 최소 턴 전이면 '장면 구체화' 1턴 — 상대가 한 말 그대로 / 결과 수치 중 비어 있는 쪽."""
    slots = (ep or {}).get("slots") or {}
    reaction_q = (slots.get("reaction") or {}).get("quote") or ""
    result_q = (slots.get("result") or {}).get("quote") or ""
    if not _QUOTE_MARK_RE.search(reaction_q):
        return "상대(팀원·상사)가 그때 실제로 한 말을 그대로 한 마디 — 어떤 표현이었는지"
    if not _DIGIT_RE.search(result_q):
        return "결과를 숫자나 기간으로 — 얼마나, 언제까지"
    return "가장 또렷한 장면 하나에서 한 걸음 더 — 그 자리에서 리더님이 처음 꺼낸 말"


# ── 커버리지 원장 ─────────────────────────────────────────────────────────────
def _add_to_list(store: dict, key: str, chapter: str, value: str) -> dict:
    m = dict(store.get(key) or {})
    cur = list(m.get(chapter) or [])
    if value not in cur:
        cur.append(value)
    m[chapter] = cur
    store[key] = m
    return store


def covered_set(store: dict | None, chapter: str | None) -> set[str]:
    return set((((store or {}).get("covered") or {}).get(chapter or "", {}) or {}).keys())


def weak_map(store: dict | None, chapter: str | None) -> dict[str, list[int]]:
    return dict((((store or {}).get("weak") or {}).get(chapter or "", {}) or {}))


def _list(store: dict | None, key: str, chapter: str | None) -> list[str]:
    return list((((store or {}).get(key) or {}).get(chapter or "", []) or []))


def close_episode(store: dict, chapter: str, ep: dict, status: str, labels: list[dict] | None,
                  all_subs: list[str]) -> dict:
    """사례 종료: 상태·라벨 기록, strong → covered(asked 파생), weak → weak. labels = [{sub, strength, quote}]."""
    ep = dict(ep)
    ep["status"] = status
    clean: list[dict] = []
    for lb in labels or []:
        sub = str((lb or {}).get("sub") or "").strip()
        if sub not in all_subs:
            continue
        strength = "strong" if str((lb or {}).get("strength") or "").lower() == "strong" else "weak"
        clean.append({"sub": sub, "strength": strength, "quote": str((lb or {}).get("quote") or "")[:160]})
    # strong 상한 3개(인용이 긴 순) — 사례 하나가 챕터 전부를 덮는 과잉 배정 방지
    strong = sorted([x for x in clean if x["strength"] == "strong"], key=lambda x: -len(x["quote"]))[:3]
    weak = [x for x in clean if x["strength"] == "weak" and x["sub"] not in {s["sub"] for s in strong}]
    ep["labels"] = strong + weak
    store = update_episode(store, chapter, ep)
    tag = ep["idx"] if ep.get("kind", "episode") == "episode" else f"sweep{ep['idx']}"
    cov_all = dict(store.get("covered") or {})
    cov = {k: list(v) for k, v in (cov_all.get(chapter) or {}).items()}
    for s in strong:
        cov.setdefault(s["sub"], []).append({"episode": tag, "strength": "strong", "quote": s["quote"]})
        store = _add_to_list(store, "asked_subs", chapter, s["sub"])
    cov_all[chapter] = cov
    store["covered"] = cov_all
    weak_all = dict(store.get("weak") or {})
    wk = {k: list(v) for k, v in (weak_all.get(chapter) or {}).items()}
    for w in weak:
        if tag not in wk.setdefault(w["sub"], []):
            wk[w["sub"]].append(tag)
    weak_all[chapter] = wk
    store["weak"] = weak_all
    return store


def mark_repeat(store: dict, chapter: str, sub: str | None) -> dict:
    """(P12b-3) 이 칸의 질문에 리더가 앞에서 닫힌 사례를 다시 말했고, 한 번 더 청해도 다른 장면이 없었다 — '사례 없음'과 구분해 적는다(repeat_subs).
    그 칸의 근거는 원래 사례에 있다(원래 사례의 addenda 에 그 답의 문장을 남긴다)."""
    return _add_to_list(store, "repeat_subs", chapter, sub) if sub else store


def mark_no_case(store: dict, chapter: str, sub: str | None) -> dict:
    return _add_to_list(store, "no_case_subs", chapter, sub) if sub else store


def mark_unconfirmed(store: dict, chapter: str, sub: str | None) -> dict:
    return _add_to_list(store, "unconfirmed", chapter, sub) if sub else store


def uncovered(store: dict | None, chapter: str | None, all_subs: list[str], priority: list[str] | None = None) -> list[str]:
    """covered(strong)·no_case·unconfirmed 를 뺀 하위역량(정의 순서 첫 항목 고정 + priority 우선)."""
    from diag_project.services.traversal import order_by_priority
    skip = (covered_set(store, chapter) | set(_list(store, "no_case_subs", chapter)) | set(_list(store, "unconfirmed", chapter))
            | set(_list(store, "repeat_subs", chapter)))
    return [s for s in order_by_priority(list(all_subs), list(priority or [])) if s not in skip]


def unasked(store: dict | None, chapter: str | None, all_subs: list[str]) -> list[str]:
    """(2026-11-10 P9-1) 아직 한 번도 묻지 않은 하위역량 — asked(여는 앵커·SWEEP 앵커·strong 매핑)·no_case·unconfirmed 어디에도 없는 것.
    챕터 종료 조건과 예약 턴 수의 기준이다."""
    done = set(_list(store, "asked_subs", chapter)) | set(_list(store, "no_case_subs", chapter)) | set(_list(store, "unconfirmed", chapter)) \
        | covered_set(store, chapter) | set(_list(store, "sweep_asked", chapter)) | set(_list(store, "repeat_subs", chapter))
    return [s for s in all_subs if s not in done]


def episode_max(chapter: str | None) -> int:
    return CHAPTER_EPISODE_MAX.get(chapter or "", EPISODE_MAX)


def pick_opener(store: dict | None, chapter: str | None, all_subs: list[str], priority: list[str] | None = None) -> str | None:
    """다음 사례를 여는 하위역량 — 미커버 중 이전 사례의 여는 하위역량이 아닌 첫 항목. 전부 썼으면 미커버 첫 항목."""
    used = {e.get("opener_sub") for e in episodes(store, chapter) if e.get("opener_sub")}
    cands = uncovered(store, chapter, all_subs, priority)
    fresh = [s for s in cands if s not in used]
    return (fresh or cands or [None])[0]


def sweep_count(store: dict | None, chapter: str | None) -> int:
    """(P4-5 → 2026-11-06 P7) 챕터당 SWEEP 상한에 세는 항목 — 사례를 찾아 들은 것(sweep_done 등)만. '없음'(no_case) 1턴짜리는 세지 않는다(전수 탐색 보장)."""
    return sum(1 for e in episodes(store, chapter) if e.get("kind") == "sweep" and e.get("status") not in ("no_case", "repeat"))


def sweep_target(store: dict | None, chapter: str | None, all_subs: list[str], priority: list[str] | None = None) -> str | None:
    """다음 SWEEP 하위역량 — (2026-11-10 P9-1) 미질문 항목 먼저(전수 질문), 그 다음 물었지만 strong 근거가 없는 항목(예산이 남았을 때만).
    챕터당 상한은 없다. 미질문이 남아 있으면 예산이 0 이어도 앵커 1턴은 낸다."""
    asked = set(_list(store, "sweep_asked", chapter))
    cands = [s for s in uncovered(store, chapter, all_subs, priority) if s not in asked]
    un = set(unasked(store, chapter, all_subs))
    first = next((s for s in cands if s in un), None)
    if first:
        return first
    if remaining(store, chapter) <= 0:
        return None
    return cands[0] if cands else None


def consecutive_sweeps(store: dict | None, chapter: str | None) -> int:
    """지금 열린(또는 마지막) 항목까지 이어진 연속 SWEEP 수 — 2개째부터 앵커 앞 다리 문장이 필수(P4-5)."""
    n = 0
    for e in reversed(episodes(store, chapter)):
        if e.get("kind") == "sweep":
            n += 1
        else:
            break
    return n


def plan_after_episode(store: dict | None, chapter: str | None, all_subs: list[str]) -> str:
    """사례 종료 뒤 다음 상태: 'episode' | 'sweep' | 'close'.
    사례 수 < 2 → 사례. = 2 → 미커버 ≥2 이고 남은 턴 − 미커버 수(SWEEP 예비, 앵커만) ≥ 5 면 사례. ≥3 → SWEEP.
    예산이 사례 하나(5턴) 안 남았으면 SWEEP, SWEEP 대상도 없거나 남은 턴 0 이면 CLOSE."""
    n = counted_episodes(store, chapter)
    rem = remaining(store, chapter)
    unc = uncovered(store, chapter, all_subs)
    un = unasked(store, chapter, all_subs)
    if not unc and not un:
        return STATE_CLOSE
    # (2026-11-10 P9-1) 종료 조건은 "모든 하위역량 asked" 하나 — 미질문이 남아 있으면 예산이 0 이어도 SWEEP(앵커 1턴)로 간다.
    #   사례를 새로 열려면 여는 하위역량을 뺀 미질문 수만큼(1턴씩)을 예약하고도 최소 턴이 남아야 한다.
    reserve = RESERVE_PER_UNASKED * max(0, len(un) - 1)      # (P12-3) 칸당 2턴
    can_open = rem - reserve >= EPISODE_OPEN_MIN_REMAINING
    if n < EPISODE_MIN and can_open:
        return STATE_EPISODE
    if EPISODE_MIN <= n < episode_max(chapter) and len(unc) >= 2 and can_open and rem - len(unc) >= EPISODE_OPEN_MIN_REMAINING:
        return STATE_EPISODE
    return STATE_SWEEP if sweep_target(store, chapter, all_subs) else STATE_CLOSE


def sweep_followup_allowed(store: dict | None, chapter: str | None, all_subs: list[str], ep: dict | None) -> bool:
    """SWEEP 후속 1턴 — (P12-3) 사례가 나왔으면 꼬리 질문을 한 번은 하고 넘어간다. 여섯 가지가 다 나왔거나, 아직 묻지 않은 칸의
    여는 질문(칸당 1턴)까지 못 내게 될 때만 생략한다. (종전: 행동+결과가 찼으면 생략 · 미질문 예약 1턴씩)"""
    if not ep or int(ep.get("leader_turns") or 0) >= 2:
        return False
    if len(filled_slots(ep)) >= len(SLOT_KEYS):
        return False
    return remaining(store, chapter) > len(unasked(store, chapter, all_subs))


# ── (2026-11-12 P11b-7) 보완 질문에서 나온 사례 ─────────────────────────────
#   11/12 운영 Daniel: 보완 질문의 답이 실제 사건(평가 불일치)이었는데 2턴(앵커 + 후속 1)에 닫혀 주제가 바뀌었다. 답이 실제 사건이면 일반 사례처럼 올려
#   여섯 가지 중 빠진 것만 묻는다 — 리더 턴 최대 4(앵커 답 포함). 아직 묻지 않은 하위역량의 예약 턴(1턴씩)은 침범하지 않는다.
#   예산이 모자라면 올리지 않고 종전대로 2턴에 닫는다. 어느 쪽으로 갔는지는 그 항목의 promote('promoted'|'no_budget')·promote_end(닫힌 사유)에 적는다.
SWEEP_PROMOTE_MAX_TURNS = 4
SWEEP_PROMOTE_MIN_ROOM = 2            # 예약을 빼고 이만큼은 남아야 올린다(1 이면 종전의 후속 1턴과 같다)


def sweep_promote_decision(store: dict | None, chapter: str | None, all_subs: list[str], ep: dict | None, *, incident: bool | None) -> str | None:
    """보완 질문의 첫 답을 보고 정한다 — 'promoted'(일반 사례로 올림) | 'no_budget'(사건이지만 예산 부족, 종전대로) | None(사건이 아니거나 이미 정했다)."""
    if not ep or ep.get("kind") != "sweep" or ep.get("promote") or int(ep.get("leader_turns") or 0) != 1 or incident is not True:
        return None
    if len(filled_slots(ep)) >= len(SLOT_KEYS):
        return None                                   # 한 번의 답에 여섯 가지가 다 나왔다 — 더 물을 것이 없다
    room = remaining(store, chapter) - reserve_turns(store, chapter, all_subs)
    return "promoted" if room >= SWEEP_PROMOTE_MIN_ROOM else "no_budget"


def promoted_done_reason(ep: dict | None, store: dict | None, chapter: str | None, all_subs: list[str] | None = None) -> str | None:
    """올린 보완 사례의 종료 사유 — 'slots'(여섯 가지) | 'turns'(리더 턴 4) | 'budget' | 'reserve'(미질문 예약 침범) | 'stalled' | None(계속)."""
    if not ep:
        return None
    if len(filled_slots(ep)) >= len(SLOT_KEYS):
        return "slots"
    if int(ep.get("leader_turns") or 0) >= SWEEP_PROMOTE_MAX_TURNS:
        return "turns"
    if remaining(store, chapter) <= 0:
        return "budget"
    if all_subs and remaining(store, chapter) <= reserve_turns(store, chapter, all_subs):
        return "reserve"
    if int(ep.get("stall") or 0) >= EPISODE_STALL_TURNS or next_slot(ep) is None:
        return "stalled" if filled_slots(ep) else "stalled_empty"     # (P11c-4) 채운 칸 없이 2턴 무진전 → 호출자가 사례 없음으로 닫는다
    return None


def is_natural_close(closed_tag: str | None) -> bool:
    """(P11b-8) 휴식을 권해도 되는 닫힘인가 — 일반 사례가 여섯 가지를 다 채웠거나('episodeN:done') 8턴에 닿았을 때('episodeN:turns')만.
    보완 사례(sweepN:…)·조기 종료(stalled·reserve·budget)·사례 없음(no_case)은 아니다."""
    t = str(closed_tag or "")
    return t.startswith("episode") and t.rsplit(":", 1)[-1] in ("done", "turns")


# ── 스냅숏(LLM 실패·일시정지 제안 되돌림) ───────────────────────────────────
def snapshot(store: dict | None) -> dict:
    return {k: copy.deepcopy((store or {}).get(k)) for k in LEDGER_KEYS}


def restore(store: dict, snap: dict | None) -> dict:
    for k in LEDGER_KEYS:
        v = (snap or {}).get(k)
        if v is None:
            store.pop(k, None)
        else:
            store[k] = copy.deepcopy(v)
    return store


# ── 요약(리포트·린트) ─────────────────────────────────────────────────────────
def coverage_summary(store: dict | None, chapter: str, all_subs: list[str]) -> dict:
    cov = covered_set(store, chapter)
    sweep = set(_list(store, "sweep_asked", chapter))
    unc = set(_list(store, "unconfirmed", chapter))
    noc = set(_list(store, "no_case_subs", chapter))
    asked = set(_list(store, "asked_subs", chapter))   # (P9-1) 여는 앵커로 물은 항목도 물은 것 — 미탐색은 '한 번도 묻지 않은 것'만
    not_explored = [s for s in all_subs if s not in cov and s not in sweep and s not in unc and s not in noc and s not in asked]
    return {
        "repeat": sorted(set(_list(store, "repeat_subs", chapter))),
        "covered": sorted(cov), "sweep_asked": sorted(sweep), "unconfirmed": sorted(unc | noc),
        "not_explored": not_explored, "episodes": counted_episodes(store, chapter), "bei_turns": bei_turns(store, chapter),
        "budget": chapter_budget(chapter),
    }


def not_explored_subs(store: dict | None, chapter: str, all_subs: list[str]) -> list[str]:
    return coverage_summary(store, chapter, all_subs)["not_explored"]
