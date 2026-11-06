#!/usr/bin/env python
"""코치 재생·시뮬 전문 품질 린트 — 대화 품질 지표를 자동 집계해 마크다운 표로 낸다. (2026-10-28 도입 → 2026-11-04 BEI 개편)

입력: `.fm_work/replay_result_*.json` / `tools/sim_leader.py` 출력 구조의 파일 1개 이상.
    {"session": "...", "coach": "2", "rows": [{"t", "role", "chapter", "probe", "instr", "content", "guard"}, ...],
     "ledger": {...self_assessment_data 일부(선택)}, "truth": {"episodes": [{"subs": [...]}, ...]}(시뮬 정답, 선택)}

사용:
    python tools/transcript_lint.py FILE [FILE ...] [--json OUT] [--dump-lexicon]

집계 항목
  1. 내부 어휘 누설 — 누설 사전은 프롬프트 템플릿에서 **자동 추출**(수동 목록 없음) + 상태 보고문 패턴
  2. ALIGN 턴 검사(하위역량 목록 전부 / 앵커 질문 1개 / 확인 질문으로 끝나지 않음)
  3. 질문 잘림(주절 없이 조건절·연결어미로 시작하는 질문)
  4. 사용자 입력 복사·반복 미감지 (a) 직전 사용자 턴 반복 (b) 코치 질문 그대로 붙여넣기
  5. (BEI) 사례 단계 — 사례당 리더 턴·6슬롯 도달·챕터 리더 턴·커버리지·미확인/미탐색·매핑 정확도(정답 있을 때)
  6. 되받기 — 되받기 없는 턴 / 리더 명사구 미인용 턴 / 형식 재생성·미해결(receive_miss) · 고정 문장(시스템 앵커·슬롯) 연속 반복
  7. 코치별 어미 분포 · 코치 간 동일 앵커 문장 쌍 수 · 페르소나 슬롯(사례당 1)·Michael '좋습니다' 챕터 최대

2단계 통과 기준(docs/design_bei_2026-11.md §11): 사례당 리더 턴 5~8 · 되받기 없는 턴 0 · 고정 문장 반복 없음 · 챕터 리더 턴 ≤ 20 · 커버리지 ≥ 3/4.
"""
from __future__ import annotations

import argparse
import difflib
import json
import os
import re
import sys
from collections import Counter, defaultdict
from itertools import combinations
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from diag_project.data.coaches_persona import COACHES_PERSONA  # noqa: E402
from diag_project.data.competencies import COMPETENCY_FRAMEWORK  # noqa: E402
from diag_project.services.bei_engine import BEI_INSTRUCTIONS, SLOT_KEYS, coverage_summary, is_no_case_text as _is_no_case_text  # noqa: E402
from diag_project.services.leak_lexicon import (  # noqa: E402
    _HANGUL_RE, _raw_tokens, build_lexicon, find_lexicon_leaks, find_state_report, guard_lexicon, lexicon_size,
)
from diag_project.services.output_guard import count_questions, is_question, split_sentences  # noqa: E402
from diag_project.services.receive_check import RECEIVE_REQUIRED_INSTRUCTIONS as _RECV_INSTR, check_receive  # noqa: E402

COACH_NAMES: dict[str, str] = {k: v["name"].split(" ")[0] for k, v in COACHES_PERSONA.items()}
_STRICT_LEX = guard_lexicon()
CHAPTERS = [k for k in COMPETENCY_FRAMEWORK if k != "supplementary"]

_TRUNC_START_RE = re.compile(r"^(있었다면|있으셨다면|했다면|하셨다면|이유였는지|시점이었는지|계기였는지|때문이었는지)")
_TRUNC_FIRST_TOKEN_RE = re.compile(r"(다면|시면|으면|하면|라면|이면|려면|거든|는지|인지|였는지|었는지|던지)[,，]?$")   # (p2a) '전면·장면' 명사 오탐 제외
_TRUNC_EXEMPT = {"그렇다면", "그러면", "그럼", "그러시면", "아니면", "괜찮으시면", "괜찮다면", "가능하다면", "가능하시면", "혹시라도", "말하자면", "예를들면"}
_REPEAT_ACK_RE = re.compile(r"((앞서|방금|조금\s*전|이전에|아까|직전에)\s*(말씀하신|하신\s*말씀|주신\s*답변|답하신|쓰신|보내신)\s*(내용|말씀|답변|것)?(과|와|이랑|하고|도)?\s*(같|동일|비슷|반복|다시)"
                            r"|같은\s*(답변|내용|말씀|글)(이|을|을\s*다시|이\s*다시|이\s*반복)|(답변|내용|말씀)(이|을)\s*(그대로|다시|반복)|반복(된|되는|하신|해서\s*주신|으로)|두\s*번\s*(같은|동일))")
_PASTE_ACK_RE = re.compile(r"(질문(이|을|만|이\s*그대로|을\s*그대로)?\s*(그대로|다시|되돌|돌아|돌려|옮겨|붙여|복사)|제\s*질문(을|이)|되돌아온|되돌아왔|질문을\s*되묻|질문이\s*반복|질문\s*그대로|그대로\s*(돌아왔|보내|옮기|붙여|돌려))")
# '~는지요?/~은지요?/~인지요?/~실지요?/~을지요?' 는 간접 의문(Daniel·Olivia 어미)이지 확인 질문이 아니다
_CONFIRM_TAIL_RE = re.compile(r"(죠\?|(?<![는은인실을일할])지요\?|크게\s*다르지\s*않|맞을까요\?|맞나요\?|맞습니까\?|않으신가요\?|않을까요\?|아닐까요\?)\s*$")
_ENDINGS = ("시겠습니까", "셨습니까", "였습니까", "었습니까", "습니까", "ㅂ니까", "었을까요", "았을까요", "였을까요", "을까요", "실까요", "ㄹ까요", "까요",
            "셨나요", "었나요", "았나요", "였나요", "나요", "는지요", "지요", "죠", "세요", "셨어요", "었어요", "았어요", "어요", "아요", "예요", "에요",
            "요", "니까", "는가", "ㄴ가", "가", "니", "지")
_PROBE_TYPE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_BEI_COACH_INSTR = set(BEI_INSTRUCTIONS) | {"COMPETENCY_ALIGN"}
_PROBE_INSTR = {"EPISODE_PROBE", "NO_CASE_REFRAME", "SWEEP_FOLLOWUP"}


# ══════════════════════════════════════════════════════════════════════════════
# 보조 함수
# ══════════════════════════════════════════════════════════════════════════════
def _slot_sentence_kept(coach_name: str, text: str, slot_kind: str | None = None) -> bool:
    """페르소나 슬롯 고정 문장(2026-11-05 P4-1: 코치별 5종 순환·Michael 실행 의지 3종)이 본문에 남아 있는가(첫 문장 기준)."""
    from diag_project.services.intro_messages import MICHAEL_WILL_QUESTIONS, slot_variants_for
    from diag_project.services.persona_voice import _CONTRAST_RE
    _n = lambda t: re.sub(r"\s+", "", t or "")   # noqa: E731
    body = _n(text)
    pool = MICHAEL_WILL_QUESTIONS if slot_kind == "Michael_q" else slot_variants_for(coach_name)
    if any(_n((split_sentences(x) or [x])[0]) in body for x in pool):
        return True
    return coach_name == "Olivia" and slot_kind != "Michael_q" and bool(_CONTRAST_RE.search(text or ""))


def _fixed_pool_norm() -> set[str]:
    """고정 문장(슬롯 5종×코치·관찰·실행 의지·ALIGN 다리) 정규화 집합 — 평가 말투·흉터 집계에서 제외."""
    from diag_project.services.intro_messages import all_fixed_sentences
    return {norm_sentence(x) for x in all_fixed_sentences()}


def norm_sentence(s: str) -> str:
    return re.sub(r"[\s\.,!?…:;()\[\]{}'\"“”‘’·\-—–]+", "", s or "")


def question_sentences(text: str) -> list[str]:
    return [s.strip() for s in split_sentences(text) if is_question(s)]


def last_question(text: str) -> str | None:
    qs = question_sentences(text)
    return qs[-1] if qs else None


def ending_of(sentence: str) -> str:
    s = (sentence or "").strip().rstrip("?!.…").strip()
    for e in _ENDINGS:
        if s.endswith(e):
            return e + "?"
    return (s[-2:] if len(s) >= 2 else s) + "?"


def is_truncated_question(sentence: str) -> bool:
    s = (sentence or "").strip().lstrip("'\"“‘(")
    if not s:
        return False
    if _TRUNC_START_RE.match(s):
        return True
    first = s.split()[0] if s.split() else ""
    bare = first.rstrip(",，")
    if bare in _TRUNC_EXEMPT or not _HANGUL_RE.match(bare):
        return False
    _first_clause = re.split(r"[,，]", s, 1)[0].strip()
    if len(s.split(",")) > 1 and re.search(r"(는데요|은데요|ㄴ데요|지만|거든요|고요|니다만)$", _first_clause):
        return False
    return bool(_TRUNC_FIRST_TOKEN_RE.search(first))


def indicator_names(chapter: str | None) -> list[str]:
    fw = COMPETENCY_FRAMEWORK.get(chapter or "") or {}
    return [ind["name"] for ind in fw.get("indicators", {}).values()]


def _align_list_items(text: str) -> list[str]:
    return [line.strip()[2:].strip() for line in (text or "").splitlines() if line.strip().startswith("· ")]


def check_align_turn(text: str, chapter: str | None) -> tuple[bool, list[str]]:
    """ALIGN 턴 3항목 검사. (PASS 여부, 사유 목록)"""
    reasons: list[str] = []
    names = indicator_names(chapter)
    items = [norm_sentence(i) for i in _align_list_items(text)]
    if not names:
        reasons.append(f"챕터 미확인({chapter})")
    else:
        missing = []
        for n in names:
            nn = norm_sentence(n)
            base = norm_sentence(n.split("(")[0])
            if not any(it == nn or it == base or (len(it) >= 2 and nn.startswith(it)) for it in items):
                missing.append(n)
        if missing:
            reasons.append("하위역량 누락: " + ", ".join(missing))
    sents = split_sentences(text)
    last = sents[-1].strip() if sents else ""
    n_q = count_questions(text)
    # (2026-11-05 P4-4) 여는 문장은 질문 뒤 짧은 덧붙임 1문장('작은 일이어도요.')이 올 수 있다 — 끝에서 두 번째가 질문이고 덧붙임 ≤ 25자면 통과
    _tail_ok = is_question(last) or (len(sents) >= 2 and is_question(sents[-2].strip()) and len(last) <= 25)
    if _tail_ok and not is_question(last):
        last = sents[-2].strip()
    if n_q != 1 or not _tail_ok:
        reasons.append(f"앵커 질문 1개 아님(질문 문장 {n_q}개, 마지막 문장 질문={is_question(last)})")
    if _CONFIRM_TAIL_RE.search(last):
        reasons.append("확인 질문으로 끝남: " + last[-20:])
    return (not reasons), reasons


def _guard(row: dict) -> dict:
    return row.get("guard") or {}


def _chapter_of(row: dict) -> str | None:
    return row.get("chapter") or _guard(row).get("ch")


def _probe_target(row: dict) -> str:
    g = _guard(row)
    for key in ("target", "sub", "sub_key", "target_sub"):
        v = g.get(key) or row.get(key)
        if v:
            return str(v)
    p = row.get("probe")
    if p and not _PROBE_TYPE_RE.match(str(p)):
        return str(p)
    return _chapter_of(row) or "-"


def _is_anchor_turn(row: dict) -> str | None:
    """앵커 비교 대상 턴이면 종류 문자열을, 아니면 None."""
    instr = row.get("instr")
    if instr == "COMPETENCY_ALIGN":
        return "ALIGN"
    if instr in ("EPISODE_OPEN", "SWEEP_ANCHOR") or _guard(row).get("anchor_attached"):
        return "앵커"
    return None


# ══════════════════════════════════════════════════════════════════════════════
# 파일 단위 분석
# ══════════════════════════════════════════════════════════════════════════════
def analyze(data: dict, lex: dict, label: str = "") -> dict:
    rows = data.get("rows") or []
    coach_key = str(data.get("coach") or "")
    coach_name = COACH_NAMES.get(coach_key, coach_key or "?")
    res: dict = {
        "file": label, "session": data.get("session"), "coach": coach_key, "coach_name": coach_name,
        "coach_turns": 0, "leaks": [], "leak_total": 0, "leak_strict_total": 0,
        "align": [], "align_pass": 0, "align_total": 0,
        "truncated": [], "truncated_total": 0,
        "repeat_a_cases": 0, "repeat_a_missed": 0, "repeat_b_cases": 0, "repeat_b_missed": 0, "repeat_missed": [],
        "leak_final_turns": 0, "incident_word_turns": 0,
        "slot_turns": 0, "slot_kept": 0, "slot_restored": 0, "slot_episodes": 0,
        "good_lead_by_chapter": {}, "good_lead_max": 0,
        # 되받기(8-w 턴 형식): 대상 턴 수 · 되받기 없는 턴 · 명사구 미인용 턴 · 형식 재생성 턴 · 미해결(receive_miss) 턴
        "receive_turns": 0, "no_receive_turns": 0, "receive_no_quote_turns": 0, "receive_issues": [],
        "format_regen_turns": 0, "receive_miss_turns": 0, "format_miss": {},
        # 고정 문장(시스템 앵커·슬롯) 연속 반복 — 목표 0
        "tail_repeat": 0, "slot_repeat": 0, "anchor_reuse": 0, "repeat_issues": [],
        # (2026-11-05 P4) 슬롯 챕터당 최대(≤1) · 평가 말투 턴(0) · 흉터 문장 턴(0) · 같은 고정 문장 세션 ≥3회(0) · 여는 문장 모드 · SWEEP 다리 누락 · 종료 요약 모드
        "slot_per_chapter_max": 0, "slot_by_chapter": {}, "praise_turns": 0, "praise_issues": [], "broken_turns": 0, "broken_issues": [],
        "repeat3": [], "opener_modes": {}, "sweep_bridge_missing": 0, "close_modes": {}, "scope_fallback_turns": 0,
        # (BEI) 사례 단계
        "episodes": {}, "episode_turns": [], "episode_turns_out_of_range": 0, "episodes_six_slots": 0, "episodes_closed": 0,
        "chapter_leader_turns": {}, "chapter_leader_turns_max": 0, "coverage": {}, "coverage_ratio": None,
        "unconfirmed_total": 0, "not_explored_total": 0, "sweep_turns": 0, "retry_turns": 0, "open_turns": 0,
        "mapping_accuracy": None, "parrot_turns": 0,
        "endings": {}, "anchors": [],
    }
    endings: Counter = Counter()
    prev_user: str | None = None
    prev_coach: str | None = None
    prev_tail: str | None = None
    prev_slot_text: str | None = None
    user_tokens: set[str] = set()
    ep_turn: dict[tuple, int] = {}          # (챕터, 사례 번호) → 최대 리더 턴
    ep_closed: dict[tuple, dict] = {}       # (챕터, 사례 번호) → {status, slots_filled}
    ch_leader: Counter = Counter()
    mapped_by_ch: dict[str, set] = defaultdict(set)
    slot_eps: set = set()
    last_bei_model_ch: str | None = None    # 직전 코치 턴이 BEI/ALIGN 이면 다음 리더 답은 BEI 리더 턴
    _fixed_norm = _fixed_pool_norm()
    _sent_counter: Counter = Counter()      # (P4-1) 코치 문장 세션 누적 — 같은 문장 ≥3회 = 실패
    from diag_project.services.output_guard import _has_praise as _hp_l, is_broken_sentence as _ibs_l

    for i, row in enumerate(rows):
        role = row.get("role")
        content = row.get("content") or ""
        t = row.get("t")
        if role == "user":
            if last_bei_model_ch:
                ch_leader[last_bei_model_ch] += 1
                last_bei_model_ch = None
            a, b = re.sub(r"\s+", "", prev_user or ""), re.sub(r"\s+", "", content)
            nxt = next((r for r in rows[i + 1:] if r.get("role") == "model"), None)
            nxt_text = (nxt or {}).get("content") or ""
            if prev_user and a and b and len(b) >= 10 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.9:
                res["repeat_a_cases"] += 1
                if not _REPEAT_ACK_RE.search(nxt_text):
                    res["repeat_a_missed"] += 1
                    res["repeat_missed"].append({"t": t, "kind": "a", "user": content[:60], "coach": nxt_text[:80]})
            if prev_coach:
                nu = norm_sentence(content)
                pasted = [q for q in question_sentences(prev_coach) if len(norm_sentence(q)) >= 10 and norm_sentence(q) in nu]
                if pasted:
                    res["repeat_b_cases"] += 1
                    if not _PASTE_ACK_RE.search(nxt_text):
                        res["repeat_b_missed"] += 1
                        res["repeat_missed"].append({"t": t, "kind": "b", "user": content[:60], "coach": nxt_text[:80]})
            prev_user = content
            user_tokens.update(tk.lower() for tk in _raw_tokens(content))
            continue
        if role != "model":
            continue
        res["coach_turns"] += 1
        g = _guard(row)
        chapter = _chapter_of(row)
        instr = row.get("instr")
        last_bei_model_ch = chapter if (chapter and instr in _BEI_COACH_INSTR) else None
        # 1. 누설
        words = find_lexicon_leaks(content, lex, user_tokens)
        state = find_state_report(content)
        words_strict = find_lexicon_leaks(content, _STRICT_LEX, user_tokens)
        if words or state:
            res["leaks"].append({"t": t, "words": words, "state": state, "strict": words_strict})
            res["leak_total"] += len(words) + len(state)
            res["leak_strict_total"] += len(words_strict) + len(state)
        # 2. ALIGN
        if instr == "COMPETENCY_ALIGN":
            ok, reasons = check_align_turn(content, chapter)
            res["align_total"] += 1
            res["align_pass"] += int(ok)
            res["align"].append({"t": t, "pass": ok, "reasons": reasons})
        # 3. 잘림
        _sents_all = split_sentences(content)
        for _qi, q in enumerate(_sents_all):
            if not is_question(q) or not is_truncated_question(q):
                continue
            if _qi > 0 and is_question(_sents_all[_qi - 1]):
                continue
            res["truncated"].append({"t": t, "sentence": q})
            res["truncated_total"] += 1
        # 5. (BEI) 사례 단계
        if chapter and g.get("episode") is not None and g.get("ep_kind", "episode") == "episode":
            key = (chapter, int(g.get("episode")))
            ep_turn[key] = max(ep_turn.get(key, 0), int(g.get("ep_turn") or 0))
            if g.get("slot"):
                slot_eps.add(key)
        if chapter and g.get("closed"):
            m = re.match(r"(episode|sweep)(\d+):(\w+)", str(g.get("closed")))
            if m and m.group(1) == "episode":
                key_c = (chapter, int(m.group(2)))
                ep_closed[key_c] = {"status": m.group(3), "slots_filled": int(g.get("slots_filled") or 0)}
                # 종료 턴의 리더 답은 그 사례의 마지막 리더 턴 — guard closed_turns(신규)가 있으면 그것, 없으면 직전 최대 +1
                ep_turn[key_c] = int(g.get("closed_turns") or (ep_turn.get(key_c, 0) + 1))
        for lb in (g.get("mapped") or []):
            if isinstance(lb, str) and lb.endswith(":s") and chapter:
                mapped_by_ch[chapter].add(lb[:-2])
        if instr in ("SWEEP_ANCHOR", "SWEEP_FOLLOWUP"):
            res["sweep_turns"] += 1
        if instr == "NO_CASE_REFRAME":
            res["retry_turns"] += 1
        if instr == "EPISODE_OPEN":
            res["open_turns"] += 1
        if g.get("parrot") == 2:
            res["parrot_turns"] += 1
        # 6. 되받기·형식
        if chapter and instr in _RECV_INSTR:
            res["receive_turns"] += 1
            _has_r, _quoted_r = check_receive(content, prev_user)
            if not _has_r:
                res["no_receive_turns"] += 1
                res["receive_issues"].append({"t": t, "kind": "none", "instr": instr, "coach": content[:90], "user": (prev_user or "")[:60]})
            elif not _quoted_r and not _is_no_case_text(prev_user):   # (2026-11-06 P7) 사례 아님 답에는 인용 요구 없음(8-w 와 같은 기준)
                res["receive_no_quote_turns"] += 1
                res["receive_issues"].append({"t": t, "kind": "no_quote", "instr": instr, "coach": content[:90], "user": (prev_user or "")[:60]})
        if g.get("format_regen"):
            res["format_regen_turns"] += 1
        if g.get("receive_miss"):
            res["receive_miss_turns"] += 1
        for k in (g.get("format_miss") or []):
            res["format_miss"][k] = res["format_miss"].get(k, 0) + 1
        # 7-0. (2026-11-05 P4) 평가 말투·흉터·고정 문장 ≥3회 — 안내 턴(DIAGNOSIS_INTRO)·목록 줄('· ')·고정 문장은 제외
        if instr != "DIAGNOSIS_INTRO":
            _lines_l = [ln for ln in content.split("\n") if ln.strip() and not ln.strip().startswith("·")]
            _sents_l = [x.strip() for ln in _lines_l for x in split_sentences(ln) if x.strip()]
            _free_l = [x for x in _sents_l if norm_sentence(x) not in _fixed_norm]
            _pr_l = [x for x in _free_l if _hp_l(x)]
            if _pr_l:
                res["praise_turns"] += 1
                res["praise_issues"].append({"t": t, "instr": instr, "sentence": _pr_l[0][:90]})
            _bk_l = [x for x in _free_l if _ibs_l(x)]
            if _bk_l:
                res["broken_turns"] += 1
                res["broken_issues"].append({"t": t, "instr": instr, "sentence": _bk_l[0][:90]})
            for x in _sents_l:
                _nx = norm_sentence(x)
                if len(_nx) >= 6:
                    _sent_counter[_nx] += 1
        if g.get("opener"):
            res["opener_modes"][g["opener"]] = res["opener_modes"].get(g["opener"], 0) + 1
        if g.get("sweep_bridge") == 0:
            res["sweep_bridge_missing"] += 1
        if g.get("close_summary_mode"):
            res["close_modes"][g["close_summary_mode"]] = res["close_modes"].get(g["close_summary_mode"], 0) + 1
        if g.get("scope_fallback"):
            res["scope_fallback_turns"] += 1
        # 7. 슬롯·좋습니다·기타
        if g.get("slot"):
            res["slot_turns"] += 1
            if g.get("slot") != "Michael_q":
                res["slot_by_chapter"][chapter or "-"] = res["slot_by_chapter"].get(chapter or "-", 0) + 1
            res["slot_restored"] += int(g.get("slot_restored") or 0)
            if _slot_sentence_kept(coach_name, content, g.get("slot")):
                res["slot_kept"] += 1
            _st_now = re.sub(r"\s+", "", str(g.get("slot")))
            if _st_now == prev_slot_text and _st_now != "Michael":
                res["slot_repeat"] += 1
                res["repeat_issues"].append({"t": t, "kind": "slot", "text": str(g.get("slot"))})
            prev_slot_text = _st_now
        else:
            prev_slot_text = None
        if g.get("leak_final"):
            res["leak_final_turns"] += 1
        if (content or "").lstrip().startswith("좋습니다"):
            res["good_lead_by_chapter"][chapter or "-"] = res["good_lead_by_chapter"].get(chapter or "-", 0) + 1
        if g.get("incident_word"):
            res["incident_word_turns"] += 1
        # 어미·고정 문장 꼬리 반복
        lq = last_question(content)
        if lq:
            endings[ending_of(lq)] += 1
        if lq and (g.get("anchor_attached") or instr == "COMPETENCY_ALIGN"):
            _tail_now = " ".join(lq.rstrip("?.!…").split()[-2:])
            if _tail_now and _tail_now == prev_tail:
                res["tail_repeat"] += 1
                res["repeat_issues"].append({"t": t, "kind": "tail", "text": _tail_now})
            prev_tail = _tail_now
        kind = _is_anchor_turn(row)
        if kind and lq:
            res["anchors"].append({"t": t, "kind": kind, "sentence": lq, "norm": norm_sentence(lq)})
        prev_coach = content

    # (BEI) 집계
    for key, n in sorted(ep_turn.items()):
        ch, idx = key
        info = ep_closed.get(key, {})
        res["episodes"].setdefault(ch, []).append({"idx": idx, "leader_turns": n, "status": info.get("status"),
                                                   "slots_filled": info.get("slots_filled")})
    closed_eps = [e for lst in res["episodes"].values() for e in lst if e.get("status")]
    res["episode_turns"] = [e["leader_turns"] for e in closed_eps]
    res["episodes_closed"] = len(closed_eps)
    res["episode_turns_out_of_range"] = sum(1 for n in res["episode_turns"] if not 5 <= n <= 8)
    res["episodes_six_slots"] = sum(1 for e in closed_eps if (e.get("slots_filled") or 0) >= len(SLOT_KEYS))
    res["slot_episodes"] = len(slot_eps)
    res["chapter_leader_turns"] = dict(ch_leader)
    res["chapter_leader_turns_max"] = max(ch_leader.values()) if ch_leader else 0
    ledger = data.get("ledger") or {}
    cov_total = sub_total = 0
    for ch in CHAPTERS:
        subs = indicator_names(ch)
        if ch not in ch_leader and ch not in res["episodes"]:
            continue
        if ledger.get("covered") is not None or ledger.get("episodes") is not None:
            cs = coverage_summary(ledger, ch, subs)
        else:
            cs = {"covered": sorted(mapped_by_ch.get(ch, set())), "unconfirmed": [], "not_explored": [], "sweep_asked": []}
        res["coverage"][ch] = {"covered": len(cs["covered"]), "total": len(subs), "unconfirmed": len(cs["unconfirmed"]),
                               "not_explored": len(cs["not_explored"]), "covered_subs": cs["covered"],
                               # (2026-11-06 P7) 탐색 = 물어본 하위역량(covered ∪ sweep ∪ unconfirmed ∪ no_case) — 전수 탐색 기준 N/N
                               "asked": len(subs) - len(cs["not_explored"])}
        cov_total += len(cs["covered"]); sub_total += len(subs)
        res["unconfirmed_total"] += len(cs["unconfirmed"])
        res["not_explored_total"] += len(cs["not_explored"])
    res["coverage_ratio"] = (round(cov_total / sub_total, 2) if sub_total else None)
    truth = data.get("truth") or {}
    if truth.get("episodes") and mapped_by_ch:
        want = {s for e in truth["episodes"] if e.get("used", True) for s in (e.get("subs") or [])}
        got = {s for v in mapped_by_ch.values() for s in v}
        res["mapping_accuracy"] = round(len(want & got) / len(want), 2) if want else None
    res["good_lead_max"] = max([n for c, n in res["good_lead_by_chapter"].items() if c != "-"] or [0])
    res["slot_per_chapter_max"] = max(res["slot_by_chapter"].values() or [0])
    res["repeat3"] = [{"n": n, "sentence": k[:60]} for k, n in _sent_counter.most_common() if n >= 3]
    # 세션 안에서 같은 앵커 문장(여는·SWEEP)을 두 번 쓴 수 — 0 목표(s2a Jessica: SWEEP 이 ALIGN 앵커를 되물었다)
    _seen_anchor: Counter = Counter(a["norm"] for a in res["anchors"])
    res["anchor_reuse"] = sum(n - 1 for n in _seen_anchor.values() if n > 1)
    res["endings"] = dict(endings.most_common())
    return res


def cross_anchor_pairs(results: list[dict]) -> dict:
    """서로 다른 코치 파일 간 완전히 같은 앵커 문장 쌍. 같은 코치의 여러 벌끼리는 비교하지 않는다."""
    by_norm: dict[str, dict[str, str]] = defaultdict(dict)
    for r in results:
        for a in r["anchors"]:
            by_norm[a["norm"]].setdefault(r["coach"], a["sentence"])
    pairs = 0
    per_coach: Counter = Counter()
    dup: list[dict] = []
    for norm, coaches in by_norm.items():
        if len(coaches) < 2:
            continue
        keys = sorted(coaches)
        pairs += len(list(combinations(keys, 2)))
        for k in keys:
            per_coach[k] += len(keys) - 1
        dup.append({"sentence": next(iter(coaches.values())), "coaches": [COACH_NAMES.get(k, k) for k in keys]})
    return {"pairs": pairs, "per_coach": dict(per_coach), "duplicates": dup}


# ══════════════════════════════════════════════════════════════════════════════
# 마크다운 출력
# ══════════════════════════════════════════════════════════════════════════════
def render_markdown(results: list[dict], cross: dict, lex: dict) -> str:
    L: list[str] = []
    L.append("## 코치 재생 전문 린트 요약")
    L.append("")
    L.append("| 코치 | 파일 | 누설(전체/엄격) | 8-y | ALIGN | 잘림 | 미감지 a/b | 사례당 리더 턴(5~8 밖) | 6슬롯/종료 사례 | 챕터 리더 턴 최대 | 커버리지 | 미확인/미탐색 | 되받기 없음/미인용(대상) | 형식 재생성/미해결 | 고정문장 반복 꼬리/슬롯/앵커재사용 | 슬롯 사례(보존/턴) | 슬롯/챕터 최대 | 평가 말투 | 흉터 | 고정문장≥3회 | 좋습니다 최대 | 동일앵커 |")
    L.append("|---|---|---:|---:|---:|---:|---:|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in results:
        same = cross["per_coach"].get(r["coach"], 0)
        ep_s = ",".join(str(n) for n in r["episode_turns"]) or "-"
        cov_s = " ".join(f"{c[:2]}{v['covered']}/{v['total']}" for c, v in r["coverage"].items()) or "-"
        L.append(f"| {r['coach_name']}({r['coach']}) | {os.path.basename(r['file'])} | {r['leak_total']}/{r['leak_strict_total']} | {r['leak_final_turns']} | "
                 f"{r['align_pass']}/{r['align_total']} | {r['truncated_total']} | "
                 f"{r['repeat_a_missed']}/{r['repeat_a_cases']} · {r['repeat_b_missed']}/{r['repeat_b_cases']} | "
                 f"{ep_s}({r['episode_turns_out_of_range']}) | {r['episodes_six_slots']}/{r['episodes_closed']} | {r['chapter_leader_turns_max']} | {cov_s} | "
                 f"{r['unconfirmed_total']}/{r['not_explored_total']} | {r['no_receive_turns']}/{r['receive_no_quote_turns']}({r['receive_turns']}) | "
                 f"{r['format_regen_turns']}/{r['receive_miss_turns']} | {r['tail_repeat']}/{r['slot_repeat']}/{r['anchor_reuse']} | {r['slot_episodes']}({r['slot_kept']}/{r['slot_turns']}) | "
                 f"{r['slot_per_chapter_max']} | {r['praise_turns']} | {r['broken_turns']} | {len(r['repeat3'])} | {r['good_lead_max']} | {same} |")
    L.append("")
    L.append("- 미감지 a/b: (직전 사용자 턴 반복 미감지/발생) · (코치 질문 붙여넣기 미감지/발생)")
    L.append("- 사례당 리더 턴: 종료된 사례별 리더 턴 수(괄호는 5~8 밖 사례 수). 6슬롯/종료 사례: 6/6 로 닫힌 사례 수 / 종료 사례 수.")
    L.append("- 되받기 없음/미인용: 사례 턴(EPISODE_*/SWEEP_*)에서 되받기 평서문이 없는 턴 / 리더 명사구를 인용하지 않은 턴. 형식 재생성/미해결: 8-w 재생성이 돈 턴 / 2회 뒤에도 되받기가 없어 그대로 나간 턴(폴백 없음) — 둘 다 0 목표.")
    L.append("- 고정문장 반복: 시스템 앵커 꼬리(마지막 2어절) 연속 2회 / 같은 페르소나 슬롯 연속 2회 — 0 이어야 함.")
    L.append("- (2026-11-05 P4) 슬롯/챕터 최대 ≤1 · 평가 말투('좋습니다/좋은 방향/잘하셨/인상적' 류, 고정 문장 제외) 0 · 흉터(서술어 없음·호칭만·조사 끝) 0 · "
             "같은 고정 문장 세션 ≥3회 0 — 넷 다 P4 통과 기준.")
    if any(r["mapping_accuracy"] is not None for r in results):
        L.append("- 매핑 정확도(시뮬 정답 대비): " + ", ".join(f"{r['coach_name']} {r['mapping_accuracy']}" for r in results if r["mapping_accuracy"] is not None))
    L.append(f"- 코치 간 동일 앵커 문장 쌍 합계: **{cross['pairs']}** (0 이어야 함)")
    for d in cross["duplicates"]:
        L.append(f"  - {' · '.join(d['coaches'])}: \"{d['sentence']}\"")
    L.append("")
    for r in results:
        L.append(f"### {r['coach_name']}({r['coach']}) — {os.path.basename(r['file'])} (코치 턴 {r['coach_turns']})")
        L.append("")
        if r["episodes"]:
            L.append("**사례** " + " / ".join(f"{c[:4]}: " + ", ".join(f"#{e['idx']} {e['leader_turns']}턴 {e.get('status') or '진행'}(슬롯 {e.get('slots_filled') if e.get('slots_filled') is not None else '-'})" for e in eps)
                                           for c, eps in r["episodes"].items()))
            L.append(f"  챕터 리더 턴: " + ", ".join(f"{c[:4]} {n}" for c, n in r["chapter_leader_turns"].items())
                     + f" · 여는 턴 {r['open_turns']} · 재질문 {r['retry_turns']} · SWEEP 턴 {r['sweep_turns']} · 앵무새 미해결 {r['parrot_turns']}")
            for c, v in r["coverage"].items():
                L.append(f"  커버리지 {c}: {v['covered']}/{v['total']} {v['covered_subs']} · 탐색 {v.get('asked', '-')}/{v['total']} · 미확인 {v['unconfirmed']} · 미탐색 {v['not_explored']}")
            L.append("")
        L.append(f"**누설 턴** (전체 {r['leak_total']}건 · 엄격 {r['leak_strict_total']}건 — 엄격 = 가드 사전 기준)")
        if not r["leaks"]:
            L.append("- 없음")
        for lk in r["leaks"]:
            parts = []
            if lk["words"]:
                parts.append("어휘: " + ", ".join(lk["words"]))
            if lk["state"]:
                parts.append("상태보고: " + " / ".join(lk["state"]))
            L.append(f"- t{lk['t'] if lk['t'] is not None else '-'}: " + " | ".join(parts))
        L.append("")
        L.append(f"**ALIGN 검사** ({r['align_pass']}/{r['align_total']})")
        if not r["align"]:
            L.append("- ALIGN 턴 없음")
        for a in r["align"]:
            L.append(f"- t{a['t']}: {'PASS' if a['pass'] else 'FAIL — ' + '; '.join(a['reasons'])}")
        L.append("")
        L.append(f"**되받기 문제 턴** ({len(r['receive_issues'])}건)" + (f" · 형식 미해결 사유 {r['format_miss']}" if r["format_miss"] else ""))
        if not r["receive_issues"]:
            L.append("- 없음")
        for x in r["receive_issues"][:12]:
            L.append(f"- t{x['t']} ({x['kind']}, {x['instr']}): 리더 \"{x['user']}\" → 코치 \"{x['coach']}\"")
        L.append("")
        L.append(f"**질문 잘림** ({r['truncated_total']}건)")
        if not r["truncated"]:
            L.append("- 없음")
        for tq in r["truncated"]:
            L.append(f"- t{tq['t']}: {tq['sentence']}")
        L.append("")
        L.append(f"**반복 미감지** (a {r['repeat_a_missed']}/{r['repeat_a_cases']}, b {r['repeat_b_missed']}/{r['repeat_b_cases']})")
        if not r["repeat_missed"]:
            L.append("- 없음")
        for m in r["repeat_missed"]:
            L.append(f"- t{m['t']} ({m['kind']}): 사용자 \"{m['user']}\" → 코치 \"{m['coach']}\"")
        if r["repeat_issues"]:
            L.append("")
            L.append("**고정 문장 연속 반복** " + "; ".join(f"t{x['t']} {x['kind']}: {x['text']}" for x in r["repeat_issues"]))
        L.append("")
        L.append(f"**P4** 슬롯/챕터 {r['slot_by_chapter']} · 평가 말투 {r['praise_turns']}턴 · 흉터 {r['broken_turns']}턴 · 고정문장≥3회 {len(r['repeat3'])}종 · "
                 f"여는 문장 {r['opener_modes']} · SWEEP 다리 누락 {r['sweep_bridge_missing']} · 종료 요약 {r['close_modes']} · 범위 문장 폴백 {r['scope_fallback_turns']}")
        for x in r["praise_issues"][:8]:
            L.append(f"- 평가 말투 t{x['t']} ({x['instr']}): {x['sentence']}")
        for x in r["broken_issues"][:8]:
            L.append(f"- 흉터 t{x['t']} ({x['instr']}): {x['sentence']}")
        for x in r["repeat3"][:8]:
            L.append(f"- 고정문장 {x['n']}회: {x['sentence']}")
        L.append("")
        L.append("**어미 분포** " + (", ".join(f"{k} {v}" for k, v in r["endings"].items()) or "질문 없음"))
        L.append("")
    L.append("---")
    L.append(f"누설 사전 크기: {lexicon_size(lex)} (한글 {len(lex['korean'])} · 영문 {len(lex['english'])}; "
             f"코치 발화 어휘로 제외된 후보 {lex['excluded_coach']}개). 상태 보고 어간: {', '.join(lex['state_stems'])}")
    top = list(lex["korean"].items())[:50]
    L.append("상위 50개(한글): " + ", ".join(f"{w}({n})" for w, n in top))
    L.append("영문 상위 20개: " + ", ".join(f"{w}({n})" for w, n in list(lex["english"].items())[:20]))
    return "\n".join(L)


def render_lexicon(lex: dict) -> str:
    L = [f"# 누설 사전 — 총 {lexicon_size(lex)} (한글 {len(lex['korean'])}, 영문 {len(lex['english'])})", "", "## 한글"]
    for w, n in lex["korean"].items():
        L.append(f"{w}\t{n}\t{','.join(lex['sources'].get(w, []))}")
    L.append("")
    L.append("## 영문")
    for w, n in lex["english"].items():
        L.append(f"{w}\t{n}\t{','.join(lex['sources'].get(w, []))}")
    return "\n".join(L)


# ══════════════════════════════════════════════════════════════════════════════
# CLI
# ══════════════════════════════════════════════════════════════════════════════
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="코치 재생 전문 품질 린트")
    ap.add_argument("files", nargs="*", help="replay_result_*.json / sim_result_*.json")
    ap.add_argument("--json", dest="json_out", help="집계 dict 를 저장할 경로")
    ap.add_argument("--dump-lexicon", action="store_true", help="자동 추출된 누설 사전을 출력")
    args = ap.parse_args(argv)

    lex = build_lexicon()
    if args.dump_lexicon:
        print(render_lexicon(lex))
        if not args.files:
            return 0
        print()
    if not args.files:
        ap.error("입력 파일이 없습니다 (또는 --dump-lexicon 을 쓰세요).")

    results = []
    for f in args.files:
        with open(f, encoding="utf-8") as fh:
            data = json.load(fh)
        results.append(analyze(data, lex, label=f))
    cross = cross_anchor_pairs(results)
    print(render_markdown(results, cross, lex))
    if args.json_out:
        payload = {"files": results, "cross": cross,
                   "lexicon": {"size": lexicon_size(lex), "korean": lex["korean"], "english": lex["english"]}}
        with open(args.json_out, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=1)
        print(f"\n(집계 JSON 저장: {args.json_out})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
