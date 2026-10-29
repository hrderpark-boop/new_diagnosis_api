"""(2026-10-29 P2-3) 분석 결과 린트 — 리포트 scores JSON(파일 또는 sqlite 리포트)에서 '사례 미확인' 칸 수·탐침 횟수·탐침 2회 미만 미확인을 집계한다.

용법: python tools/analysis_lint.py scores1.json [scores2.json …]
      python tools/analysis_lint.py --db replay_x.db        (diagnosis_reports 전부)
통과 기준: '탐침 2회 미만 미확인' 0.
"""
import json
import sqlite3
import sys


def summarize(label: str, scores: dict) -> dict:
    det = scores.get("details") or scores.get("competencies") or {}
    cov = scores.get("coverage") or {}
    rows = []
    unc = deficit = ev = 0
    for ck, comp in det.items():
        led = (comp or {}).get("sub_ledger") or {}
        for sub, r in led.items():
            if not isinstance(r, dict):
                continue
            if r.get("unconfirmed"):
                unc += 1
                deficit += int(bool(r.get("probe_deficit")))
                rows.append((ck, sub, r.get("unconfirmed_kind"), r.get("probe_count"), r.get("generalize_probed"), r.get("probe_deficit")))
            elif r.get("measured"):
                ev += 1
    return {"label": label, "unconfirmed": unc, "probe_deficit": deficit, "evidence_measured": ev,
            "banner": bool(cov.get("unconfirmed_banner")), "rows": rows,
            "comp_labels": {ck: (comp or {}).get("level_label") for ck, comp in det.items()}}


def main(argv):
    items = []
    if argv and argv[0] == "--db":
        con = sqlite3.connect(argv[1])
        for rid, sc in con.execute("select id, scores from diagnosis_reports order by created_at"):
            items.append((str(rid)[:8], json.loads(sc)))
    else:
        for p in argv:
            items.append((p.split("/")[-1], json.load(open(p, encoding="utf-8"))))
    print("| 리포트 | 사례 미확인 | 탐침 2회 미만 미확인 | 근거 측정 | 배너(≥6) | 대역량 라벨 |")
    print("|---|---:|---:|---:|---|---|")
    total_def = 0
    for label, sc in items:
        s = summarize(label, sc)
        total_def += s["probe_deficit"]
        print(f"| {s['label']} | {s['unconfirmed']} | {s['probe_deficit']} | {s['evidence_measured']} | {'예' if s['banner'] else '-'} | "
              + ", ".join(f"{k[:4]}:{v or '-'}" for k, v in s["comp_labels"].items()) + " |")
        for ck, sub, kind, pc, gp, pd in s["rows"]:
            if pd:
                print(f"    ⚠ 탐침 부족: {ck}/{sub} kind={kind} probes={pc} generalize_probed={gp}")
    print(f"\n탐침 2회 미만 미확인 합계: {total_def} (0 이어야 함)")
    return 0 if total_def == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
