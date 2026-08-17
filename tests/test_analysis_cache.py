"""§3: 분석/게이트 결과 영속 캐시 — 재분석 0콜 검증.

로직만 고쳤을 때(프롬프트 버전 불변) LLM 호출이 0이어야 한다.
게이트를 동일 입력으로 2회 실행하고, 2회차 LLM 호출이 0인지(캐시 적중) 확인.
파일 영속(프로세스 재시작에 견딤)도 확인.
"""
import asyncio
import json
import os
import sys
import tempfile

# 임시 캐시 디렉터리로 격리(회귀 스위트 오염 방지).
_TMP = tempfile.mkdtemp(prefix="acache_")
os.environ["ANALYSIS_CACHE_DIR"] = _TMP
os.environ["ANALYSIS_CACHE_ENABLED"] = "1"

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from diag_project.services import analysis_cache as AC  # noqa: E402
from diag_project.services import level_gate as LG  # noqa: E402
from diag_project.services.level_gate import gate_verify_levels  # noqa: E402

P = [0, 0]


def ck(label, ok, extra=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label} {extra}")
    P[0] += ok
    P[1] += (not ok)


def test_cache_roundtrip_and_persist():
    k = AC.make_key("v1", "조직", "발화A")
    AC.set("unit_ns", k, {"x": 1})
    ck("set→get 왕복", AC.get("unit_ns", k) == {"x": 1})
    # 파일 영속 확인 (직접 파일 읽기)
    path = os.path.join(_TMP, "unit_ns.json")
    ck("파일 영속", os.path.exists(path)
       and json.load(open(path, encoding="utf-8")).get(k) == {"x": 1})
    # 다른 버전 키 → 미적중
    ck("버전 다르면 미적중",
       AC.get("unit_ns", AC.make_key("v2", "조직", "발화A")) is None)


def test_gate_cache_second_run_zero_calls():
    LG._GATE_CACHE.clear()
    calls = {"n": 0}

    async def counting_llm(_p):
        calls["n"] += 1
        return json.dumps({"results": [
            {"idx": 1, "supported_level": 3, "category": "구체행동",
             "reason": "ok"}]})

    m = {"갈등관리": {"evidence": ["두 팀원 직접 통합 조율한 사례"],
                  "claimed_level": 3}}
    loop = asyncio.get_event_loop()
    r1 = loop.run_until_complete(
        gate_verify_levels("people_management", m, counting_llm))
    n1 = calls["n"]
    # in-mem 비우고 2회차 — 파일 캐시에서 반환되어야(0콜)
    LG._GATE_CACHE.clear()
    r2 = loop.run_until_complete(
        gate_verify_levels("people_management", m, counting_llm))
    n2 = calls["n"] - n1
    ck("1회차 LLM 호출 발생", n1 == 1, f"(n1={n1})")
    ck("2회차 LLM 호출 0 (캐시 적중)", n2 == 0, f"(n2={n2})")
    ck("결과 동일", r1["갈등관리"]["verified_level"]
       == r2["갈등관리"]["verified_level"] == 3)


def _run():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            print(f"— {name}")
            fn()
    print(f"\n=== §3 분석 캐시: {P[0]} PASS / {P[1]} FAIL ===")
    return P[1]


if __name__ == "__main__":
    sys.exit(1 if _run() else 0)
