"""T6: 검증 프로파일 다변화 — 합성 트랜스크립트 3종 회귀 스위트.

김보통(저-균일) 하나로는 검증 불가능한 항목들을 결정론적으로 검증한다.
  · 혼합형   : 트랙 다양·권한위임 추천 포함·D 정상 생성·max2
  · 고득점형 : D트랙 정상 생성·게이트 통과·상한 클램프
  · 저커버리지: 셧다운 발동·ZeroDivision 방어

실행: pytest tests/test_recommendation_profiles.py  (2026-10-16 pytest 형식으로 전환 — 모듈 수준 asyncio.run·sys.exit 제거)
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.services.course_recommender import (  # noqa: E402
    build_course_recommendation,
)
from diag_project.services.scoring import (  # noqa: E402
    score_shutdown, competency_behavior_score, competency_final_score,
)


class MockLLM:
    """D트랙 게이트용 모의 LLM — match 값을 고정 반환."""
    def __init__(self, match=True):
        self.match = match

    async def _generate_with_retry(self, prompt, max_tokens=300,
                                   json_mode=True, **kwargs):
        import json
        return json.dumps({"match": self.match, "reason": "mock"})


def _sub(comp, name, level, measured=True, ev=1):
    score = float(level) if measured else None
    return {
        "asked": measured, "measured": measured, "level": (level if measured else None),
        "score": score, "evidence": [f"{name} 근거 발화 {i}" for i in range(ev)],
    }


def _details(ledger_by_comp):
    return {c: {"sub_ledger": subs} for c, subs in ledger_by_comp.items()}


# ── 혼합형: Lv1~4 고르게, 권한위임 명확히 측정 ──
MIXED = _details({
    "organization_management": {
        "비전 제시 및 공유": _sub("o", "비전", 2),
        "전략적 사고": _sub("o", "전략", 1),
    },
    "people_management": {
        "권한위임": _sub("p", "권한위임", 1, ev=2),
        "코칭 및 피드백": _sub("p", "코칭", 2),
        "갈등관리": _sub("p", "갈등", 4, ev=2),   # Lv4 강점 후보(→D)
    },
    "performance_management": {
        "실행력": _sub("pf", "실행력", 3),
        "문제해결": _sub("pf", "문제해결", 2),
    },
    "work_management": {
        "업무분장": _sub("w", "업무분장", 1),
        "디지털 활용 능력": _sub("w", "디지털", 3),
    },
    "self_management": {
        "자기인식": _sub("s", "자기인식", 2),
        "회복탄력성": _sub("s", "회복", 3),
    },
})

# ── 고득점형: 대부분 Lv3~4, 근거 풍부 ──
HIGH = _details({
    "organization_management": {
        "비전 제시 및 공유": _sub("o", "비전", 4, ev=3),
        "전략적 사고": _sub("o", "전략", 3, ev=2),
    },
    "people_management": {
        "갈등관리": _sub("p", "갈등", 4, ev=3),
        "코칭 및 피드백": _sub("p", "코칭", 3, ev=2),
    },
    "performance_management": {"실행력": _sub("pf", "실행력", 4, ev=2)},
    "work_management": {"업무분장": _sub("w", "업무분장", 3, ev=2)},
    "self_management": {"자기인식": _sub("s", "자기인식", 3, ev=2)},
})

# ── 저커버리지형: 대부분 회피, measured ≤ 8 ──
LOW = _details({
    "organization_management": {
        "비전 제시 및 공유": _sub("o", "비전", 1),
        "전략적 사고": _sub("o", "전략", 1, measured=False),
        "변화관리(변화지향)": _sub("o", "변화", 1, measured=False),
    },
    "people_management": {
        "갈등관리": _sub("p", "갈등", 1),
        "코칭 및 피드백": _sub("p", "코칭", 1, measured=False),
    },
    "performance_management": {"실행력": _sub("pf", "실행력", 2)},
    # work_management / self_management 전량 미측정 → 대역량 None (ZeroDiv 방어)
    "work_management": {"업무분장": _sub("w", "업무분장", 1, measured=False)},
    "self_management": {"자기인식": _sub("s", "자기인식", 1, measured=False)},
})


def _run(coro):
    """현재 루프를 비워 두지 않는 실행 헬퍼(다른 테스트 파일의 get_event_loop() 호환)."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


def test_mixed_profile_recommendation():
    rec = _run(build_course_recommendation(MIXED, llm=MockLLM(match=True)))
    subs = [g["sub_competency"] for g in rec["growth"]]
    strength = rec.get("strength")
    assert "권한위임" in subs, f"권한위임 추천 누락: 성장={subs}"
    assert strength is not None and strength["track"] == "D", "D트랙 강점이 생성돼야 한다"
    from collections import Counter
    cats = Counter([g["category"] for g in rec["growth"]] +
                   ([strength["category"]] if strength else []))
    assert all(v <= 2 for v in cats.values()), f"대역량 max2 위반: {dict(cats)}"
    bodies = [(g["course"], g["subtitle"], g["reason_overview"]) for g in rec["growth"]]
    assert len(bodies) == len(set(bodies)), "추천 카드 본문이 완전히 같은 쌍이 있다"


def test_high_profile_recommendation_and_clamp():
    rec2 = _run(build_course_recommendation(HIGH, llm=MockLLM(match=True)))
    assert rec2.get("strength") is not None, "D트랙이 게이트를 통과해 생성돼야 한다"
    # 상한 클램프: Lv4 하위(4.0)+가점이 5.0 넘지 않음
    assert competency_final_score(4.0, 0.9, 0.9) == 5.0


def test_low_coverage_shutdown_and_zero_division_guard():
    m_low = sum(1 for c in LOW.values()
                for e in c["sub_ledger"].values() if e["measured"])
    none_comps = sum(
        1 for c in LOW.values()
        if competency_behavior_score(
            [e["score"] for e in c["sub_ledger"].values()]) is None
    )
    assert score_shutdown(none_comps, m_low, 26) is True, f"measured={m_low} None대역량={none_comps}"
    assert competency_behavior_score([None, None]) is None
