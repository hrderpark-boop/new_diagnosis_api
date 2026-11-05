"""(2026-11-05 3단계 전 1) 사례→하위역량 매핑 정밀도 — 시뮬 정답(tools/sim_profiles/edu_team_lead.json) 고정 사례 8개를 실 Haiku 로 매핑해
strong 라벨의 정밀도 ≥ 0.8 · 재현율 ≥ 0.9 를 확인한다. FM_LIVE_MAP_TEST=1 과 ANTHROPIC_API_KEY 가 있을 때만(8콜, ≈ $0.01).
과다 매핑(정밀도 낮음)은 SWEEP 생략 → 분석 gate_dropped 로 이어지므로 정밀도가 기준이다."""
import asyncio
import json
import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except Exception:  # noqa: BLE001
    pass

CASES = ["E1", "E2", "E7", "E3", "E8", "E4", "E5", "E6"]   # 조직 3 · 성과 2 · 사람 2 · 일 1
_Q = {"context": "그 일은 언제, 어떤 상황이었나요?", "action": "그때 직접 무엇을 하셨어요?", "reaction": "상대 반응은 어땠나요?",
      "result": "그 뒤 결과는 어떻게 됐나요?", "criterion": "그 선택의 기준은 무엇이었나요?", "reflection": "다시 한다면 어떻게 하고 싶으세요?"}


def map_cases(svc):
    from diag_project.data.competencies import COMPETENCY_FRAMEWORK as F
    from diag_project.services import slot_judge as SJ
    prof = json.load(open(ROOT / "tools/sim_profiles/edu_team_lead.json", encoding="utf-8"))
    eps = {e["id"]: e for e in prof["episodes"]}
    tp = fp = fn = 0
    rows = []
    for cid in CASES:
        e = eps[cid]
        tr = [x for k in ("context", "action", "reaction", "result", "criterion", "reflection") for x in (("model", _Q[k]), ("user", e[k]))]
        labels = asyncio.run(SJ.map_episode(svc, transcript=tr, chapter_name=F[e["chapter"]]["name"],
                                            sub_defs=SJ.sub_defs_for(e["chapter"]), opener_sub=e["subs"][0]))
        strong = {lb["sub"] for lb in labels if lb["strength"] == "strong"}
        truth = set(e["subs"])
        tp += len(strong & truth); fp += len(strong - truth); fn += len(truth - strong)
        rows.append((cid, sorted(truth), sorted(strong), [(lb["sub"], lb["strength"], lb.get("confidence")) for lb in labels]))
    p = tp / max(1, tp + fp); r = tp / max(1, tp + fn)
    return p, r, rows


@pytest.mark.skipif(not (os.getenv("FM_LIVE_MAP_TEST") == "1" and os.getenv("ANTHROPIC_API_KEY")),
                    reason="실 LLM 매핑 — FM_LIVE_MAP_TEST=1 과 ANTHROPIC_API_KEY 가 있을 때만")
def test_live_map_precision_recall():
    from diag_project.llm_service import GeminiService
    os.environ.pop("FM_LLM_STUB", None)
    try:   # conftest 가 ANTHROPIC_API_KEY=dummy 를 먼저 넣는다 — 실 키로 덮는다
        from dotenv import load_dotenv
        load_dotenv(ROOT / ".env", override=True)
    except Exception:  # noqa: BLE001
        pass
    svc = GeminiService().bind_provider("claude")
    p, r, rows = map_cases(svc)
    for row in rows:
        print(row)
    print(f"precision={p:.2f} recall={r:.2f}")
    assert p >= 0.8 and r >= 0.9, (p, r, rows)
