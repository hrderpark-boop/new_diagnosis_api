"""(2026-10-29 P2-3 → 2026-11-04 BEI) 분석 결과 린트 — 리포트 scores JSON(파일 또는 sqlite 리포트)에서
'사례 미확인'(no_case / gate_dropped)·'미탐색'(not_explored) 칸 수를 집계한다.

용법: python tools/analysis_lint.py scores1.json [scores2.json …]
      python tools/analysis_lint.py --db replay_x.db        (diagnosis_reports 전부)
통과 기준(3단계): measured ≥ 22/26, 사례 미확인 ≤ 4, 미탐색 세션당 ≤ 1 (2 이상이면 경고, 종료 코드 1).
"""
import json
import sqlite3
import sys

NOT_EXPLORED_WARN_MIN = 2


def summarize(label: str, scores: dict) -> dict:
    det = scores.get("details") or scores.get("competencies") or {}
    cov = scores.get("coverage") or {}
    rows = []
    unc = ne = ev = gate = noc = 0
    levels: dict = {}
    for ck, comp in det.items():
        led = (comp or {}).get("sub_ledger") or {}
        for sub, r in led.items():
            if not isinstance(r, dict):
                continue
            if r.get("status") == "not_explored":
                ne += 1
                rows.append((ck, sub, "not_explored"))
            elif r.get("unconfirmed"):
                unc += 1
                kind = r.get("unconfirmed_kind") or "no_case"
                if kind == "gate_dropped":
                    gate += 1
                else:
                    noc += 1
                rows.append((ck, sub, kind))
            elif r.get("measured"):
                ev += 1
                lv = r.get("level")
                levels[str(lv)] = levels.get(str(lv), 0) + 1
    return {"label": label, "unconfirmed": unc, "no_case": noc, "gate_dropped": gate, "not_explored": ne, "evidence_measured": ev,
            "banner": bool(cov.get("unconfirmed_banner")), "rows": rows, "levels": dict(sorted(levels.items())),
            "comp_labels": {ck: (comp or {}).get("level_label") for ck, comp in det.items()},
            # (2026-11-06 P6) 한 사례가 Lv.3 이상으로 올린 칸(≥3 경고) · '(위 사례와 동일)' 표시 수
            "episode_lift": cov.get("episode_lift") or {}, "lift_warnings": cov.get("episode_lift_warnings") or [],
            "dup_quotes": cov.get("duplicate_quotes_display")}


def main(argv):
    items = []
    if argv and argv[0] == "--db":
        con = sqlite3.connect(argv[1])
        for rid, sc in con.execute("select id, scores from diagnosis_reports order by created_at"):
            items.append((str(rid)[:8], json.loads(sc)))
    else:
        for p in argv:
            items.append((p.split("/")[-1], json.load(open(p, encoding="utf-8"))))
    print("| 리포트 | 근거 측정 | 사례 미확인(없음/게이트 탈락) | 미탐색 | 레벨 분포 | 배너(≥6) | 대역량 라벨 |")
    print("|---|---:|---:|---:|---|---|---|")
    warn = 0
    for label, sc in items:
        s = summarize(label, sc)
        flag = " ⚠" if s["not_explored"] >= NOT_EXPLORED_WARN_MIN else ""
        warn += int(s["not_explored"] >= NOT_EXPLORED_WARN_MIN)
        print(f"| {s['label']} | {s['evidence_measured']} | {s['unconfirmed']}({s['no_case']}/{s['gate_dropped']}) | {s['not_explored']}{flag} | "
              + " ".join(f"Lv{k}:{v}" for k, v in s["levels"].items()) + f" | {'예' if s['banner'] else '-'} | " + ", ".join(f"{k[:4]}:{v or '-'}" for k, v in s["comp_labels"].items()) + " |")
        for ck, sub, kind in s["rows"]:
            print(f"    · {kind}: {ck}/{sub}")
        for w in s["lift_warnings"]:
            print(f"    ⚠ 한 사례가 Lv.3 이상 ≥3칸: {w}")
        if s["episode_lift"]:
            print("    사례별 Lv.3+ 칸: " + " / ".join(f"{k} {len(v)}" for k, v in s["episode_lift"].items()) + (f" · 중복 인용 표시 {s['dup_quotes']}" if s["dup_quotes"] is not None else ""))
    print(f"\n미탐색 2개 이상 세션: {warn} (0 이어야 함)")
    return 0 if warn == 0 else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
