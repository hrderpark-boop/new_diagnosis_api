#!/usr/bin/env python
"""코치 재생(리플레이) 전문 품질 린트 — 대화 품질 지표를 자동 집계해 마크다운 표로 낸다.

입력: `.fm_work/replay_result_*.json` 구조의 파일 1개 이상.
    {"session": "...", "coach": "2", "rows": [{"t", "role", "chapter", "probe", "instr", "content", "guard"}, ...]}

사용:
    python tools/transcript_lint.py FILE [FILE ...] [--json OUT] [--dump-lexicon]

집계 항목
  1. 내부 어휘 누설 — 누설 사전은 프롬프트 템플릿에서 **자동 추출**(수동 목록 없음) + 상태 보고문 패턴
  2. ALIGN 턴 검사(하위역량 목록 전부 / 앵커 질문 1개 / 확인 질문으로 끝나지 않음)
  3. 질문 잘림(주절 없이 조건절·연결어미로 시작하는 질문)
  4. 사용자 입력 복사·반복 미감지 (a) 직전 사용자 턴 반복 (b) 코치 질문 그대로 붙여넣기
  5. 탐침 집계(사다리·일반화·'직접 하신' 과다)
  6. 코치별 어미 분포
  7. 코치 간 동일 앵커 문장 쌍 수

누설 사전 추출 방식(요약)
  - 소스: prompts/phase3a/layer1_system.py · layer2_chapters.py · layer3_state.py,
          services/instruction_decider.py(instruction 이름 상수 포함), services/persona_voice.py(persona_guide_block 텍스트).
    보조 소스: routes/diagnoses.py 의 **로그 포맷 문자열**(`%s` 류 포함 — 코치가 절대 말하지 않는 문자열, 빈도 1도 채택).
  - 문자열 리터럴(ast, f-string 조각·docstring 포함)만 읽는다. 주석은 읽지 않는다.
  - 한글 어절: 공백·문장부호로 자르고 조사를 떼어 1~6자 명사 후보로 만든다. 1자 후보는 단독 출현이 있고 빈도가 높을 때만.
  - 영문 식별어: 3자 이상 알파벳 토큰. 대문자 스네이크(COMPETENCY_ALIGN 류)는 빈도와 무관하게 채택.
  - 제외: 코치가 실제로 말하도록 설계된 어휘(competencies 의 역량·하위역량 이름·정의·앵커 질문·주제 구절,
          intro_messages·time_greeting 의 고정 문장, 페르소나 되받기 어구·다리 문장) 와 일반 기능어(폐쇄류 소목록 + 서술어 어미 휴리스틱).
  - 템플릿 안의 따옴표 예문('언제였을까요?' 류, 종결 어미로 끝나는 구간)은 코치가 말하도록 적힌 문장이므로 코치 발화 어휘로 보낸다.
  - 명사/서술어 증거: 1자 어절은 조사 결합 3회 이상, 2자 어절은 조사·복합어 증거가 서술어 어미 증거보다 많을 때만.
  - 빈도 임계: 주 소스 합산 3회 이상(또는 2개 이상 파일에 출현).
  - 탐지 시 리더가 그 시점까지 쓴 어절을 코치가 되받은 것은 누설로 세지 않는다(설계된 되받기).
"""
from __future__ import annotations

import argparse
import ast
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
from diag_project.data.competencies import (  # noqa: E402
    COMPETENCY_FRAMEWORK,
    SUBCOMPETENCY_ANCHOR_QUESTIONS,
    SUBCOMPETENCY_TOPIC_PHRASE,
)
from diag_project.services.output_guard import find_state_leak, is_question, split_sentences  # noqa: E402

# ── 코치 키 → 이름 ────────────────────────────────────────────────────────────
COACH_NAMES: dict[str, str] = {k: v["name"].split(" ")[0] for k, v in COACHES_PERSONA.items()}

# ── 사전 추출 소스 ─────────────────────────────────────────────────────────────
# (2026-10-28) 누설 사전 추출·탐지는 앱 패키지(diag_project/services/leak_lexicon.py)로 옮겼다 — 출력 가드와 같은 사전.
from diag_project.services.leak_lexicon import (  # noqa: E402
    _HANGUL_RE, _raw_tokens, build_lexicon, find_lexicon_leaks, find_state_report, guard_lexicon, lexicon_size,
)
_STRICT_LEX = guard_lexicon()

_TRUNC_START_RE = re.compile(r"^(있었다면|있으셨다면|했다면|하셨다면|이유였는지|시점이었는지|계기였는지|때문이었는지)")
_TRUNC_FIRST_TOKEN_RE = re.compile(r"(면|는지|인지|였는지|었는지|던지)[,，]?$")
_TRUNC_EXEMPT = {"그렇다면", "그러면", "그럼", "그러시면", "아니면", "괜찮으시면", "괜찮다면", "가능하다면", "가능하시면", "혹시라도", "말하자면", "예를들면"}
_REPEAT_ACK_RE = re.compile(r"((앞서|방금|조금\s*전|이전에|아까|직전에)\s*(말씀하신|하신\s*말씀|주신\s*답변|답하신|쓰신|보내신)\s*(내용|말씀|답변|것)?(과|와|이랑|하고|도)?\s*(같|동일|비슷|반복|다시)"
                            r"|같은\s*(답변|내용|말씀|글)(이|을|을\s*다시|이\s*다시|이\s*반복)|(답변|내용|말씀)(이|을)\s*(그대로|다시|반복)|반복(된|되는|하신|해서\s*주신|으로)|두\s*번\s*(같은|동일))")
_PASTE_ACK_RE = re.compile(r"(질문(이|을|만|이\s*그대로|을\s*그대로)?\s*(그대로|다시|되돌|돌아|돌려|옮겨|붙여|복사)|제\s*질문(을|이)|되돌아온|되돌아왔|질문을\s*되묻|질문이\s*반복|질문\s*그대로|그대로\s*(돌아왔|보내|옮기|붙여|돌려))")
_DIRECT_Q_RE = re.compile(r"직접\s*(하신|어떻게|뭘|무엇을|무엇이|움직이신|하셨|한\s*일|하는|해\s*보신|해보신|한\s*행동)")
# '~는지요?/~은지요?/~인지요?/~실지요?/~을지요?' 는 간접 의문(Daniel·Olivia 어미)이지 확인 질문이 아니다
_CONFIRM_TAIL_RE = re.compile(r"(죠\?|(?<![는은인실을일할])지요\?|크게\s*다르지\s*않|맞을까요\?|맞나요\?|맞습니까\?|않으신가요\?|않을까요\?|아닐까요\?)\s*$")
_ENDINGS = ("시겠습니까", "셨습니까", "였습니까", "었습니까", "습니까", "ㅂ니까", "었을까요", "았을까요", "였을까요", "을까요", "실까요", "ㄹ까요", "까요",
            "셨나요", "었나요", "았나요", "였나요", "나요", "는지요", "지요", "죠", "세요", "셨어요", "었어요", "았어요", "어요", "아요", "예요", "에요",
            "요", "니까", "는가", "ㄴ가", "가", "니", "지")
_PROBE_TYPE_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_ALIGN_LINE_RE = re.compile(r"^\s*[·•\-]\s*(.+?)\s*$")


# ══════════════════════════════════════════════════════════════════════════════
# 1. 토큰화·어절 후보
# ══════════════════════════════════════════════════════════════════════════════


# ══════════════════════════════════════════════════════════════════════════════
# 4. 보조 함수
# ══════════════════════════════════════════════════════════════════════════════
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
    return bool(_TRUNC_FIRST_TOKEN_RE.search(first))


def indicator_names(chapter: str | None) -> list[str]:
    fw = COMPETENCY_FRAMEWORK.get(chapter or "") or {}
    return [ind["name"] for ind in fw.get("indicators", {}).values()]


def _align_list_items(text: str) -> list[str]:
    items = []
    for line in (text or "").splitlines():
        if line.strip().startswith("· "):
            items.append(line.strip()[2:].strip())
    return items


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
    q_marks = (text or "").count("?") + (text or "").count("？")
    if q_marks != 1 or not is_question(last):
        reasons.append(f"앵커 질문 1개 아님(물음표 {q_marks}개, 마지막 문장 질문={is_question(last)})")
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
    if row.get("probe") == "START_CHAPTER" or instr == "CHAPTER_READY_TO_END":
        return "전환"
    if _guard(row).get("anchor"):
        return "앵커"
    return None


# ══════════════════════════════════════════════════════════════════════════════
# 5. 파일 단위 분석
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
        "ladder_turns": 0, "generalize_turns": 0, "generalize_by_chapter": {}, "direct_q_by_target": {}, "direct_excess": 0,
        "endings": {}, "anchors": [],
    }
    endings: Counter = Counter()
    gen_by_ch: Counter = Counter()
    direct_by_target: Counter = Counter()
    prev_user: str | None = None
    prev_coach: str | None = None
    user_tokens: set[str] = set()

    for i, row in enumerate(rows):
        role = row.get("role")
        content = row.get("content") or ""
        t = row.get("t")
        if role == "user":
            # 4(a) 직전 사용자 턴 반복
            a, b = re.sub(r"\s+", "", prev_user or ""), re.sub(r"\s+", "", content)
            nxt = next((r for r in rows[i + 1:] if r.get("role") == "model"), None)
            nxt_text = (nxt or {}).get("content") or ""
            # (2026-10-28) '네'·'넵' 같은 짧은 추임새의 연타는 '반복 입력'이 아니라 비실질 입력 — 앵커 재발화("그럼 여쭤볼게요")가 맞다.
            #   가드와 같은 기준(공백 제거 10자 이상)만 반복으로 센다.
            if prev_user and a and b and len(b) >= 10 and difflib.SequenceMatcher(None, a, b).ratio() >= 0.9:
                res["repeat_a_cases"] += 1
                if not _REPEAT_ACK_RE.search(nxt_text):
                    res["repeat_a_missed"] += 1
                    res["repeat_missed"].append({"t": t, "kind": "a", "user": content[:60], "coach": nxt_text[:80]})
            # 4(b) 직전 코치 질문 붙여넣기
            if prev_coach:
                nu = norm_sentence(content)
                pasted = [q for q in question_sentences(prev_coach) if len(norm_sentence(q)) >= 10 and norm_sentence(q) in nu]
                if pasted:
                    res["repeat_b_cases"] += 1
                    if not _PASTE_ACK_RE.search(nxt_text):
                        res["repeat_b_missed"] += 1
                        res["repeat_missed"].append({"t": t, "kind": "b", "user": content[:60], "coach": nxt_text[:80]})
            prev_user = content
            user_tokens.update(t.lower() for t in _raw_tokens(content))
            continue
        if role != "model":
            continue
        res["coach_turns"] += 1
        g = _guard(row)
        chapter = _chapter_of(row)
        # 1. 누설
        words = find_lexicon_leaks(content, lex, user_tokens)
        state = find_state_report(content)
        # 엄격 사전(가드와 동일: 템플릿 10회 이상 + 리더 일상어 제외) 기준 — 보고의 통과 기준은 이 열
        words_strict = find_lexicon_leaks(content, _STRICT_LEX, user_tokens)
        if words or state:
            res["leaks"].append({"t": t, "words": words, "state": state, "strict": words_strict})
            res["leak_total"] += len(words) + len(state)
            res["leak_strict_total"] += len(words_strict) + len(state)
        # 2. ALIGN
        if row.get("instr") == "COMPETENCY_ALIGN":
            ok, reasons = check_align_turn(content, chapter)
            res["align_total"] += 1
            res["align_pass"] += int(ok)
            res["align"].append({"t": t, "pass": ok, "reasons": reasons})
        # 3. 잘림
        _sents_all = split_sentences(content)
        for _qi, q in enumerate(_sents_all):
            if not is_question(q) or not is_truncated_question(q):
                continue
            # 바로 앞 문장이 질문이면("…없었습니까? 있었다면 …?") 한 쌍의 복합 질문 — 잘림이 아니다
            if _qi > 0 and is_question(_sents_all[_qi - 1]):
                continue
            res["truncated"].append({"t": t, "sentence": q})
            res["truncated_total"] += 1
        # 5. 탐침
        if g.get("ladder_probe") or g.get("ladder"):
            res["ladder_turns"] += 1
        if g.get("generalize_probe") or g.get("generalize"):
            res["generalize_turns"] += 1
            gen_by_ch[chapter or "-"] += 1
        for q in question_sentences(content):
            if _DIRECT_Q_RE.search(q):
                direct_by_target[_probe_target(row)] += 1
        # 6. 어미
        lq = last_question(content)
        if lq:
            endings[ending_of(lq)] += 1
        # 7. 앵커
        kind = _is_anchor_turn(row)
        if kind and lq:
            res["anchors"].append({"t": t, "kind": kind, "sentence": lq, "norm": norm_sentence(lq)})
        prev_coach = content

    res["generalize_by_chapter"] = dict(gen_by_ch)
    res["direct_q_by_target"] = dict(direct_by_target)
    res["direct_excess"] = sum(n - 1 for n in direct_by_target.values() if n > 1)
    res["endings"] = dict(endings.most_common())
    return res


def cross_anchor_pairs(results: list[dict]) -> dict:
    """서로 다른 코치 파일 간 완전히 같은 앵커 문장 쌍. 같은 코치의 여러 벌끼리는 비교하지 않는다."""
    by_norm: dict[str, dict[str, str]] = defaultdict(dict)   # norm → {coach_key: 원문}
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
        n_pairs = len(list(combinations(keys, 2)))
        pairs += n_pairs
        for k in keys:
            per_coach[k] += len(keys) - 1
        dup.append({"sentence": next(iter(coaches.values())), "coaches": [COACH_NAMES.get(k, k) for k in keys]})
    return {"pairs": pairs, "per_coach": dict(per_coach), "duplicates": dup}


# ══════════════════════════════════════════════════════════════════════════════
# 6. 마크다운 출력
# ══════════════════════════════════════════════════════════════════════════════
def render_markdown(results: list[dict], cross: dict, lex: dict) -> str:
    L: list[str] = []
    L.append("## 코치 재생 전문 린트 요약")
    L.append("")
    L.append("| 코치 | 파일 | 누설(전체/엄격) | ALIGN pass/total | 잘림 | 미감지 a/b | 사다리 | 일반화 | 직접하신 초과 | 동일앵커 |")
    L.append("|---|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for r in results:
        same = cross["per_coach"].get(r["coach"], 0)
        L.append(f"| {r['coach_name']}({r['coach']}) | {os.path.basename(r['file'])} | {r['leak_total']}/{r['leak_strict_total']} | "
                 f"{r['align_pass']}/{r['align_total']} | {r['truncated_total']} | "
                 f"{r['repeat_a_missed']}/{r['repeat_a_cases']} · {r['repeat_b_missed']}/{r['repeat_b_cases']} | "
                 f"{r['ladder_turns']} | {r['generalize_turns']} | {r['direct_excess']} | {same} |")
    L.append("")
    L.append("- 미감지 a/b: (직전 사용자 턴 반복 미감지/발생) · (코치 질문 붙여넣기 미감지/발생)")
    L.append(f"- 코치 간 동일 앵커 문장 쌍 합계: **{cross['pairs']}** (0 이어야 함)")
    if cross["duplicates"]:
        for d in cross["duplicates"]:
            L.append(f"  - {' · '.join(d['coaches'])}: \"{d['sentence']}\"")
    L.append("")
    for r in results:
        L.append(f"### {r['coach_name']}({r['coach']}) — {os.path.basename(r['file'])} (코치 턴 {r['coach_turns']})")
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
        L.append("")
        gen = ", ".join(f"{k} {v}" for k, v in r["generalize_by_chapter"].items()) or "없음"
        direct = ", ".join(f"{k} {v}" for k, v in r["direct_q_by_target"].items()) or "없음"
        L.append(f"**탐침** 사다리 {r['ladder_turns']}턴 · 일반화 {r['generalize_turns']}턴({gen}) · '직접 하신' 질문: {direct} → 초과 {r['direct_excess']}")
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
# 7. CLI
# ══════════════════════════════════════════════════════════════════════════════
def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="코치 재생 전문 품질 린트")
    ap.add_argument("files", nargs="*", help="replay_result_*.json")
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
