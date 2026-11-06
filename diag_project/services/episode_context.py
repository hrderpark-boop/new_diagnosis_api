"""(2026-11-06 P6) 사례(episode) 문맥 — 게이트가 '칸별 인용 조각'이 아니라 '그 인용이 속한 사례 전체'를 보고 판정하게 한다.

배경(운영 Michael 재분석 11/6): 같은 사례가 문제해결·실행력·갈등관리 세 칸을 Lv.3 으로 올리고, KPI 는 채택 문장이 목표설정 칸에 가
있어 Lv.3 이 빠졌으며, 회차마다 고른 조각이 달라 2↔3 이 교차했다. 설계 docs/design_bei_2026-11.md §17.

순수 함수만. 입력은 ChatMessage·Event 행(속성 접근)이거나 같은 꼴의 dict/객체.
  · build_episode_index      : Event 1건 = 사례 1건. 그 사례 구간의 리더 발화(ChatMessage.event_id 태깅)를 모은다. 태깅이 없으면 슬롯 인용(S/A/R)으로 폴백.
  · find_episode_for_quote   : 근거 인용 → 그 인용이 들어 있는 사례(느슨 비교: 공백·따옴표 제거 뒤 앞 40자 부분 일치). 자기 챕터 사례 우선.
  · episodes_block           : 게이트 배치 앞에 붙는 "[사례 A] …" 블록(사례 하나는 한 번만).
  · prioritize_own_chapter   : 근거 선택 우선순위 — 자기 챕터 인용이 하나라도 있으면 교차 챕터 인용은 뺀다(2번).
  · annotate_episode_lift    : 한 사례가 Lv.3 이상으로 올린 칸 수(2번 집계) — 리포트 메타·analysis_lint 경고.
  · dedupe_quotes_display    : 같은 인용이 여러 칸에 반복될 때 두 번째부터 "(위 사례와 동일)" 표시 필드(3번).
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Iterable

from diag_project.data.competencies import COMPETENCY_FRAMEWORK

EPISODE_TEXT_MAX_CHARS = 1800      # 사례 하나의 리더 발화 상한(게이트 입력)
LIFT_WARN_MIN = 3                  # 한 사례가 Lv.3 이상으로 올린 칸이 이 수 이상이면 린트 경고
_LETTERS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"


def _attr(o: Any, name: str, default=None):
    if isinstance(o, dict):
        return o.get(name, default)
    return getattr(o, name, default)


def _norm(t: str | None) -> str:
    return re.sub(r"[\s\"'“”‘’]+", "", str(t or ""))


def _strip_source_tag(q: str) -> str:
    """'(조직관리 대화에서) ' 표기를 뗀 원문."""
    return re.sub(r"^\([^)]{1,12} 대화에서\) ", "", str(q or ""))


def _chapter_name(ch: str | None) -> str:
    return (COMPETENCY_FRAMEWORK.get(ch or "", {}) or {}).get("name") or (ch or "")


def build_episode_index(messages: Iterable[Any], events: Iterable[Any], store: dict | None = None) -> list[dict]:
    """[{id, chapter, label, leader_texts, text, mapped, kind}] — Event 순서. 리더 발화는 event_id 태깅 메시지(없으면 슬롯 인용)."""
    msgs = list(messages or [])
    by_event: dict[str, list[str]] = {}
    for m in msgs:
        if str(_attr(m, "role") or "") != "user":
            continue
        eid = _attr(m, "event_id")
        if eid is None:
            continue
        by_event.setdefault(str(eid), []).append(str(_attr(m, "content") or ""))
    out: list[dict] = []
    for e in events or []:
        eid = str(_attr(e, "id"))
        chapter = str(_attr(e, "chapter") or "")
        summary = str(_attr(e, "summary") or "")
        kind = "sweep" if summary.startswith("보완") else "episode"
        head = summary.split(":", 1)[0].strip() if summary else ("보완" if kind == "sweep" else "사례")
        leader_texts = [t for t in by_event.get(eid, []) if t.strip()]
        if not leader_texts:
            leader_texts = [t for t in (_attr(e, "situation"), _attr(e, "action"), _attr(e, "result")) if t]
        text = " ".join(leader_texts).strip()
        if len(text) > EPISODE_TEXT_MAX_CHARS:
            text = text[:EPISODE_TEXT_MAX_CHARS].rsplit(" ", 1)[0] + "…"
        mapped = [s.strip() for s in str(_attr(e, "mapped_subcompetency") or "").split(",") if s.strip()]
        out.append({"id": eid, "chapter": chapter, "kind": kind, "label": f"{_chapter_name(chapter)} {head}".strip(),
                    "leader_texts": leader_texts, "text": text, "mapped": mapped})
    return out


def find_episode_for_quote(quote: str | None, episodes: list[dict], prefer_chapter: str | None = None) -> dict | None:
    """인용이 들어 있는 사례. 자기 챕터(prefer_chapter) 사례를 먼저, 없으면 다른 챕터. 6자 미만 인용은 매핑하지 않는다."""
    nq = _norm(_strip_source_tag(quote))[:40]
    if len(nq) < 6:
        return None
    ordered = sorted(episodes or [], key=lambda e: 0 if (prefer_chapter and e.get("chapter") == prefer_chapter) else 1)
    for e in ordered:
        if nq in _norm(e.get("text")) or any(nq in _norm(t) for t in e.get("leader_texts") or []):
            return e
    return None


def episodes_for_evidence(evidence: list[str], episodes: list[dict], prefer_chapter: str | None = None) -> list[dict]:
    """근거 목록이 가리키는 사례들(중복 제거, 등장 순)."""
    seen: set[str] = set()
    out: list[dict] = []
    for q in evidence or []:
        e = find_episode_for_quote(q, episodes, prefer_chapter)
        if e and e["id"] not in seen:
            seen.add(e["id"]); out.append(e)
    return out


def episodes_for_cell(evidence: list[str], episodes: list[dict], chapter: str) -> list[dict]:
    """(P6 승인 반영 가) 한 칸이 게이트에 들고 가는 사례: 자기 챕터 사례는 여럿 묶어도 되고, 자기 챕터 사례가 없으면 교차 챕터 사례 1건만(단독 근거)."""
    eps = episodes_for_evidence(evidence, episodes, prefer_chapter=chapter)
    own = [e for e in eps if e.get("chapter") == chapter]
    if own:
        return own
    cross = [e for e in eps if e.get("chapter") != chapter]
    return cross[:1]


def episode_hash(episodes: list[dict] | None) -> str:
    """게이트 캐시 키 성분 — 사례 텍스트가 바뀌면 다른 키."""
    if not episodes:
        return ""
    h = hashlib.sha256()
    for e in sorted(episodes, key=lambda x: str(x.get("id"))):
        h.update(str(e.get("id")).encode()); h.update(b"|"); h.update(str(e.get("text")).encode()); h.update(b"\n")
    return h.hexdigest()[:16]


def assign_letters(items: list[dict]) -> dict[str, str]:
    """배치 안 사례들에 A, B, … 를 매긴다(항목 등장 순). {episode_id: letter}"""
    letters: dict[str, str] = {}
    for it in items:
        for e in it.get("episodes") or []:
            if e["id"] not in letters:
                letters[e["id"]] = _LETTERS[len(letters) % len(_LETTERS)]
    return letters


def episodes_block(items: list[dict], letters: dict[str, str]) -> str:
    """게이트 배치 앞 블록 — 사례 하나는 한 번만. 비면 빈 문자열."""
    if not letters:
        return ""
    by_id: dict[str, dict] = {}
    for it in items:
        for e in it.get("episodes") or []:
            by_id.setdefault(e["id"], e)
    lines = ["[사례 전문 — 아래 항목의 '리더 발화(근거)'는 이 사례들 안의 한 부분이다. 레벨은 인용 조각이 아니라 그 사례 전체에서 리더가 실제로 한 행동으로 판정한다. "
             "사례에 없는 행동을 상상하지 않는다.]"]
    for eid, letter in letters.items():
        e = by_id[eid]
        lines.append(f"[사례 {letter}] ({e.get('label')}) 리더 발화 전체:\n{e.get('text')}")
    return "\n\n".join(lines)


def quote_chapters(quote: str | None, user_turns: list[tuple[str | None, str]]) -> list[str]:
    """인용이 들어 있는 챕터들(리더 발화 기준, 등장 순). 못 찾으면 []."""
    nq = _norm(_strip_source_tag(quote))[:40]
    if len(nq) < 6:
        return []
    out: list[str] = []
    for ch, txt in user_turns or []:
        if ch and nq in _norm(txt) and ch not in out:
            out.append(ch)
    return out


def prioritize_own_chapter(evidence: list[str], competency_key: str, user_turns: list[tuple[str | None, str]]) -> tuple[list[str], list[str]]:
    """(2번) 자기 챕터 인용이 하나라도 있으면 교차 챕터 인용은 뺀다. 출처를 못 찾은 인용은 그대로 둔다. (남긴 것, 뺀 것)"""
    if not evidence or not user_turns:
        return list(evidence or []), []
    own, cross, unknown = [], [], []
    for q in evidence:
        chs = quote_chapters(q, user_turns)
        if not chs:
            unknown.append(q)
        elif competency_key in chs:
            own.append(q)
        else:
            cross.append(q)
    if own:
        return [q for q in evidence if q in own or q in unknown], cross
    return list(evidence), []


def annotate_episode_lift(details: dict, episodes: list[dict], user_turns: list[tuple[str | None, str]] | None = None,
                          min_level: int = 3) -> dict:
    """(2번) measured 이고 level ≥ min_level 인 칸의 근거가 어느 사례에서 왔는지 — sub_ledger 행에 'episode' 라벨을 적고
    {사례 라벨: [칸…]} 를 돌려준다. 호출자는 len ≥ LIFT_WARN_MIN 이면 경고."""
    lift: dict[str, list[str]] = {}
    for ck, comp in (details or {}).items():
        led = (comp or {}).get("sub_ledger") or {}
        for sub, row in led.items():
            if not isinstance(row, dict):
                continue
            ev = row.get("evidence") or []
            eps = episodes_for_evidence(ev, episodes, prefer_chapter=ck)
            if eps:
                row["episode"] = eps[0]["label"]
            if row.get("measured") and row.get("level") and int(row["level"]) >= min_level:
                for e in eps:
                    lift.setdefault(e["label"], []).append(f"{_chapter_name(ck)}/{sub}")
    return lift


def lift_warnings(lift: dict, min_count: int = LIFT_WARN_MIN) -> list[str]:
    return [f"{label}: {len(subs)}칸 — {', '.join(subs)}" for label, subs in (lift or {}).items() if len(subs) >= min_count]


def dedupe_quotes_display(details: dict) -> int:
    """(3번) 같은 인용이 여러 칸(하위역량 근거·S/A/R 인용)에 반복되면 두 번째부터 '(위 사례와 동일) …앞 18자…'.
    원본 evidence 는 그대로 두고 표시 필드(evidence_display / quotes_display)를 만든다. 바꾼 수를 돌려준다."""
    seen: dict[str, str] = {}
    n = 0

    def _disp(q: str) -> str:
        nonlocal n
        key = _norm(_strip_source_tag(q))[:60]
        if len(key) < 6:
            return q
        if key in seen:
            n += 1
            core = _strip_source_tag(q)
            return f"(위 사례와 동일) {core[:18].rstrip()}…"
        seen[key] = q
        return q

    for ck, comp in (details or {}).items():
        if not isinstance(comp, dict):
            continue
        rp = comp.get("reasoning_process") or {}
        for step in ("1_situation", "2_action", "3_result"):
            st = rp.get(step)
            if isinstance(st, dict):
                qs = st.get("quotes") or st.get("evidence") or []
                if qs:
                    st["quotes_display"] = [_disp(str(q)) for q in qs]
        for sub, row in ((comp.get("sub_ledger") or {}).items()):
            if isinstance(row, dict) and row.get("evidence"):
                row["evidence_display"] = [_disp(str(q)) for q in row["evidence"]]
    return n
