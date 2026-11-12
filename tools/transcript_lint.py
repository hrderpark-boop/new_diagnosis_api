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
def _slot_sentence_kept(coach_name: str, text: str, slot_kind: str | None = None, slot_text: str | None = None) -> bool:
    """페르소나 슬롯 문장이 본문에 남아 있는가. (2026-11-11 P10-2) 슬롯 문장은 고정 문구가 아니라 사례 내용을 넣어 쓴 렌더본 —
    guard_log 의 slot_text 가 본문에 있는지로 본다. slot_text 가 없는 옛 로그는 Olivia 대조 꼴만 본다."""
    from diag_project.services.persona_voice import _CONTRAST_RE
    _n = lambda t: re.sub(r"\s+", "", t or "")   # noqa: E731
    if slot_text:
        return _n((split_sentences(slot_text) or [slot_text])[0]) in _n(text)
    return coach_name == "Olivia" and slot_kind != "Michael_q" and bool(_CONTRAST_RE.search(text or ""))


def _fixed_pool_norm() -> set[str]:
    """고정 문장(ALIGN 다리) 정규화 집합 — 평가 말투·흉터 집계에서 제외. (P10-2) 슬롯 문장은 렌더본이라 턴별 guard slot_text 로 뺀다."""
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
# ── (2026-11-12 P11) 11/12 운영 Daniel 세션 검토 항목 ─────────────────────────────────────────────
_POLITE_END_L = re.compile(r"(요|죠)[.?!…~\"'”’]*$")
_FORMAL_END_L = re.compile(r"(니다|니까|십시오|시오)[.?!…~\"'”’]*$")
_RECV_END_L = re.compile(r"(군요|네요)[.?!…~\"'”’]*$")


def mixed_register_sentences(text: str) -> tuple[list[str], list[str]]:
    """한 턴 안의 (해요체 문장, 합쇼체 문장). 받는 문장의 '~군요/~네요' 는 어느 쪽으로도 세지 않는다(예외 유지).
    둘 다 비어 있지 않으면 그 턴은 말투가 섞인 턴이다. 목록 줄('· …')과 따옴표 안의 인용은 보지 않는다."""
    from diag_project.services.output_guard import split_sentences as _ss
    polite, formal = [], []
    for line in (text or "").split("\n"):
        if line.strip().startswith("·"):
            continue
        for s in _ss(line):
            s = s.strip()
            if not s:
                continue
            bare = re.sub(r"['‘“\"][^'’”\"\n]{0,80}['’”\"]", "", s).strip()
            if _RECV_END_L.search(bare) and not bare.endswith("?"):
                continue
            if re.search(r"(는지요|은지요|인지요|신지요|을지요|지요)[.?!…~]*$", bare):
                continue                      # '~는지요?' 는 합쇼체 코치(Daniel)에게 허용된 질문 변주(P9) — 어느 쪽으로도 세지 않는다
            if _FORMAL_END_L.search(bare):
                formal.append(s)
            elif _POLITE_END_L.search(bare):
                polite.append(s)
    return polite, formal


def p11_analyze(data: dict) -> dict:
    """P11 열 — 말투 혼용 턴 · 받는 문장 금지 꼴 · 예고 문장 · 리더가 하지 않은 말 귀속 · 때 이른 감사 · 질문 완결성 · 받기 2문장 이상 ·
    받기 겹침 분포 · 슬롯 끝맺음 반복·1인칭 · 여는 문장 틀 분포 · 같은 답 안내 반복 · 다시 묻기 턴."""
    from statistics import median
    from diag_project.services.output_guard import is_question as _isq, split_sentences as _ss
    from diag_project.services.receive_check import receive_statements as _rst
    from diag_project.services.slot_render import _ending_key, has_leader_first_person
    from diag_project.services.turn_checks import (
        is_announcement, is_thanks_sentence, question_issues, receive_ban_reason, receive_overlap, unsaid_spans,
    )
    rows = data.get("rows") or []
    out: dict = {"mixed_turns": [], "recv_ban": [], "announce": [], "unsaid": [], "thanks": [], "q_issues": [], "recv_multi": [],
                 "overlap": [], "slot_endings": [], "slot_first_person": [], "opener_frames": [], "dup_lines": [], "reask": [],
                 "guard": {"recv_ban": 0, "recv_trim": 0, "q_default": 0, "q_regen": 0, "q_repaired": 0, "announce_cut": 0, "thanks_cut": 0, "unsaid_attr": 0}}
    leader_all: list[str] = []
    last_user = ""
    names = [v.get("name") for v in COMPETENCY_FRAMEWORK.values() if v.get("name")] + ["네"]
    for row in rows:
        content = row.get("content") or ""
        if row.get("role") == "user":
            leader_all.append(content); last_user = content
            continue
        g = _guard(row)
        instr = row.get("instr") or g.get("instr") or ""
        t = row.get("t")
        pol, frm = mixed_register_sentences(content)
        if pol and frm:
            out["mixed_turns"].append({"t": t, "instr": instr, "polite": pol[0][:60], "formal": frm[0][:60]})
        for k in ("recv_ban", "unsaid_attr"):
            if g.get(k):
                out["guard"][k] += 1
        for k in ("recv_trim", "announce_cut", "thanks_cut"):
            if g.get(k):
                out["guard"][k] += 1
        qc = str(g.get("q_complete") or "")
        if qc.startswith("default"):
            out["guard"]["q_default"] += 1
        elif qc == "regen":
            out["guard"]["q_regen"] += 1
        elif qc == "repaired":
            out["guard"]["q_repaired"] += 1
        if g.get("opener_frame") is not None and str(g.get("opener") or "").startswith(("llm", "bare")):
            out["opener_frames"].append(int(g["opener_frame"]))
        if g.get("reask"):
            out["reask"].append({"t": t, "kind": g.get("reask"), "user": last_user[:30], "coach": content[:90]})
        if instr == "INPUT_REPEATED":
            out["dup_lines"].append(content[:60])
        if g.get("slot_text"):
            st = str(g["slot_text"])
            out["slot_endings"].append(_ending_key(st))
            if has_leader_first_person(st):
                out["slot_first_person"].append({"t": t, "sentence": st[:80]})
        if instr not in ("EPISODE_PROBE", "NO_CASE_REFRAME", "SWEEP_FOLLOWUP", "EPISODE_OPEN", "SWEEP_ANCHOR"):
            continue
        fixed = {re.sub(r"\s+", "", str(g.get("slot_text") or ""))}
        sents = [x.strip() for x in _ss(content) if x.strip()]
        has_real_q = any(_isq(x) and not is_announcement(x) for x in sents)
        closing = bool(g.get("closed"))
        for s in sents:
            if re.sub(r"\s+", "", s) in fixed:
                continue
            r = receive_ban_reason(s)
            if r:
                out["recv_ban"].append({"t": t, "instr": instr, "why": r, "sentence": s[:80]})
            if has_real_q and is_announcement(s) and instr in ("EPISODE_PROBE", "NO_CASE_REFRAME", "SWEEP_FOLLOWUP"):
                out["announce"].append({"t": t, "instr": instr, "sentence": s[:80]})
            if is_thanks_sentence(s) and not closing:
                out["thanks"].append({"t": t, "instr": instr, "sentence": s[:80]})
            if instr in ("EPISODE_PROBE", "NO_CASE_REFRAME", "SWEEP_FOLLOWUP"):
                bad = unsaid_spans(s, leader_all, names)
                if bad:
                    out["unsaid"].append({"t": t, "instr": instr, "words": bad[:3], "sentence": s[:80]})
        if instr in ("EPISODE_PROBE", "NO_CASE_REFRAME", "SWEEP_FOLLOWUP") and not g.get("reask"):
            qs = [x for x in sents if _isq(x)]
            if qs:
                iss = question_issues(qs[-1], last_user)
                if iss and not str(g.get("q_complete") or "").startswith("default"):
                    out["q_issues"].append({"t": t, "instr": instr, "why": iss, "sentence": qs[-1][:80]})
            recv = [x for x in _rst(content) if re.sub(r"\s+", "", x) not in fixed]
            if len(recv) > 1:
                out["recv_multi"].append({"t": t, "n": len(recv), "sentence": " ".join(recv)[:100]})
            if recv:
                a, b, n = receive_overlap(recv[0], last_user)
                out["overlap"].append({"t": t, "from_user": a, "covered": b, "n": n, "sentence": recv[0][:80]})
    ov = out["overlap"]
    out["overlap_stats"] = ({"n": len(ov), "from_user_p50": round(median(x["from_user"] for x in ov), 2), "from_user_max": max(x["from_user"] for x in ov),
                             "covered_p50": round(median(x["covered"] for x in ov), 2), "covered_p90": sorted(x["covered"] for x in ov)[int(len(ov) * 0.9) - 1 if len(ov) >= 2 else 0],
                             "covered_max": max(x["covered"] for x in ov)} if ov else {})
    ends = Counter(e for e in out["slot_endings"] if e)
    out["slot_ending_repeat"] = {k: v for k, v in ends.items() if v > 1}
    fr = Counter(out["opener_frames"])
    out["opener_frame_counts"] = dict(sorted(fr.items()))
    out["opener_frame_over"] = {k: v for k, v in fr.items() if v > 2}
    out["opener_frame_adjacent"] = sum(1 for a, b in zip(out["opener_frames"], out["opener_frames"][1:]) if a == b)
    dl = Counter(out["dup_lines"])
    out["dup_line_repeat"] = {k: v for k, v in dl.items() if v > 1}
    return out


def render_p11(coach_name: str, p: dict) -> list[str]:
    L: list[str] = []
    g = p["guard"]
    L.append(f"**P11** 말투 혼용 턴 {len(p['mixed_turns'])} · 받는 문장 금지 꼴 {len(p['recv_ban'])} · 예고 문장 {len(p['announce'])} · 하지 않은 말 귀속 {len(p['unsaid'])} · "
             f"때 이른 감사 {len(p['thanks'])} · 질문 완결성 위반 {len(p['q_issues'])} · 받기 2문장 이상 {len(p['recv_multi'])} · 슬롯 끝맺음 반복 {p['slot_ending_repeat'] or 0} · "
             f"슬롯 1인칭 {len(p['slot_first_person'])} · 여는 문장 틀 {p['opener_frame_counts']}(3회 이상 {p['opener_frame_over'] or 0}, 연속 같은 틀 {p['opener_frame_adjacent']}) · "
             f"같은 답 안내 반복 {p['dup_line_repeat'] or 0} · 다시 묻기 턴 {len(p['reask'])}")
    L.append(f"- 처리 기록: 금지 꼴 삭제 {g['recv_ban']}턴 · 받기 줄임 {g['recv_trim']}턴 · 질문 수선 {g['q_repaired']} / 재생성 {g['q_regen']} / 기본 질문 {g['q_default']} · "
             f"예고 삭제 {g['announce_cut']}턴 · 감사 삭제 {g['thanks_cut']}턴 · 귀속 삭제 {g['unsaid_attr']}턴")
    if p.get("overlap_stats"):
        s = p["overlap_stats"]
        L.append(f"- 받기 겹침({s['n']}턴): 받기 어절 중 리더 답에서 온 비율 중앙값 {s['from_user_p50']}·최대 {s['from_user_max']} / "
                 f"리더 답 어절 중 받기에 다시 나온 비율 중앙값 {s['covered_p50']}·90% {s['covered_p90']}·최대 {s['covered_max']}")
    for key, title in (("mixed_turns", "말투 혼용"), ("recv_ban", "받는 문장 금지 꼴"), ("announce", "예고 문장"), ("unsaid", "하지 않은 말 귀속"),
                       ("thanks", "때 이른 감사"), ("q_issues", "질문 완결성"), ("recv_multi", "받기 2문장 이상"), ("slot_first_person", "슬롯 1인칭")):
        for it in p[key][:8]:
            extra = it.get("why") or it.get("words") or ""
            body = it.get("sentence") or f"해요체 '{it.get('polite')}' / 합쇼체 '{it.get('formal')}'"
            L.append(f"- [P11 {title}] {coach_name} t{it['t']} {it.get('instr', '')} {extra}: {body}")
    for it in p["reask"][:8]:
        L.append(f"- [P11 다시 묻기 {it['kind']}] {coach_name} t{it['t']}: 리더 \"{it['user']}\" → 코치 \"{it['coach']}\"")
    top = sorted(p["overlap"], key=lambda x: -x["covered"])[:3]
    for it in top:
        L.append(f"- [P11 받기 겹침 상위] {coach_name} t{it['t']} 되풀이 {it['covered']} · 받기 기준 {it['from_user']} · 어절 {it['n']}: {it['sentence']}")
    return L


def p11b_analyze(data: dict) -> dict:
    """P11b 열 — 재생성 사유별 건수 · 틀린 활용 꼴 · 내용 없는 연결 문구 · 여는 턴의 진행 해설·기대는 머리 · 관찰·응원 슬롯 턴의 꼴과 낱말 반복 ·
    '리더님께서' 로 시작하는 받기 수 · 되풀이 받기(상한 초과) · 한 문장 안 두 질문 · 안내 중복 · 보완 사례 승격 · 휴식 제안."""
    from diag_project.services.conjugation import bad_form
    from diag_project.services.output_guard import is_question as _isq, split_sentences as _ss
    from diag_project.services.receive_check import receive_statements as _rst
    from diag_project.services.slot_render import repeated_turn_words
    from diag_project.services.turn_checks import (
        _LEAN_START_RE, _LINK_CLAUSE_RE, RECEIVE_REPEAT_MAX, RECEIVE_REPEAT_MIN_CHUNKS, inline_question_clauses, is_progress_commentary,
        leader_prefix_wrong_subject, receive_overlap, starts_with_leader_prefix,
    )
    rows = data.get("rows") or []
    out: dict = {"open_no_q": [], "probe_no_q": [], "near_repeat_q": [],
                 "regen_why": Counter(), "regen_turns": 0, "bad_form": [], "link": [], "commentary": [], "lean_start": [], "slot_turn_shape": [],
                 "slot_repeat_word": [], "leader_prefix": [], "leader_prefix_subject": [], "recv_repeat": [], "inline_two_q": [], "intro_dup": [],
                 "promote": [], "pause": [], "pause_block": [],
                 "guard": Counter()}
    leader_all: list[str] = []
    last_user = ""
    prev_q: dict = {}
    for row in rows:
        content = row.get("content") or ""
        if row.get("role") == "user":
            leader_all.append(content); last_user = content
            continue
        g = _guard(row)
        instr = row.get("instr") or g.get("instr") or ""
        t = row.get("t")
        why = [str(x) for x in (g.get("regen_why") or [])]
        if why:
            out["regen_turns"] += 1
            for w in why:
                out["regen_why"][w] += 1
        for k in ("conj_fix", "intro_dup", "link_cut", "commentary_cut", "lean_start", "lead_prefix", "recv_cap", "q_clause", "reask_unsaid", "slot_turn"):
            if g.get(k):
                out["guard"][k] += 1
        if str(g.get("q_complete") or "").endswith("(tail)"):
            out["guard"]["q_tail_default"] += 1
        if g.get("sweep_promote"):
            out["promote"].append({"t": t, "how": g.get("sweep_promote"), "closed": g.get("closed")})
        if g.get("pause_block"):
            out["pause_block"].append({"t": t, "closed": g.get("pause_block")})
        if row.get("probe") == "SUGGEST_PAUSE" or "쉬어" in content and instr in ("EPISODE_OPEN", "SWEEP_ANCHOR") and g.get("closed") is None:
            out["pause"].append({"t": t, "instr": instr})
        bf = bad_form(content)
        if bf:
            out["bad_form"].append({"t": t, "instr": instr, "why": bf, "sentence": next((x.strip()[:80] for x in _ss(content) if bad_form(x)), content[:80])})
        sents = [x.strip() for x in _ss(content) if x.strip()]
        if instr == "DIAGNOSIS_INTRO":
            ann = [x for x in sents if re.search(r"안내드리겠습니다|안내드릴게요|안내해 드릴게요", x)]
            if len(ann) >= 2:
                out["intro_dup"].append({"t": t, "sentence": " / ".join(a[:40] for a in ann[:2])})
        if instr not in ("EPISODE_PROBE", "NO_CASE_REFRAME", "SWEEP_FOLLOWUP", "EPISODE_OPEN", "SWEEP_ANCHOR"):
            continue
        slot = str(g.get("slot_text") or "")
        fixed = {re.sub(r"\s+", "", slot)} - {""}
        # (시뮬 p11b) 질문 없이 끝난 턴 · 같은 영역에서 직전 질문을 거의 그대로 되풀이한 턴(다시 묻기·같은 답 안내 턴 제외)
        _qs_all = [x for x in sents if _isq(x)]
        if not _qs_all:
            out["open_no_q" if instr in ("EPISODE_OPEN", "SWEEP_ANCHOR") else "probe_no_q"].append({"t": t, "instr": instr, "sentence": content[:90]})
        else:
            import difflib as _dl
            _nq = re.sub(r"[\s.,?!'\"]", "", _qs_all[-1])
            if prev_q.get("ch") == _chapter_of(row) and not g.get("reask") and prev_q.get("q") and _dl.SequenceMatcher(None, prev_q["q"], _nq).ratio() >= 0.8:
                out["near_repeat_q"].append({"t": t, "instr": instr, "sentence": _qs_all[-1][:90]})
            prev_q.update({"ch": _chapter_of(row), "q": _nq})
        for x in sents:
            if re.sub(r"\s+", "", x) in fixed:
                continue
            if _LINK_CLAUSE_RE.search(x):
                out["link"].append({"t": t, "instr": instr, "sentence": x[:90]})
            if instr in ("EPISODE_OPEN", "SWEEP_ANCHOR") and is_progress_commentary(x):
                out["commentary"].append({"t": t, "instr": instr, "sentence": x[:90]})
        if instr in ("EPISODE_OPEN", "SWEEP_ANCHOR"):
            for x in sents:
                if _LEAN_START_RE.match(x) and not _isq(x):
                    out["lean_start"].append({"t": t, "instr": instr, "sentence": x[:90]})
        recv = [x for x in _rst(content) if re.sub(r"\s+", "", x) not in fixed]
        if slot and g.get("slot_kind") in ("observation", "cheer"):
            if recv:
                out["slot_turn_shape"].append({"t": t, "sentence": " ".join(recv)[:90]})
            rest = " ".join(x for x in sents if re.sub(r"\s+", "", x) not in fixed)
            rw = repeated_turn_words(slot, rest, leader_all)
            if rw:
                out["slot_repeat_word"].append({"t": t, "words": rw[:3], "sentence": slot[:90]})
        if recv and not g.get("reask"):
            if starts_with_leader_prefix(recv[0]):
                out["leader_prefix"].append({"t": t, "sentence": recv[0][:80]})
                if leader_prefix_wrong_subject(recv[0]):
                    out["leader_prefix_subject"].append({"t": t, "sentence": recv[0][:80]})
            a_, b_, n_ = receive_overlap(recv[0], last_user)
            if b_ >= RECEIVE_REPEAT_MAX and n_ >= RECEIVE_REPEAT_MIN_CHUNKS:
                out["recv_repeat"].append({"t": t, "covered": b_, "n": n_, "sentence": recv[0][:90]})
        if instr in ("EPISODE_PROBE", "NO_CASE_REFRAME", "SWEEP_FOLLOWUP"):
            qs = [x for x in sents if _isq(x) and re.sub(r"\s+", "", x) not in fixed]
            if qs and len(inline_question_clauses(qs[-1])) >= 2:
                out["inline_two_q"].append({"t": t, "sentence": qs[-1][:100]})
    from diag_project.services.receive_check import is_quote_receive as _iqr
    probe = [r for r in rows if r.get("role") != "user" and (r.get("instr") or _guard(r).get("instr")) in ("EPISODE_PROBE", "NO_CASE_REFRAME", "SWEEP_FOLLOWUP")]
    out["probe_turns"] = len(probe)
    out["probe_with_statement"] = sum(1 for r in probe if any(not _isq(x) for x in _ss(r.get("content") or "") if x.strip()))
    out["quote_receives"] = [{"t": r.get("t"), "sentence": x.strip()[:80]} for r in rows if r.get("role") != "user"
                             for x in _ss(r.get("content") or "") if _iqr(x)]
    out["format_miss"] = [{"t": r.get("t"), "miss": _guard(r).get("format_miss")} for r in rows if r.get("role") != "user" and _guard(r).get("format_miss")]
    out["regen_why"] = dict(out["regen_why"].most_common())
    out["guard"] = dict(out["guard"])
    return out


def render_p11b(coach_name: str, p: dict) -> list[str]:
    L: list[str] = []
    L.append(f"**P11b** 틀린 활용 꼴 {len(p['bad_form'])} · 안내 중복 {len(p['intro_dup'])} · 연결 문구 {len(p['link'])} · 여는 턴 진행 해설 {len(p['commentary'])} · "
             f"기대는 머리 {len(p['lean_start'])} · 슬롯 턴에 받기 남음 {len(p['slot_turn_shape'])} · 슬롯 턴 낱말 반복 {len(p['slot_repeat_word'])} · "
             f"'리더님께서' 받기 {len(p['leader_prefix'])}(주어 어긋남 {len(p['leader_prefix_subject'])}) · 되풀이 받기 {len(p['recv_repeat'])} · "
             f"한 문장 안 두 질문 {len(p['inline_two_q'])}")
    L.append(f"- (P11c) 탐침 턴 {p.get('probe_turns')}개 중 질문 앞에 평서문이 있는 턴 {p.get('probe_with_statement')} · 구절 인용 꼴 받기 {len(p.get('quote_receives') or [])}회(세션 2회까지) · "
             f"형식미해결 {p.get('format_miss') or 0}")
    L.append(f"- 질문 없이 끝난 여는 턴 {len(p['open_no_q'])} · 질문 없이 끝난 탐침 턴 {len(p['probe_no_q'])} · 직전 질문을 거의 그대로 되풀이 {len(p['near_repeat_q'])}")
    L.append(f"- 재생성 걸린 턴 {p['regen_turns']} · 사유별 {p['regen_why'] or '없음'}")
    L.append(f"- 처리 기록(턴 수): {p['guard'] or '없음'}")
    L.append(f"- 보완 사례 승격 {p['promote'] or '없음'} · 휴식 제안 {len(p['pause'])}회 · 자연스러운 닫힘이 아니라 내지 않음 {p['pause_block'] or '없음'}")
    for key, title in (("open_no_q", "질문 없는 여는 턴"), ("probe_no_q", "질문 없는 탐침 턴"), ("near_repeat_q", "질문 되풀이"),
                       ("bad_form", "틀린 활용 꼴"), ("intro_dup", "안내 중복"), ("link", "연결 문구"), ("commentary", "진행 해설"), ("lean_start", "기대는 머리"),
                       ("slot_turn_shape", "슬롯 턴에 받기"), ("slot_repeat_word", "슬롯 턴 낱말 반복"), ("leader_prefix_subject", "'리더님께서' 주어 어긋남"),
                       ("recv_repeat", "되풀이 받기"), ("inline_two_q", "한 문장 안 두 질문")):
        for it in p[key][:8]:
            extra = it.get("why") or it.get("words") or ""
            L.append(f"- [P11b {title}] {coach_name} t{it['t']} {it.get('instr', '')} {extra}: {it.get('sentence')}")
    return L


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
        "slot_per_chapter_max": 0, "slot_by_chapter": {}, "register_mix": 0, "register_mix_open": 0, "register_issues": [], "close_side_q": 0, "close_side_issues": [],
        "no_referent_q": 0, "no_referent_issues": [], "praise_turns": 0, "praise_issues": [], "broken_turns": 0, "broken_issues": [],
        "repeat3": [], "opener_modes": {}, "sweep_bridge_missing": 0, "close_modes": {}, "scope_fallback_turns": 0,
        # (2026-11-11 P10) 입버릇 초과(궁금 챕터 1·이번에는 쪽 이야기 세션 2·채움 문장 0) · 질문 2개 이상 턴 · 고정 받기(같은 받는 문장 반복) ·
        #   받기 폴백(리더 절 인용) · 슬롯 문장에 사례 낱말 없음 · 스몰톡 처리 · 15자 이하 대상 없는 질문
        "phrase_over": {"gunggeum": 0, "side_story": 0, "filler": 0}, "phrase_issues": [], "multi_q_turns": 0, "multi_q_issues": [],
        "fixed_receive": 0, "fixed_receive_issues": [], "receive_fallback_turns": 0, "slot_generic": 0, "slot_issues": [],
        "smalltalk": None, "smalltalk_total_s": None, "smalltalk_regen": None, "short_bare_q": 0, "short_bare_issues": [],
        "summary_eval": 0, "summary_eval_issues": [], "empty_receive": 0, "empty_receive_issues": [],
        "instruction_echo": 0, "instruction_echo_issues": [],
        # (2026-11-11 재생성 예산) 질문 지워짐 = 탐침 턴에 직접 묻는 문장이 없다(질문 없음, 또는 '예를 들어 … 주시면 돼요' 도움말만 남음) · 재생성 2회 이상 턴(예산 위반)
        "question_lost": 0, "question_lost_issues": [], "regen_over": 0, "regen_turns": 0, "turn_totals": [],
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
    _recv_counter: Counter = Counter()      # (P10-5) 받는 문장(첫 평서문) 세션 누적 — 같은 문장 2회 이상 = 고정 받기
    _gg_by_ch: Counter = Counter()          # (P10-3) '궁금' 챕터별
    _side_n = 0                             # (P10-3) '이번에는 ~ 쪽 이야기' 세션 누적
    _leader_by_ep: dict[tuple, list[str]] = defaultdict(list)   # (챕터, 사례 번호) → 그 사례의 리더 답
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
            # (2026-11-12 P11c-1) 받는 문장이 꼭 있어야 하는 턴은 닫고 넘어가는 턴(여는·보완 앵커)뿐 — 탐침 턴은 질문만 나가도 정상이라 세지 않는다
            _recv_req = instr in ("EPISODE_OPEN", "SWEEP_ANCHOR")
            res["receive_turns"] += 1 if _recv_req else 0
            _has_r, _quoted_r = check_receive(content, prev_user)
            if not _recv_req:
                pass
            elif not _has_r:
                res["no_receive_turns"] += 1
                res["receive_issues"].append({"t": t, "kind": "none", "instr": instr, "coach": content[:90], "user": (prev_user or "")[:60]})
            elif not _quoted_r and not _is_no_case_text(prev_user):   # (2026-11-06 P7) 사례 아님 답에는 인용 요구 없음(8-w 와 같은 기준)
                res["receive_no_quote_turns"] += 1
                res["receive_issues"].append({"t": t, "kind": "no_quote", "instr": instr, "coach": content[:90], "user": (prev_user or "")[:60]})
            # (2026-11-11 P10-5) 고정 받기 — 같은 받는 문장이 세션에서 되풀이되는가(어디에나 붙는 문구). 시스템 여는 문장·슬롯은 받는 문장이 아니다
            from diag_project.services.receive_check import receive_statements as _rst_l
            _r_first = next((x for x in _rst_l(content) if norm_sentence(x) != norm_sentence(g.get("slot_text") or "")), "")
            if _r_first and not g.get("receive_fallback"):
                _rk = norm_sentence(_r_first)
                _recv_counter[_rk] += 1
                if _recv_counter[_rk] == 2:
                    res["fixed_receive"] += 1
                    res["fixed_receive_issues"].append({"t": t, "instr": instr, "sentence": _r_first[:90]})
            if g.get("receive_fallback"):
                res["receive_fallback_turns"] += 1
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
            _free_l = [x for x in _sents_l if norm_sentence(x) not in _fixed_norm and norm_sentence(x) != norm_sentence(g.get("slot_text") or "")]
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
        # 7-1. (2026-11-10 P9) 말투 섞임 · 닫는 턴 질문 · 주어 없는 질문 — 셋 다 0 이 통과 기준
        if chapter and instr != "DIAGNOSIS_INTRO":
            from diag_project.services.output_guard import _CLOSE_SIDE_BAN_RE as _csb_l, is_question as _isq_l, question_lacks_referent as _qlr_l
            from diag_project.services.persona_register import register_violations as _rv_l
            _body_l = " ".join(ln for ln in content.split("\n") if ln.strip() and not ln.strip().startswith("·"))
            _body_l = re.sub(r"['‘“\"][^'’”\"]{1,80}['’”\"]", "''", _body_l)     # 따옴표 인용(정의·리더 말)은 말투 검사에서 뺀다
            # (승인 조건 1) 어미 검사는 질문 문장(전 턴) + 시스템이 자리를 정한 평서문(여는 문장의 '왜 묻는지', 범위 문장)만 — 받는 문장은 보지 않는다
            _rv = _rv_l(coach_name, _body_l, scope="questions")
            _slot_l = []
            if instr in ("EPISODE_OPEN", "COMPETENCY_ASK", "DIAGNOSIS_CONFIRM") or (instr == "SWEEP_ANCHOR" and g.get("sweep_bridge")):
                # (2026-11-11 P10-4) 여는 문장의 '왜 묻는지'·범위 문장·첫 영역 다리·SWEEP 다리는 코치 어미 강제(strict) — 받는 문장(첫 평서문)만 자유
                _sb = [x.strip() for x in split_sentences(_body_l) if x.strip()]
                _qi_l = [i for i, x in enumerate(_sb) if _isq_l(x)]
                _lo_l = 0 if instr in ("COMPETENCY_ASK", "DIAGNOSIS_CONFIRM") else 1
                if _qi_l:
                    for _x in _sb[_lo_l:_qi_l[-1]]:
                        if not _isq_l(_x):
                            _slot_l.extend(_rv_l(coach_name, _x, scope="strict"))
            _rv = _rv + [x for x in _slot_l if x not in _rv]
            if _rv:
                res["register_mix"] += len(_rv)
                if instr in ("EPISODE_OPEN", "SWEEP_ANCHOR", "COMPETENCY_ASK", "DIAGNOSIS_CONFIRM"):
                    res["register_mix_open"] += len(_rv)
                res["register_issues"].append({"t": t, "instr": instr, "sentence": _rv[0][:90]})
            _ss_p9 = [x.strip() for x in split_sentences(content) if x.strip()]
            if instr in ("EPISODE_OPEN", "SWEEP_ANCHOR") and g.get("closed"):
                _qi = [i for i, x in enumerate(_ss_p9) if _isq_l(x)]
                _before = _ss_p9[:_qi[-1]] if _qi else _ss_p9
                _bad_c = [x for x in _before if _isq_l(x) or _csb_l.search(x)]
                # 여는 문장의 '왜 묻는지' 평서문은 닫는 쪽이 아니다 — 마지막 질문 바로 앞 1~2문장은 질문일 때만 센다
                _bad_c = [x for x in _bad_c if _isq_l(x) or x in _before[:max(0, len(_before) - 2)]]
                if _bad_c:
                    res["close_side_q"] += 1
                    res["close_side_issues"].append({"t": t, "instr": instr, "sentence": _bad_c[0][:90]})
            if instr in ("EPISODE_PROBE", "NO_CASE_REFRAME", "SWEEP_FOLLOWUP"):
                _qs_p9 = [x for x in _ss_p9 if _isq_l(x)]
                _trim_p9 = bool(g.get("one_q")) or len(_qs_p9) == len(_ss_p9)      # 라우트 8-w3 과 같은 조건: 질문 하나만 남긴 턴 또는 받는 문장이 없는 턴
                if _qs_p9 and _trim_p9 and _qlr_l(_qs_p9[-1], [prev_user or ""]):
                    res["no_referent_q"] += 1
                    res["no_referent_issues"].append({"t": t, "instr": instr, "sentence": _qs_p9[-1][:90]})
        # 7-2. (2026-11-11 P10) 입버릇 · 질문 수 · 슬롯 문장 · 짧은 질문
        if instr != "DIAGNOSIS_INTRO":
            from diag_project.services.output_guard import count_question_markers as _cqm_l, is_short_bare_question as _isbq_l
            from diag_project.services.phrase_caps import _GUNGGEUM_RE as _gg_l, _SIDE_STORY_RE as _ss_re_l, is_filler_sentence as _ifs_l
            _plain_l = "\n".join(ln for ln in content.split("\n") if not ln.strip().startswith("·"))
            _n_gg = len(_gg_l.findall(_plain_l))
            if _n_gg and chapter:
                _gg_by_ch[chapter] += _n_gg
                if _gg_by_ch[chapter] > 1:
                    res["phrase_over"]["gunggeum"] += 1
                    res["phrase_issues"].append({"t": t, "instr": instr, "kind": "궁금(챕터 1회 초과)", "sentence": next((x for x in split_sentences(_plain_l) if _gg_l.search(x)), "")[:90]})
            _n_side = len(_ss_re_l.findall(_plain_l))
            if _n_side:
                _side_n += _n_side
                if _side_n > 2:
                    res["phrase_over"]["side_story"] += 1
                    res["phrase_issues"].append({"t": t, "instr": instr, "kind": "이번에는 ~쪽 이야기(세션 2회 초과)", "sentence": next((x for x in split_sentences(_plain_l) if _ss_re_l.search(x)), "")[:90]})
            _fill_l = [x.strip() for x in split_sentences(_plain_l) if _ifs_l(x)]
            if _fill_l:
                res["phrase_over"]["filler"] += 1
                res["phrase_issues"].append({"t": t, "instr": instr, "kind": "채움 문장", "sentence": _fill_l[0][:90]})
            if chapter and instr != "COMPETENCY_ALIGN" and _cqm_l(_plain_l) >= 2:
                res["multi_q_turns"] += 1
                res["multi_q_issues"].append({"t": t, "instr": instr, "sentence": " / ".join(question_sentences(_plain_l))[:120]})
            if chapter and instr in _PROBE_INSTR:
                from diag_project.services.output_guard import is_aid_sentence as _ias_l
                _qs_all_l = question_sentences(_plain_l)
                if not [x for x in _qs_all_l if not _ias_l(x)]:
                    res["question_lost"] += 1
                    res["question_lost_issues"].append({"t": t, "instr": instr, "sentence": (_qs_all_l[-1] if _qs_all_l else _plain_l)[:110]})
                _qs_sb = question_sentences(_plain_l)
                if _qs_sb and _isbq_l(_qs_sb[-1], [prev_user or ""]):
                    res["short_bare_q"] += 1
                    res["short_bare_issues"].append({"t": t, "instr": instr, "sentence": _qs_sb[-1][:90]})
        if chapter and instr in ("EPISODE_OPEN", "COMPETENCY_ALIGN"):
            # (P10 p10b) 여는 문장이 지시문을 되읊었는가 — "무엇을 듣고 싶은지 말씀해 주세요: …"
            _echo_l = [x.strip() for x in split_sentences(_plain_l if instr != "DIAGNOSIS_INTRO" else "") if re.search(r"(무엇을 듣고 싶은지|말씀해\s*주세요\s*[:：]|꼴의 문장|①|②)", x)]
            if _echo_l:
                res["instruction_echo"] += 1
                res["instruction_echo_issues"].append({"t": t, "instr": instr, "sentence": _echo_l[0][:110]})
        if chapter and instr == "CHAPTER_READY_TO_END":
            # (P10 p10a) 종료 요약의 총평·해석 문장 — "…직접 쓰셨다는 점에서, 저희는 리더가 … 힘을 봐요."
            from diag_project.services.output_guard import _SUMMARY_INTERP_RE as _sir_l
            _ev_l = [x.strip() for x in split_sentences(content) if _sir_l.search(x.strip())]
            if _ev_l:
                res["summary_eval"] += 1
                res["summary_eval_issues"].append({"t": t, "instr": instr, "sentence": _ev_l[0][:110]})
        if chapter and instr in ("EPISODE_OPEN", "SWEEP_ANCHOR") and prev_user is not None:
            # (P10-5) 받을 낱말이 없는 답('네, 맞아요') 뒤의 여는 턴에 받는 문장이 붙었는가 — 내용 없는 받기
            from diag_project.services.receive_check import leader_nouns as _lnn_l, receive_statements as _rsts_l
            _rs_o = _rsts_l(content)
            if not _lnn_l(prev_user) and len(_rs_o) >= 2:      # 여는 문장의 '왜 묻는지' 1문장 말고도 평서문이 더 있다
                res["empty_receive"] += 1
                res["empty_receive_issues"].append({"t": t, "instr": instr, "sentence": _rs_o[0][:90]})
        if chapter and g.get("episode") is not None and prev_user:
            _leader_by_ep[(chapter, g.get("ep_kind", "episode"), int(g.get("episode")))].append(prev_user)
        if g.get("slot") and g.get("slot_text"):
            from diag_project.services.slot_render import slot_sentence_ok as _sso_l
            _ok_s, _why_s = _sso_l(g.get("slot_kind") or "", g.get("slot_text"), _leader_by_ep.get((chapter, g.get("ep_kind", "episode"), int(g.get("episode") or 0))) or [prev_user or ""],
                                   persona_name=coach_name)
            if not _ok_s and _why_s in ("no_case_words", "example_copied", "shape", "garbled_choice"):
                res["slot_generic"] += 1
                res["slot_issues"].append({"t": t, "instr": instr, "why": _why_s, "sentence": str(g.get("slot_text"))[:90]})
        if g.get("total"):
            res["turn_totals"].append(float(g.get("total")))
            _rg_l = int(g.get("regen") or 0) + int(g.get("render_regen") or 0)
            res["regen_turns"] += 1 if _rg_l else 0
            res["regen_over"] += 1 if _rg_l > 1 else 0
        if g.get("smalltalk"):
            res["smalltalk"] = g.get("smalltalk"); res["smalltalk_total_s"] = g.get("total"); res["smalltalk_regen"] = g.get("regen")
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
            if _slot_sentence_kept(coach_name, content, g.get("slot"), g.get("slot_text")):
                res["slot_kept"] += 1
            _st_now = re.sub(r"\s+", "", str(g.get("slot_text") or g.get("slot")))   # (P10-2) 같은 슬롯 '문장'이 이어서 나왔는가
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
    res["p11"] = p11_analyze(data)
    res["p11b"] = p11b_analyze(data)
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
    L.append("| 코치 | 파일 | 누설(전체/엄격) | 8-y | ALIGN | 잘림 | 미감지 a/b | 사례당 리더 턴(5~8 밖) | 6슬롯/종료 사례 | 챕터 리더 턴 최대 | 커버리지 | 미확인/미탐색 | 되받기 없음/미인용(대상) | 형식 재생성/미해결 | 고정문장 반복 꼬리/슬롯/앵커재사용 | 슬롯 사례(보존/턴) | 슬롯/챕터 최대 | 평가 말투 | 흉터 | 고정문장≥3회 | 좋습니다 최대 | 동일앵커 | 말투 섞임(여는·범위/전체) | 닫는 턴 질문 | 주어 없는 질문 | 입버릇 초과(궁금/쪽 이야기/채움) | 질문 2개+ 턴 | 고정 받기(반복/미인용/내용 없음) | 슬롯 일반문 | 짧은 질문 | 요약 총평 | 지시문 되읊기 | 질문 지워짐 | 재생성 턴(2회 이상) |")
    L.append("|---|---|---:|---:|---:|---:|---:|---|---:|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
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
                 f"{r['slot_per_chapter_max']} | {r['praise_turns']} | {r['broken_turns']} | {len(r['repeat3'])} | {r['good_lead_max']} | {same} | {r['register_mix_open']}/{r['register_mix']} | {r['close_side_q']} | {r['no_referent_q']} | "
                 f"{r['phrase_over']['gunggeum']}/{r['phrase_over']['side_story']}/{r['phrase_over']['filler']} | {r['multi_q_turns']} | "
                 f"{r['fixed_receive']}/{r['receive_no_quote_turns']}/{r['empty_receive']} | {r['slot_generic']} | {r['short_bare_q']} | {r['summary_eval']} | {r['instruction_echo']} | {r['question_lost']} | {r['regen_turns']}({r['regen_over']}) |")
    L.append("")
    L.append("- 미감지 a/b: (직전 사용자 턴 반복 미감지/발생) · (코치 질문 붙여넣기 미감지/발생)")
    L.append("- 사례당 리더 턴: 종료된 사례별 리더 턴 수(괄호는 5~8 밖 사례 수). 6슬롯/종료 사례: 6/6 로 닫힌 사례 수 / 종료 사례 수.")
    L.append("- 되받기 없음/미인용: 사례 턴(EPISODE_*/SWEEP_*)에서 되받기 평서문이 없는 턴 / 리더 명사구를 인용하지 않은 턴. 형식 재생성/미해결: 8-w 재생성이 돈 턴 / 2회 뒤에도 되받기가 없어 그대로 나간 턴(폴백 없음) — 둘 다 0 목표.")
    L.append("- 고정문장 반복: 시스템 앵커 꼬리(마지막 2어절) 연속 2회 / 같은 페르소나 슬롯 연속 2회 — 0 이어야 함.")
    L.append("- (2026-11-10 P9) 미탐색 = 끝난 챕터에서 한 번도 묻지 않은 하위역량(0 이어야 함). 말투 섞임 = 페르소나 어미와 다른 질문 문장·여는 문장·범위 문장(여는 턴·범위 턴/전체; 받는 문장의 '~군요/~네요'는 세지 않는다), "
             "닫는 턴 질문 = 사례를 닫고 새 사례를 여는 턴의 받기 쪽에 질문·예고·조언·가정이 남은 턴, 주어 없는 질문 = 대상 낱말이 없는 탐침 질문 — 셋 다 0 목표.")
    L.append("- (2026-11-11 P10) 입버릇 초과 = '궁금해요/궁금합니다' 챕터 1회 초과 / '이번에는 ~쪽 이야기' 세션 2회 초과 / 채움 문장('~마다 다릅니다') 턴. "
             "질문 2개+ 턴 = 한 턴에 질문 표지가 둘 이상(쉼표로 이은 의문사 나열 포함). 고정 받기 = 같은 받는 문장이 세션에서 되풀이된 수 / 리더 낱말이 없는 받기 턴 / 받을 낱말이 없는 답 뒤에 붙은 받는 문장. 요약 총평 = 챕터 종료 요약의 해석·평가 문장. "
             "슬롯 일반문 = 사례 낱말이 없거나 고른 쪽·버린 쪽이 뒤섞인 슬롯 문장. 지시문 되읊기 = 여는 문장에 틀 설명이 그대로 나온 턴. 짧은 질문 = 대상·장면 없이 15자 이하인 탐침 질문 — 전부 0 목표. 말투 섞임은 여는 문장·범위 문장·다리를 코치 어미로 본다(받는 문장만 자유).")
    L.append("- (2026-11-05 P4) 슬롯/챕터 최대 ≤1 · 평가 말투('좋습니다/좋은 방향/잘하셨/인상적' 류, 고정 문장 제외) 0 · 흉터(서술어 없음·호칭만·조사 끝) 0 · "
             "같은 고정 문장 세션 ≥3회 0 — 넷 다 P4 통과 기준.")
    if any(r["mapping_accuracy"] is not None for r in results):
        L.append("- 매핑 정확도(시뮬 정답 대비): " + ", ".join(f"{r['coach_name']} {r['mapping_accuracy']}" for r in results if r["mapping_accuracy"] is not None))
    L.append(f"- 코치 간 동일 앵커 문장 쌍 합계: **{cross['pairs']}** (0 이어야 함)")
    for d in cross["duplicates"]:
        L.append(f"  - {' · '.join(d['coaches'])}: \"{d['sentence']}\"")
    L.append("")
    for r in results:
        for key, title in (("register_issues", "말투 섞임"), ("close_side_issues", "닫는 턴 질문"), ("no_referent_issues", "주어 없는 질문")):
            for it in r.get(key) or []:
                L.append(f"- [P9 {title}] {r['coach_name']} t{it['t']} {it['instr']}: {it['sentence']}")
        for it in r.get("phrase_issues") or []:
            L.append(f"- [P10 입버릇 — {it['kind']}] {r['coach_name']} t{it['t']} {it['instr']}: {it['sentence']}")
        for key, title in (("multi_q_issues", "질문 2개+"), ("fixed_receive_issues", "고정 받기(반복)"), ("empty_receive_issues", "고정 받기(내용 없음)"),
                           ("slot_issues", "슬롯 일반문"), ("short_bare_issues", "짧은 질문"), ("summary_eval_issues", "요약 총평"),
                           ("instruction_echo_issues", "지시문 되읊기"), ("question_lost_issues", "질문 지워짐")):
            for it in r.get(key) or []:
                L.append(f"- [P10 {title}] {r['coach_name']} t{it['t']} {it['instr']}: {it['sentence']}")
        if r.get("turn_totals"):
            _tt = sorted(r["turn_totals"])
            _p50 = _tt[len(_tt) // 2] if len(_tt) % 2 else round((_tt[len(_tt) // 2 - 1] + _tt[len(_tt) // 2]) / 2, 2)
            _p95 = _tt[max(0, int(round(len(_tt) * 0.95)) - 1)]
            L.append(f"- [턴 소요] {r['coach_name']}: LLM 턴 {len(_tt)}개 · p50 {_p50}s · p95 {_p95}s · 최대 {_tt[-1]}s · 재생성 걸린 턴 {r['regen_turns']} · 재생성 2회 이상 {r['regen_over']}")
        if r.get("smalltalk"):
            L.append(f"- [P10 스몰톡] {r['coach_name']}: 처리 {r['smalltalk']} · 소요 {r['smalltalk_total_s']}s · 재생성 {r['smalltalk_regen']} · 받기 폴백(리더 절 인용) {r['receive_fallback_turns']}턴")
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
        if r.get("p11"):
            L.extend(render_p11(r["coach_name"], r["p11"]))
        if r.get("p11b"):
            L.extend(render_p11b(r["coach_name"], r["p11b"]))
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
