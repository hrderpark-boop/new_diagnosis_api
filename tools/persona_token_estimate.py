"""§6(b) 페르소나 절삭 토큰 산출 (LLM 없이, fixture 기반 — 716k/226k/230k 재현).

용법: python tools/persona_token_estimate.py [fixture.json]
  기본 fixture: tests/fixtures/kimbautong_te.json (72턴)

산출: off(전체) / N=20 / N=10 / N=5 / N=10+사건요약 의 세션 페르소나 입력
토큰 합계·flash 추정비용·off 대비 절감률. (코치 입력은 절삭 무관·불변.)
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from tools.persona_context import (  # noqa: E402
    truncate_history, summary_block,
)

_CHARS_PER_TOKEN = 2.5   # 한국어 혼합 근사
_PERSONA_FIXED = 400     # 페르소나 프롬프트+질문+지시 고정분 근사


def _toks(nchars: int) -> float:
    return nchars / _CHARS_PER_TOKEN


def estimate(fixture_path: str) -> dict:
    fx = json.load(open(fixture_path, encoding="utf-8"))
    msgs = fx["messages"]
    events = fx.get("events", [])
    ev_summaries = [e.get("summary") for e in events if e.get("summary")]
    sblock_toks = _toks(len(summary_block(ev_summaries)))

    first = next((m["content"] for m in msgs if m["role"] == "model"), "")
    body = [m for m in msgs if m["role"] in ("user", "model")
            and not (m["role"] == "model" and m["content"] == first)]

    def total(cutoff: int, with_summary: bool) -> float:
        lines = [f"AI 코치: {first}"]
        acc = 0.0
        for m in body:
            if m["role"] == "user":
                hist = truncate_history("\n".join(lines), cutoff)
                t = _toks(len(hist)) + _PERSONA_FIXED
                if cutoff > 0 and with_summary:
                    t += sblock_toks
                acc += t
                lines.append(f"사용자: {m['content']}")
            else:
                lines.append(f"AI 코치: {m['content']}")
        return acc

    base = total(0, False)
    out = {"events": len(events), "summary_block_tokens": int(sblock_toks),
           "rows": {}}
    for label, cut, ws in [("off", 0, False), ("N=20", 20, False),
                           ("N=10", 10, False), ("N=5", 5, False),
                           ("N=10+요약", 10, True)]:
        tt = total(cut, ws)
        out["rows"][label] = {
            "tokens": int(tt), "usd_flash_in": round(tt * 0.30 / 1e6, 4),
            "saving_pct": 0 if cut == 0 else round((1 - tt / base) * 100)}
    return out


if __name__ == "__main__":
    fp = (sys.argv[1] if len(sys.argv) > 1 else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "tests/fixtures/kimbautong_te.json"))
    r = estimate(fp)
    print(f"사건 {r['events']}개 · 요약블록 ~{r['summary_block_tokens']}토큰")
    print(f"{'조건':10} {'페르소나입력토큰':>14} {'flash$':>9} {'절감':>6}")
    for k, v in r["rows"].items():
        print(f"  {k:8} {v['tokens']:>14} {v['usd_flash_in']:>9} "
              f"{v['saving_pct']:>5}%")
