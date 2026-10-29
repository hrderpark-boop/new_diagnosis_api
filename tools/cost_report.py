"""usage_*.jsonl(호출별 실제 토큰) → 단계별 호출 수·토큰·USD. 용법: python cost_report.py usage_s292_2.jsonl ..."""
import json, sys, collections
PRICE = {"claude-haiku-5-5": (0.10, 0.50), "claude-sonnet-5-5": (2.00, 10.00)}
STAGE = {"coach_light": "대화", "coach_heavy": "대화", "judge_volunteered": "대화(판정)", "judge_same_q": "대화(판정)", "judge_level": "대화(판정)",
         "deep_analysis": "사전분석 심층", "level_gate": "사전분석 게이트"}
files = sys.argv[1:]
agg = collections.defaultdict(lambda: [0, 0, 0, 0, 0.0])   # calls, in, out, think, usd
for f in files:
    for l in open(f):
        r = json.loads(l); ct = r["call_type"]; m = r["model"]
        pi, po = PRICE.get(m, (0, 0)); usd = (r["in"] * pi + (r["out"] + r["think"]) * po) / 1e6
        a = agg[(STAGE.get(ct, "최종 리포트"), ct, m)]; a[0] += 1; a[1] += r["in"]; a[2] += r["out"]; a[3] += r["think"]; a[4] += usd
n = len(files)
print(f"세션 {n}건 평균 (파일: {', '.join(files)})")
print("| 단계 | call_type | 모델 | 호출 | 입력 tok | 출력 tok | thinking | USD |"); print("|---|---|---|---:|---:|---:|---:|---:|")
tot = [0, 0, 0, 0, 0.0]
for (st, ct, m), a in sorted(agg.items()):
    print(f"| {st} | {ct} | {m.split('-')[1]} | {a[0]/n:.1f} | {a[1]/n:,.0f} | {a[2]/n:,.0f} | {a[3]/n:,.0f} | {a[4]/n:.4f} |")
    for i in range(5): tot[i] += a[i]
print(f"| **합계** | | | {tot[0]/n:.1f} | {tot[1]/n:,.0f} | {tot[2]/n:,.0f} | {tot[3]/n:,.0f} | **{tot[4]/n:.4f}** |")
