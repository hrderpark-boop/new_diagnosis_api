#!/usr/bin/env python3
"""대화 쪽 회귀 점검 — 코치 × 요약형 팀장 × 조직관리 + 사람관리 시뮬을 한 명령으로 돌리고 조건을 판정한다.

(2026-11-15 P13 묶음을 닫으며) 대화 쪽(프롬프트·후처리·사례 진행)을 고친 커밋은 push 전에 이 점검을 최소 2코치로 통과시킨다.

사용(워크트리 루트에서):
    FM_PREWARM=0 .venv/bin/python tools/regression_check.py TAG                  # 6코치(기본)
    FM_PREWARM=0 .venv/bin/python tools/regression_check.py TAG --pair           # 2코치(push 전 최소) — 해요체 Ella + 합쇼체 Daniel
    FM_PREWARM=0 .venv/bin/python tools/regression_check.py TAG --coaches 2,6    # 코치를 직접 고를 때(해요체·합쇼체를 각각 1명 이상 넣는다)
    .venv/bin/python tools/regression_check.py TAG --coaches 1,4 --no-run        # 시뮬은 돌리지 않고 있는 결과만 다시 판정(LLM 호출 없음)

  TAG       결과 파일 이름에 들어가는 표지(예: p14a). 같은 TAG·코치의 결과가 있으면 덮어쓴다.
  --coaches 1 Ella · 2 Jessica · 3 Olivia · 4 Daniel · 5 Michael · 6 Lucas(해요체 1·3·5, 합쇼체 2·4, Lucas 는 섞어 쓴다)
  --pair    --coaches 1,4 와 같다(2026-11-18 P14d: 합쇼체 코치가 빠진 2코치 점검이 받는 말 탈락을 놓쳤다 — 두 말투를 모두 넣는다)
  --out     결과 폴더(기본: 환경 변수 SIM_OUT, 없으면 워크트리 옆의 sim 폴더)
  --port    시뮬 서버 포트(기본 8180)

비용: 실제 LLM(Haiku)을 부른다 — 코치 한 명에 약 $0.055(코치 쪽 약 $0.045~0.055 + 시뮬 리더 쪽 약 $0.008), 6코치에 약 $0.33, 3~4분씩.
      코치는 한 명씩 차례로 돌린다(동시에 돌리면 지연 수치가 서로 섞인다).

조건(코치마다, 하나라도 넘으면 종료 코드 1):
    p50 ≤ 4.6초 · p95 ≤ 8.0초(점검표 값 — 올림 순위) · 재생성 걸린 턴 ≤ 8 · 형식미해결 0 · 깨진 문장 0 · 첫 꼬리 질문 대체 문장 ≤ 1
    (P15 — 2026-11-18, '받는 말이 붙었는가'가 아니라 '리더 말을 되짚는가'를 센다)
      (A) 맥락 없는 본론 턴 ≤ 10% — 꼬리 질문 턴: 평서문도 없고 질문에 이 사례의 리더 답에서 온 명사 어절이 하나도 없는 턴('그때'·'그 결정'만으로 가리킴)
                                    전환 턴: 받는 말도 넘김말도 없는 턴
      a) 되짚는 턴 ≤ 30% — 본론 턴 중 되짚는 평서문(받는 말·슬롯 문장)이 있거나 질문에서 리더 답을 옮긴 부분이 6어절을 넘는 턴
         (P15 판정: 앞 절 기준을 철회하고 옮긴 부분의 길이로 바꿨다 — 옮긴 부분 = 리더 답에도 있는 어절이 끊기지 않고 이어진 가장 긴 구간)
      (A)에서 '다시 한다면·배운 것'을 묻는 질문은 리더 낱말이 없어도 맥락 없는 턴으로 세지 않는다
      b) 사례 안(꼬리 질문 턴) 받는 말 0 · c) 사례당 청하는 꼴 2회 이상인 사례 0 · d) '리더님께서'로 시작하는 문장이 있는 턴 0
      전환 턴에 받는 말 또는 넘김말 100% · 영역당 되짚기형 전환 ≤ 2 · 8어절 미만 꼬리 질문 ≤ 1 · 구체화 질문이 2회 이상인 사례 0
    (P15b 판정) p50 은 이번 묶음에 한해 4.6초 이하 · 첫 꼬리 대체 문장 ≤ 1.
      받는 말 평균 어절·12어절 초과·앞 절 겹침·끝맺음 최다와 꼬리 질문 청하는 꼴 %는 참고로만 표시한다(판정에 넣지 않는다)
    삭제(P15): (B) 전환 턴에 받는 말 ≥ 80% · (C) 받는 말 있는 본론 턴 ≤ 75%·연속 4턴 · 8어절 미만 질문 중 받는 말 없이 나간 것 ≤ 1
    '구체화 질문이 구체화를 물었는가'도 사람이 읽어 판정한다.
  '첫 꼬리 질문이 리더 본인의 말·조치를 물었는가'(사례의 78% 이상)는 사람이 읽어 판정한다 — 이 스크립트는 문장만 뽑아 준다.

산출물(결과 폴더):
    sim_result_TAG_<코치>.json · sim_usage_TAG_*.jsonl · sim_server_TAG_<코치>.log      시뮬 원자료
    regression_TAG_table.md       코치별 점검표(tools/regression_table.py --detail)
    regression_TAG_lint.md        전문 린트(tools/transcript_lint.py)
    regression_TAG_transcript_<코치 이름>.md   전문
    regression_TAG_summary.md     조건 판정표 + 첫 꼬리 질문 목록
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "tools"))

COACH_NAMES = {"1": "ella", "2": "jessica", "3": "olivia", "4": "daniel", "5": "michael", "6": "lucas"}
TOPICS = "조직관리,사람관리"
PROFILE = "tools/sim_profiles/summary_team_lead.json"
# (조건 이름, 결과 키, 상한) — 값이 상한 이하면 통과
# (조건 이름, 결과 키, 하한, 상한) — 하한 ≤ 값 ≤ 상한이면 통과(하한 None = 하한 없음)
LIMITS: tuple[tuple[str, str, float | None, float], ...] = (
    # (2026-11-18 P15b 판정) p50 상한은 이번 묶음에 한해 4.6초 — 슬롯 판정 뒤에 호출이 순서대로 붙는 구조라 4초대 중반이 나온다(설계 문서 §27).
    ("p50 ≤ 4.6초", "p50", None, 4.6), ("p95 ≤ 8.0초", "p95", None, 8.0), ("재생성 턴 ≤ 8", "regen_turns", None, 8), ("형식미해결 0", "format_miss", None, 0),
    ("깨진 문장 0", "broken_total", None, 0), ("첫 꼬리 대체 문장 ≤ 1", "fp_fallback", None, 1),
    # (2026-11-18 P15) (B)·(C)·'짧은 질문 중 받는 말 없는 것'은 삭제 — 받는 말이 붙었는지를 세던 조건이 메아리를 통과시켰다.
    #   (A)는 10%로 낮추고 '질문에 리더 낱말이 있는가'로 다시 정의했다. a·b·d 와 전환 턴·짧은 꼬리 질문 조건을 더했다.
    # (P15b 판정) c) '청하는 꼴 30% 이하'는 '사례당 청하는 꼴 2회 이상인 사례 0'으로 교체(사례가 짧은 세션에서는 사례당 한 번을 지켜도 30%를 넘는다).
    #   8어절 미만 꼬리 질문은 1개까지. 받는 말 평균 어절·끝맺음 최다 등은 표본이 작아(세션당 2~4개) 참고로만 표시한다.
    ("(A) 맥락 없는 본론 턴 ≤ 10%", "ctx_bare_pct", None, 10),
    ("a) 되짚는 턴 ≤ 30%", "echo_pct", None, 30), ("b) 꼬리 질문 턴 받는 말 0", "tail_recv_n", None, 0),
    ("c) 사례당 청하는 꼴 2회 이상인 사례 0", "req_case_multi", None, 0), ("d) '리더님께서'로 시작 0", "lead_addr_n", None, 0),
    ("전환 턴에 받는 말 또는 넘김말 100%", "trans_cover_pct", 100, 100), ("영역당 되짚기형 전환 ≤ 2", "echo_trans_max", None, 2),
    ("8어절 미만 꼬리 질문 ≤ 1", "tail_short_n", None, 1),
    ("구체화 질문 2회 이상인 사례 0", "specify_multi", None, 0),
)
# 참고로만 표시(판정에 넣지 않음) — (이름, 결과 키)
INFO_ROWS: tuple[tuple[str, str], ...] = (
    ("참고: 꼬리 질문 청하는 꼴 %", "req_tail_pct"), ("참고: 받는 말 평균 어절", "recv_avg_eojeol"), ("참고: 받는 말 12어절 초과", "recv_over12"),
    ("참고: 받는 말·질문 앞 절 겹침", "recv_echo_n"), ("참고: 받는 말 끝맺음 최다 %", "recv_top_end_pct"),
)
NONE_OK: frozenset = frozenset()
MAIN_INSTR = ("EPISODE_PROBE", "SWEEP_FOLLOWUP", "EPISODE_OPEN", "SWEEP_ANCHOR")


ECHO_RATIO = 0.6


def receive_stats(rows: list[dict]) -> dict:
    """본론 턴(탐침·훑는 질문·여는 턴)의 받는 말 — 유무, 끝맺음 분포, 어절 수, 같은 턴 질문의 앞 절과 겹친 턴, 받는 말 없이 나간 짧은 질문.
    서버가 남긴 recv_out(끝맺음 갈래 | other | fixed | slot | None)을 읽는다. 슬롯 문장(관찰·응원) 턴은 받는 말 자리가 없으므로 분모에서 뺀다."""
    from collections import Counter
    import regression_table as rt
    from diag_project.services.output_guard import _content_chunks, is_question
    from diag_project.services.receive_render import receivable
    from diag_project.services.turn_checks import question_front_clause, question_overlap
    by_instr: dict[str, list[int]] = {}
    bare: list[str] = []          # (A) 받는 말도 없고 질문 앞 절이 리더 직전 답의 내용도 담지 않은 턴(질문 문장)
    main_n = 0
    trans: list[tuple[bool, str]] = []      # (B) 전환 턴 (받는 말 있음, 원문) — 리더 직전 답이 받을 내용 없는 답이면 뺀다
    trans_fixed: list[str] = []             # (P14f-2) 그 가운데 고정 받기가 붙은 턴(원문)
    streak = 0
    streak4 = 0
    ends: Counter = Counter()
    rules: Counter = Counter()
    lens: list[int] = []
    echo: list[str] = []
    short_bare: list[str] = []
    for i, r in enumerate(rows):
        if r.get("role") != "model" or r.get("instr") not in MAIN_INSTR:
            continue
        g = r.get("guard") or {}
        out = g.get("recv_out")
        if g.get("recv_rule"):
            rules[str(g.get("recv_rule"))] += 1
        prev_ans = rows[i - 1].get("content") or "" if i > 0 and rows[i - 1].get("role") == "user" else ""
        can_recv = receivable(prev_ans)
        sents = [x.strip() for x in rt.sentences(r.get("content") or "") if x.strip()]
        qs = [x for x in sents if is_question(x)]
        has = bool(out) and out != "slot"
        streak = streak + 1 if has else 0
        if streak == 4:
            streak4 += 1
        if r["instr"] in ("EPISODE_OPEN", "SWEEP_ANCHOR") and can_recv:
            trans.append((has, (r.get("content") or "").strip()))
            if out == "fixed":
                trans_fixed.append((r.get("content") or "").strip())
        if can_recv:                       # (A) 받을 내용이 없는 답 뒤의 턴은 따지지 않는다
            main_n += 1
            front = question_front_clause(qs[0]) if qs else ""
            carries = bool(front) and len(question_overlap(front, prev_ans)) >= 2
            if not has and out != "slot" and not carries and qs:
                bare.append(qs[0])
        if out == "slot":
            continue
        a = by_instr.setdefault(r["instr"], [0, 0])
        a[1] += 1
        if out == "fixed":
            a[0] += 1
        elif out:
            a[0] += 1
            ends[out] += 1
            recv = next((x for x in sents if not is_question(x)), "")
            lens.append(len(recv.split()))
            front = question_front_clause(qs[0]) if qs else ""
            fw = {c[:2] for c in _content_chunks(front) if len(c) >= 2}
            rw = {c[:2] for c in _content_chunks(recv) if len(c) >= 2}
            if len(fw) >= 2 and len(fw & rw) / len(fw) >= ECHO_RATIO:
                echo.append(f"{recv} ↔ {front}")
        elif qs and r["instr"] in ("EPISODE_PROBE", "SWEEP_FOLLOWUP") and len(qs[-1].split()) < SHORT_Q_EOJEOL:
            short_bare.append(qs[-1])
    have = sum(v[0] for v in by_instr.values()); total = sum(v[1] for v in by_instr.values())
    top = ends.most_common(1)[0][1] if ends else 0
    n_ends = sum(ends.values())
    return {"bare_pct": round(100 * len(bare) / main_n, 1) if main_n else None, "bare_list": bare, "main_n": main_n,
            "trans_recv_pct": round(100 * sum(1 for h, _t in trans if h) / len(trans), 1) if trans else None, "trans_list": trans, "trans_fixed": trans_fixed, "recv_streak4": streak4,
            "recv_have_pct": round(100 * have / total, 1) if total else None, "recv_top_end_pct": round(100 * top / n_ends, 1) if n_ends else None,
            "recv_avg_eojeol": round(sum(lens) / len(lens), 1) if lens else None, "recv_over12": sum(1 for n in lens if n > 12),
            "recv_echo_n": len(echo), "recv_echo": echo, "short_bare": len(short_bare), "short_bare_list": short_bare,
            "recv_by_instr": {k: f"{v[0]}/{v[1]}" for k, v in by_instr.items()}, "recv_ends": dict(ends.most_common()), "recv_rules": dict(rules.most_common())}


# ── (2026-11-18 P15) 메아리 집계 — '받는 말이 붙었는가'가 아니라 '리더 말을 되짚는가'를 센다 ──────────────────────────
#   11/18 운영 Lucas 사람관리: 본론 21턴 중 12턴이 되짚는 문장으로 시작했고 6턴은 질문 앞머리 절에서 되짚었다. p14f 조건은 받는 말이 붙었는지만 세어 통과시켰다.
TAIL_INSTR = ("EPISODE_PROBE", "SWEEP_FOLLOWUP")          # 사례 안 꼬리 질문 턴
OPEN_INSTR = ("EPISODE_OPEN", "SWEEP_ANCHOR")             # 사례를 닫고 다음을 여는 전환 턴
TAIL_MIN_EOJEOL = 8
def overlap_keys(text: str | None) -> set[str]:
    from diag_project.services.turn_checks import content_keys
    return content_keys(text)


def question_first_clause(question: str | None) -> str:
    from diag_project.services.turn_checks import question_first_clause as _qfc
    return _qfc(question)


def echo_stats(rows: list[dict]) -> dict:
    """(P15) a 되짚는 턴 비율 · b 사례 안(꼬리 질문 턴) 받는 말 수 · c 꼬리 질문 끝맺음 중 청하는 꼴 비율 · d '리더님께서'로 시작하는 턴 수 ·
    e 받는 말 끝맺음 종류 수와 최다 비율 · 꼬리 질문 어절 수 분포와 8어절 미만 수 · 전환 턴의 받는 말/넘김말 · 영역당 되짚기형 전환 수."""
    from collections import Counter
    import statistics
    import regression_table as rt
    from diag_project.services.intro_messages import all_fixed_sentences
    from diag_project.services.output_guard import is_question
    from diag_project.services.receive_render import receivable
    from diag_project.services.turn_checks import BORROW_MAX_EOJEOL, REQUEST_END_RE, borrowed_run, leader_nouns, receive_ending_key
    fixed = {re.sub(r"\s+", "", x) for x in all_fixed_sentences()}
    case_ans: list[str] = []          # 이 사례에서 리더가 한 말(사례를 여는 코치 턴에서 비운다)
    ctx_bare: list[str] = []          # (A) 맥락 없는 본론 턴(원문)
    main_n = tail_n = 0
    echo_stmt: list[str] = []; echo_slot: list[str] = []; echo_front: list[str] = []
    tail_recv: list[str] = []; tail_slot = 0
    req_tail = 0; req_all = 0; q_all = 0
    lead_addr: list[str] = []; lead_any = 0
    ends: Counter = Counter()
    tail_len: list[int] = []; tail_short: list[str] = []
    trans: list[tuple[str, str, str]] = []            # (갈래: 받는 말 | 넘김말 | 없음 | 받을 내용 없음, 영역, 원문)
    echo_trans_by_ch: Counter = Counter()
    tail_rows: list[dict] = []
    case_req = 0                      # 이 사례의 꼬리 질문 가운데 청하는 꼴로 끝난 수
    req_cases: list[int] = []         # 사례별 청하는 꼴 수(전환 턴에서 닫는다)
    for i, r in enumerate(rows):
        if r.get("role") != "model" or r.get("instr") not in MAIN_INSTR:
            continue
        g = r.get("guard") or {}
        text = (r.get("content") or "").strip()
        prev_ans = rows[i - 1].get("content") or "" if i > 0 and rows[i - 1].get("role") == "user" else ""
        if prev_ans:
            case_ans.append(prev_ans)
        sents = [x.strip() for x in rt.sentences(text) if x.strip()]
        qs = [x for x in sents if is_question(x)]
        stmts = [x for x in sents if not is_question(x)]
        retell = [x for x in stmts if re.sub(r"\s+", "", x) not in fixed]      # 고정 문장(넘김말·고정 받기)은 되짚는 문장이 아니다
        is_tail = r["instr"] in TAIL_INSTR
        main_n += 1
        nouns = leader_nouns(qs[-1], " ".join(case_ans)) if (qs and is_tail) else []
        borrow = borrowed_run(qs[-1], " ".join(case_ans)) if (qs and is_tail) else 0      # 질문에서 리더 답을 옮긴 부분의 어절 수
        reflect = g.get("ask_slot") == "reflection"
        if (is_tail and not stmts and not nouns and not reflect) or (not is_tail and not stmts):
            ctx_bare.append(text)
        if retell:
            (echo_slot if g.get("slot") else echo_stmt).append(text)
            if not g.get("slot"):
                ends[receive_ending_key(retell[0]) or "other"] += 1
        elif borrow > BORROW_MAX_EOJEOL:
            echo_front.append(text)
        if any(x.startswith("리더님께서") for x in sents):
            lead_addr.append(text)
        if any(x.startswith("리더님") for x in sents):
            lead_any += 1
        if qs:
            q_all += 1
            req_all += 1 if REQUEST_END_RE.search(qs[-1]) else 0
        if is_tail:
            tail_n += 1
            if retell and not g.get("slot"):
                tail_recv.append(text)
            elif retell:
                tail_slot += 1
            if qs:
                n = len(qs[-1].split())
                tail_len.append(n)
                req_tail += 1 if REQUEST_END_RE.search(qs[-1]) else 0
                case_req += 1 if REQUEST_END_RE.search(qs[-1]) else 0
                if n < TAIL_MIN_EOJEOL:
                    tail_short.append(qs[-1])
                tail_rows.append({"t": r.get("t"), "chapter": r.get("chapter"), "q": qs[-1], "nouns": nouns, "borrow": borrow, "first": bool(g.get("first_probe")),
                                  "pick": g.get("first_probe_pick"), "fallback": g.get("first_probe") == "fallback", "fp_retry": g.get("first_probe") == "llm_retry",
                                  "slot": bool(g.get("slot")),
                                  "specify": bool(g.get("specify")), "regen": g.get("tail_regen"), "direct": g.get("direct_fix")})
        else:
            kind = "받는 말" if retell else ("넘김말" if stmts else ("받을 내용 없음" if not receivable(prev_ans) else "없음"))
            trans.append((kind, str(r.get("chapter")), text))
            if retell:
                echo_trans_by_ch[str(r.get("chapter"))] += 1
            case_ans = []                 # 다음 사례가 열린다
            req_cases.append(case_req)
            case_req = 0
    req_cases.append(case_req)
    echo_n = len(echo_stmt) + len(echo_slot) + len(echo_front)
    n_ends = sum(ends.values())
    need = [t for t in trans if t[0] != "받을 내용 없음"]
    return {"ctx_bare_pct": round(100 * len(ctx_bare) / main_n, 1) if main_n else None, "ctx_bare_list": ctx_bare,
            "echo_pct": round(100 * echo_n / main_n, 1) if main_n else None, "echo_n": echo_n, "echo_main_n": main_n,
            "echo_stmt_n": len(echo_stmt), "echo_slot_n": len(echo_slot), "echo_front_n": len(echo_front), "echo_front_list": echo_front,
            "tail_recv_n": len(tail_recv), "tail_recv_list": tail_recv, "tail_slot_n": tail_slot, "tail_n": tail_n,
            "req_tail_pct": round(100 * req_tail / len(tail_len), 1) if tail_len else None, "req_tail_n": req_tail,
            "req_all_pct": round(100 * req_all / q_all, 1) if q_all else None,
            "req_case_multi": sum(1 for n in req_cases if n >= 2), "req_case_max": max(req_cases) if req_cases else 0,
            "lead_addr_n": len(lead_addr), "lead_addr_list": lead_addr, "lead_any_n": lead_any,
            "recv_end_kinds": len(ends), "recv_end_top_pct": round(100 * ends.most_common(1)[0][1] / n_ends, 1) if n_ends else None, "recv_end_dist": dict(ends.most_common()),
            "tail_len_min": min(tail_len) if tail_len else None, "tail_len_med": statistics.median(tail_len) if tail_len else None,
            "tail_len_max": max(tail_len) if tail_len else None, "tail_short_n": len(tail_short), "tail_short_list": tail_short,
            "trans2": trans, "trans_cover_pct": round(100 * sum(1 for t in need if t[0] != "없음") / len(need), 1) if need else None,
            "echo_trans_max": max(echo_trans_by_ch.values()) if echo_trans_by_ch else 0, "echo_trans_by_ch": dict(echo_trans_by_ch), "tail_rows": tail_rows}


def call_stats(rows: list[dict]) -> dict:
    """(2026-11-18 P14d-4) 받는 말 전용 호출의 통과/탈락(사유별)과, 전용 호출(받는 말·첫 꼬리·구체화)에서 탈락한 문장."""
    from collections import Counter
    modes: Counter = Counter()
    drops: dict[str, list[str]] = {}
    for r in rows:
        g = (r.get("guard") or {}) if r.get("role") == "model" else {}
        m = g.get("pre_recv_mode") or g.get("pre_recv")
        if m:
            modes["통과" if str(m).startswith("llm") or m == "used" else str(m)] += 1
        for kind, why, text in (g.get("call_drops") or []):
            drops.setdefault(f"{kind}·{why}", []).append(str(text))
    return {"recv_calls": dict(modes.most_common()), "call_drops": drops}


def first_probe_pick_stats(rows: list[dict]) -> dict:
    """(P15 판정 2) 첫 꼬리 전용 호출의 후보 통과 내역 — 1번 통과 · 2번 통과 · 둘 다 탈락(대체 문장). 본 호출 꼬리 질문의 다시 쓰기 수도 함께."""
    from collections import Counter
    pick: Counter = Counter()
    regen: Counter = Counter()
    for r in rows:
        g = (r.get("guard") or {}) if r.get("role") == "model" else {}
        if g.get("first_probe"):
            if g.get("first_probe") == "fallback":
                pick["대체 문장"] += 1
            elif g.get("first_probe") == "llm_retry":
                pick["다시 써서 통과"] += 1
            else:
                pick[f"{g.get('first_probe_pick')}번 통과" if g.get("first_probe_pick") else str(g.get("first_probe"))] += 1
        for w in (g.get("regen_why") or []):
            regen[str(w)] += 1
    return {"fp_pick": dict(sorted(pick.items())), "regen_why": dict(regen.most_common()), "regen_total": sum(regen.values())}


def specify_stats(data: dict) -> dict:
    """구체화 질문 — 턴 기록(guard.specify)과 원장(사례의 specificity_probe)."""
    from collections import Counter
    per: Counter = Counter()
    for r in data.get("rows") or []:
        g = (r.get("guard") or {}) if r.get("role") == "model" else {}
        if g.get("specify"):
            per[(r.get("chapter"), g.get("ep_kind"), g.get("episode"))] += 1
    return {"specify_n": sum(per.values()), "specify_multi": sum(1 for v in per.values() if v >= 2)}
SHORT_Q_EOJEOL = 8
POLITE_COACHES = frozenset({"1", "3", "5"})      # 해요체
FORMAL_COACHES = frozenset({"2", "4"})           # 합쇼체


def judge(metrics: dict) -> list[tuple[str, object, bool]]:
    """조건별 (이름, 값, 통과 여부). 값이 없으면(None) 통과로 보지 않는다."""
    out = []
    for name, key, lo, hi in LIMITS:
        v = metrics.get(key)
        out.append((name, v, (v is None and key in NONE_OK) or (v is not None and float(v) <= float(hi) and (lo is None or float(v) >= float(lo)))))
    return out


def short_questions(rows: list[dict]) -> list[str]:
    """꼬리 질문 턴의 마지막 질문 문장 가운데 8어절 미만인 것."""
    import regression_table as rt
    from diag_project.services.output_guard import is_question
    out = []
    for r in rows:
        if r.get("role") != "model" or r.get("instr") not in ("EPISODE_PROBE", "SWEEP_FOLLOWUP"):
            continue
        qs = [s for s in rt.sentences(r.get("content") or "") if is_question(s)]
        if qs and len(qs[-1].split()) < SHORT_Q_EOJEOL:
            out.append(qs[-1].strip())
    return out


def first_probes(rows: list[dict]) -> list[tuple[str, str, str]]:
    """(각도, 기록, 문장) — 사람이 읽어 '리더 본인의 말·조치를 물었는가'를 판정할 목록."""
    out = []
    for r in rows:
        g = (r.get("guard") or {}) if r.get("role") == "model" else {}
        if g.get("first_probe"):
            out.append((str(g.get("first_probe_angle") or "-"), str(g.get("first_probe")), (r.get("content") or "").strip()))
    return out


def collect(path: Path) -> dict:
    import regression_table as rt
    data = json.loads(path.read_text(encoding="utf-8"))
    res = rt.analyze(data, None)
    rows = data.get("rows") or []
    sq = short_questions(rows)
    return {"p50": res.get("p50"), "p95": res.get("p95"), "max": res.get("max"), "regen_turns": res.get("regen_turns"), "format_miss": res.get("format_miss"),
            "broken_total": res.get("broken_total"), "fp_fallback": int((res.get("fp_mode") or {}).get("fallback", 0)), "fp_mode": res.get("fp_mode") or {},
            **receive_stats(rows), **specify_stats(data), **call_stats(rows), **echo_stats(rows), **first_probe_pick_stats(rows),
            "short_q": len(sq), "short_list": sq, "first_probes": first_probes(rows), "status": data.get("status"), "cost_usd": float(data.get("cost_usd") or 0.0),
            "turns": data.get("turns")}


def run_sim(tag: str, coach: str, out_dir: Path, port: int) -> tuple[int, float]:
    """시뮬 한 명. (종료 코드, 시뮬 리더 쪽 비용)."""
    env = dict(os.environ, SIM_OUT=str(out_dir), RP_PORT_BASE=str(port), FM_PREWARM="0")
    log = out_dir / f"run_{tag}_{coach}.log"
    with open(log, "w", encoding="utf-8") as f:
        rc = subprocess.run([sys.executable, "tools/sim_leader.py", tag, "--coaches", coach, "--chapters", "2", "--provider", "claude",
                             "--topics", TOPICS, "--profile", PROFILE], cwd=str(ROOT), env=env, stdout=f, stderr=subprocess.STDOUT).returncode
    m = re.search(r"시뮬 리더 호출 비용[^$]*\$([\d.]+)", log.read_text(encoding="utf-8", errors="replace"))
    return rc, float(m.group(1)) if m else 0.0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="대화 쪽 회귀 점검(코치 × 요약형 팀장 × 조직관리 + 사람관리)")
    ap.add_argument("tag")
    ap.add_argument("--coaches", default="1,2,3,4,5,6")
    ap.add_argument("--pair", action="store_true", help="push 전 최소 조합: 해요체 Ella(1) + 합쇼체 Daniel(4)")
    ap.add_argument("--out", default=os.environ.get("SIM_OUT") or str(ROOT.parent / "sim"))
    ap.add_argument("--port", type=int, default=8180)
    ap.add_argument("--no-run", action="store_true", help="시뮬을 돌리지 않고 있는 결과만 판정한다(LLM 호출 없음)")
    args = ap.parse_args(argv)
    coaches = ["1", "4"] if args.pair else [c for c in args.coaches.split(",") if c in COACH_NAMES]
    if not (set(coaches) & POLITE_COACHES and set(coaches) & FORMAL_COACHES):
        print("주의: 해요체 코치(1·3·5)와 합쇼체 코치(2·4)가 각각 1명 이상 들어가야 한다 — 지금 조합은 한쪽 말투가 빠졌다.", flush=True)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    leader_cost = 0.0
    if not args.no_run:
        for c in coaches:
            print(f"[{args.tag}] 코치 {c}({COACH_NAMES[c]}) 시뮬 시작 …", flush=True)
            rc, lc = run_sim(args.tag, c, out_dir, args.port)
            leader_cost += lc
            if rc != 0:
                print(f"  시뮬 종료 코드 {rc} — {out_dir / f'run_{args.tag}_{c}.log'} 를 본다", flush=True)
    files = [out_dir / f"sim_result_{args.tag}_{c}.json" for c in coaches]
    missing = [str(p) for p in files if not p.exists()]
    if missing:
        print("결과 파일이 없습니다: " + ", ".join(missing))
        return 2
    py = sys.executable
    fs = [str(p) for p in files]
    (out_dir / f"regression_{args.tag}_table.md").write_text(
        subprocess.run([py, "tools/regression_table.py", *fs, "--detail"], cwd=str(ROOT), capture_output=True, text=True).stdout, encoding="utf-8")
    (out_dir / f"regression_{args.tag}_lint.md").write_text(
        subprocess.run([py, "tools/transcript_lint.py", *fs], cwd=str(ROOT), capture_output=True, text=True).stdout, encoding="utf-8")
    for c, p in zip(coaches, fs):
        (out_dir / f"regression_{args.tag}_transcript_{COACH_NAMES[c]}.md").write_text(
            subprocess.run([py, "tools/sim_leader.py", "--dump", p], cwd=str(ROOT), capture_output=True, text=True).stdout, encoding="utf-8")
    L = [f"# 회귀 점검 {args.tag} — 코치 × 요약형 팀장 × {TOPICS}", ""]
    ms = {c: collect(p) for c, p in zip(coaches, files)}
    L.append("| 조건 | " + " | ".join(COACH_NAMES[c].capitalize() for c in coaches) + " |")
    L.append("|---|" + "---|" * len(coaches))
    all_ok = True
    verdicts = {c: judge(ms[c]) for c in coaches}
    for i, (name, _key, _lo, _hi) in enumerate(LIMITS):
        cells = []
        for c in coaches:
            _n, v, ok = verdicts[c][i]
            all_ok = all_ok and ok
            cells.append(f"{v}" if ok else f"**{v} 미달**")
        L.append(f"| {name} | " + " | ".join(cells) + " |")
    for name, key in INFO_ROWS:
        L.append(f"| {name} | " + " | ".join(str(ms[c].get(key)) for c in coaches) + " |")
    L.append("| 세션 상태 | " + " | ".join(str(ms[c]["status"]) for c in coaches) + " |")
    all_ok = all_ok and all(str(ms[c]["status"]) == "completed" for c in coaches)
    L.append("| 받는 말(턴 종류별 있음/전체) | " + " | ".join(" · ".join(f"{k} {v}" for k, v in ms[c]["recv_by_instr"].items()) or "-" for c in coaches) + " |")
    L.append("| 받는 말 끝맺음 분포 | " + " | ".join(" · ".join(f"{k} {v}" for k, v in ms[c]["recv_ends"].items()) or "-" for c in coaches) + " |")
    L.append("| 되짚는 턴 구성(받는 말 문장 / 슬롯 문장 / 옮긴 부분 6어절 초과) | " + " | ".join(f"{ms[c]['echo_stmt_n']} / {ms[c]['echo_slot_n']} / {ms[c]['echo_front_n']}" for c in coaches) + " |")
    L.append("| 첫 꼬리 후보 통과 내역 | " + " | ".join(" · ".join(f"{k} {v}" for k, v in ms[c]["fp_pick"].items()) or "-" for c in coaches) + " |")
    L.append("| 다시 쓰기(사유별) | " + " | ".join(" · ".join(f"{k} {v}" for k, v in ms[c]["regen_why"].items()) or "0" for c in coaches) + " |")
    L.append("| 꼬리 질문 어절 수(최소·중앙·최대) | " + " | ".join(f"{ms[c]['tail_len_min']}·{ms[c]['tail_len_med']}·{ms[c]['tail_len_max']}" for c in coaches) + " |")
    L.append("| 받는 말 끝맺음 종류 수 / 최다 % | " + " | ".join(f"{ms[c]['recv_end_kinds']} / {ms[c]['recv_end_top_pct']}" for c in coaches) + " |")
    L.append("| '리더님'으로 시작(조사 무관) | " + " | ".join(str(ms[c]['lead_any_n']) for c in coaches) + " |")
    L.append("| 전환 턴 갈래 | " + " | ".join(" · ".join(f"{k} {sum(1 for t in ms[c]['trans2'] if t[0] == k)}" for k in ("받는 말", "넘김말", "없음", "받을 내용 없음")
                                                         if any(t[0] == k for t in ms[c]['trans2'])) or "-" for c in coaches) + " |")
    L.append("| 받는 말 붙인 규칙 | " + " | ".join(" · ".join(f"{k} {v}" for k, v in ms[c]["recv_rules"].items()) or "-" for c in coaches) + " |")
    L.append("| 받는 말 전용 호출(통과/탈락 사유) | " + " | ".join(" · ".join(f"{k} {v}" for k, v in ms[c]["recv_calls"].items()) or "-" for c in coaches) + " |")
    L.append("| 구체화 질문 수 | " + " | ".join(str(ms[c]["specify_n"]) for c in coaches) + " |")
    L.append("| 첫 꼬리 질문 기록 | " + " | ".join(" · ".join(f"{k} {v}" for k, v in sorted(ms[c]["fp_mode"].items())) or "-" for c in coaches) + " |")
    coach_cost = sum(ms[c]["cost_usd"] for c in coaches)
    L += ["", f"실제 USD: 코치 쪽 ${coach_cost:.4f}" + ("" if args.no_run else f" + 시뮬 리더 쪽 ${leader_cost:.4f} = ${coach_cost + leader_cost:.4f}"),
          "", f"판정: {'통과' if all_ok else '미달 있음'} — '첫 꼬리 질문이 리더 본인의 말·조치를 물었는가'는 아래 문장을 읽어 따로 판정한다.", ""]
    for c in coaches:
        L.append(f"## {COACH_NAMES[c].capitalize()} — 첫 꼬리 질문 {len(ms[c]['first_probes'])}개")
        L += [f"{n}. [{a} · {mode}] {t}" for n, (a, mode, t) in enumerate(ms[c]["first_probes"], 1)]
        if ms[c]["short_list"]:
            L.append("8어절 미만 질문: " + " / ".join(ms[c]["short_list"]))
        if ms[c]["short_bare_list"]:
            L.append("그중 받는 말 없이 나간 것: " + " / ".join(ms[c]["short_bare_list"]))
        for k, v in sorted(ms[c]["call_drops"].items(), key=lambda kv: -len(kv[1])):
            L.append(f"탈락 [{k}] {len(v)}건: " + " / ".join(v[:3]))
        L.append(f"(A) 맥락 없는 본론 턴 {len(ms[c]['ctx_bare_list'])}/{ms[c]['echo_main_n']}:")
        L += [f"   - {q}" for q in ms[c]["ctx_bare_list"]]
        L.append(f"a) 리더 답을 6어절 넘게 옮긴 질문 {ms[c]['echo_front_n']}:")
        L += [f"   - {q}" for q in ms[c]["echo_front_list"]]
        if ms[c]["tail_recv_list"]:
            L.append("b) 받는 말이 붙은 꼬리 질문 턴: " + " / ".join(ms[c]["tail_recv_list"]))
        if ms[c]["lead_addr_list"]:
            L.append("d) '리더님께서'로 시작한 턴: " + " / ".join(ms[c]["lead_addr_list"]))
        if ms[c]["tail_short_list"]:
            L.append("8어절 미만 꼬리 질문: " + " / ".join(ms[c]["tail_short_list"]))
        L.append(f"전환 턴 {len(ms[c]['trans2'])}개(영역별 되짚기형 {ms[c]['echo_trans_by_ch']}):")
        L += [f"   - [{k}] {t}" for k, _ch, t in ms[c]["trans2"]]
        L.append("꼬리 질문 전체(턴 · 어절 수 · 질문 · 리더 답을 옮긴 부분의 어절 수):")
        L += [f"   - t{x['t']} · {len(x['q'].split())}어절 · {x['q']} · 옮긴 부분 {x['borrow']}어절"
              + ((" (첫 꼬리: 대체 문장)" if x['fallback'] else f" (첫 꼬리: {'다시 써서 ' if x['fp_retry'] else ''}후보 {x['pick']})") if x['first'] else "")
              + (" (슬롯)" if x['slot'] else "") + (" (구체화)" if x['specify'] else "") + (f" (다시 씀: {x['regen']})" if x['regen'] else "")
              + (" (직접 묻는 꼴로 바꿈)" if x['direct'] else "") for x in ms[c]["tail_rows"]]
        if ms[c]["recv_echo"]:
            L.append("받는 말과 질문 앞 절이 겹친 턴: " + " / ".join(ms[c]["recv_echo"]))
        L.append("")
    text = "\n".join(L)
    (out_dir / f"regression_{args.tag}_summary.md").write_text(text, encoding="utf-8")
    print(text)
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
