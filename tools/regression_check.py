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
    p50 ≤ 3.8초 · p95 ≤ 8.0초(점검표 값 — 올림 순위) · 재생성 걸린 턴 ≤ 8 · 형식미해결 0 · 깨진 문장 0 · 첫 꼬리 질문 fallback ≤ 1
    (P14b) 받는 말 있는 본론 턴 40~75% · 받는 말 평균 9어절 이하 · 12어절 초과 0 · 받는 말과 질문 앞 절이 겹친 턴 0(낱말 겹침 60% 이상)
           받는 말 끝맺음 한 가지 ≤ 40% · 8어절 미만 질문 중 받는 말 없이 나간 것 ≤ 1 · 구체화 질문이 2회 이상인 사례 0
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
    ("p50 ≤ 3.8초", "p50", None, 3.8), ("p95 ≤ 8.0초", "p95", None, 8.0), ("재생성 턴 ≤ 8", "regen_turns", None, 8), ("형식미해결 0", "format_miss", None, 0),
    ("깨진 문장 0", "broken_total", None, 0), ("첫 꼬리 fallback ≤ 1", "fp_fallback", None, 1),
    # (2026-11-16 P14 → P14b) 받는 말: 한 턴에 리더 말을 되짚는 것은 한 번 — 있는 턴 40~75%, 평균 9어절 이하, 12어절 초과 0, 질문 앞 절과 겹친 턴 0, 끝맺음 최다 40% 이하
    ("받는 말 있는 본론 턴 40~75%", "recv_have_pct", 40, 75), ("받는 말 평균 ≤ 9어절", "recv_avg_eojeol", None, 9), ("받는 말 12어절 초과 0", "recv_over12", None, 0),
    ("받는 말·질문 앞 절 겹침 0", "recv_echo_n", None, 0), ("받는 말 끝맺음 최다 ≤ 40%", "recv_top_end_pct", None, 40),
    ("8어절 미만 질문 중 받는 말 없는 것 ≤ 1", "short_bare", None, 1), ("구체화 질문 2회 이상인 사례 0", "specify_multi", None, 0),
)
MAIN_INSTR = ("EPISODE_PROBE", "SWEEP_FOLLOWUP", "EPISODE_OPEN", "SWEEP_ANCHOR")


ECHO_RATIO = 0.6


def receive_stats(rows: list[dict]) -> dict:
    """본론 턴(탐침·훑는 질문·여는 턴)의 받는 말 — 유무, 끝맺음 분포, 어절 수, 같은 턴 질문의 앞 절과 겹친 턴, 받는 말 없이 나간 짧은 질문.
    서버가 남긴 recv_out(끝맺음 갈래 | other | slot | None)을 읽는다. 슬롯 문장(관찰·응원) 턴은 받는 말 자리가 없으므로 분모에서 뺀다."""
    from collections import Counter
    import regression_table as rt
    from diag_project.services.output_guard import _content_chunks, is_question
    from diag_project.services.turn_checks import question_front_clause
    by_instr: dict[str, list[int]] = {}
    ends: Counter = Counter()
    rules: Counter = Counter()
    lens: list[int] = []
    echo: list[str] = []
    short_bare: list[str] = []
    for r in rows:
        if r.get("role") != "model" or r.get("instr") not in MAIN_INSTR:
            continue
        g = r.get("guard") or {}
        out = g.get("recv_out")
        if g.get("recv_rule"):
            rules[str(g.get("recv_rule"))] += 1
        if out == "slot":
            continue
        sents = [x.strip() for x in rt.sentences(r.get("content") or "") if x.strip()]
        qs = [x for x in sents if is_question(x)]
        a = by_instr.setdefault(r["instr"], [0, 0])
        a[1] += 1
        if out:
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
    return {"recv_have_pct": round(100 * have / total, 1) if total else None, "recv_top_end_pct": round(100 * top / have, 1) if have else None,
            "recv_avg_eojeol": round(sum(lens) / len(lens), 1) if lens else None, "recv_over12": sum(1 for n in lens if n > 12),
            "recv_echo_n": len(echo), "recv_echo": echo, "short_bare": len(short_bare), "short_bare_list": short_bare,
            "recv_by_instr": {k: f"{v[0]}/{v[1]}" for k, v in by_instr.items()}, "recv_ends": dict(ends.most_common()), "recv_rules": dict(rules.most_common())}


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
        out.append((name, v, v is not None and float(v) <= float(hi) and (lo is None or float(v) >= float(lo))))
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
            **receive_stats(rows), **specify_stats(data), **call_stats(rows),
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
    L.append("| 세션 상태 | " + " | ".join(str(ms[c]["status"]) for c in coaches) + " |")
    all_ok = all_ok and all(str(ms[c]["status"]) == "completed" for c in coaches)
    L.append("| 받는 말(턴 종류별 있음/전체) | " + " | ".join(" · ".join(f"{k} {v}" for k, v in ms[c]["recv_by_instr"].items()) or "-" for c in coaches) + " |")
    L.append("| 받는 말 끝맺음 분포 | " + " | ".join(" · ".join(f"{k} {v}" for k, v in ms[c]["recv_ends"].items()) or "-" for c in coaches) + " |")
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
        if ms[c]["recv_echo"]:
            L.append("받는 말과 질문 앞 절이 겹친 턴: " + " / ".join(ms[c]["recv_echo"]))
        L.append("")
    text = "\n".join(L)
    (out_dir / f"regression_{args.tag}_summary.md").write_text(text, encoding="utf-8")
    print(text)
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
