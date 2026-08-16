"""T-A: 레벨 서술 매칭 게이트 단위 테스트 (LLM 모킹).

검증:
  · competencies.py levels/examples 를 레벨 기준으로 조회하는가
  · 부재 진술 → dropped(measured=False)
  · '직접 떠안음' 같은 낮은 수준 행동 → 강등(주장 레벨보다 낮게)
  · 게이트는 상향하지 않는다(강등/유지만)
  · LLM 없으면 claimed 유지(보수적), 대역량 밖 하위역량은 미검증 유지
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.services.level_gate import (  # noqa: E402
    gate_verify_levels, level_reference,
)

P = [0, 0]


def ck(label, ok, extra=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label} {extra}")
    P[0] += ok
    P[1] += (not ok)


def _run_async(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


def test_level_reference_lookup():
    ref = level_reference("people_management", "권한위임")
    ck("levels 1~4 조회", set(ref.keys()) == {1, 2, 3, 4} and len(ref[1]) > 5)
    ck("대역량 밖 하위역량 → 빈 dict",
       level_reference("people_management", "업무분장") == {})


def test_absence_dropped_and_directive_downgraded():
    async def mock(_p):
        return json.dumps({"results": [
            {"idx": 1, "supported_level": 0, "category": "부재",
             "reason": "위임 경험 없음"},
            {"idx": 2, "supported_level": 1, "category": "구체행동",
             "reason": "직접 처리=낮은 수준"},
            {"idx": 3, "supported_level": 3, "category": "구체행동",
             "reason": "정당"},
        ]})
    m = {
        "권한위임": {"evidence": ["위임 경험은 많지 않습니다"], "claimed_level": 1},
        "팀워크 촉진(협업)": {"evidence": ["제가 직접 나눴습니다"],
                       "claimed_level": 2},
        "갈등관리": {"evidence": ["두 팀원 불만, 직접 통합"], "claimed_level": 3},
    }
    r = _run_async(gate_verify_levels("people_management", m, mock))
    ck("부재 진술 → dropped(measured=False)",
       r["권한위임"]["verified_level"] is None and r["권한위임"]["dropped"])
    ck("직접처리 → 강등(2→1)",
       r["팀워크 촉진(협업)"]["verified_level"] == 1
       and r["팀워크 촉진(협업)"]["downgraded"])
    ck("정당 → 유지(3)", r["갈등관리"]["verified_level"] == 3
       and not r["갈등관리"]["downgraded"])


def test_gate_never_upgrades():
    async def mock(_p):
        return json.dumps({"results": [
            {"idx": 1, "supported_level": 4, "category": "구체행동",
             "reason": "게이트가 상향 시도"},
        ]})
    m = {"갈등관리": {"evidence": ["직접 통합 처리"], "claimed_level": 2}}
    r = _run_async(gate_verify_levels("people_management", m, mock))
    ck("상향 금지: 4 주장해도 claimed(2) 상한",
       r["갈등관리"]["verified_level"] == 2)


def test_no_llm_keeps_claimed():
    m = {"갈등관리": {"evidence": ["직접 통합 처리"], "claimed_level": 3}}
    r = _run_async(gate_verify_levels("people_management", m, None))
    ck("LLM 없으면 claimed 유지", r["갈등관리"]["verified_level"] == 3
       and not r["갈등관리"]["dropped"])


def _main():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            print(f"— {name}")
            fn()
    print(f"\n=== 레벨 게이트: {P[0]} PASS / {P[1]} FAIL ===")
    return P[1]


if __name__ == "__main__":
    sys.exit(1 if _main() else 0)
