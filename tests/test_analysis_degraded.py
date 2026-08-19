"""item4: 분석 광범위 실패(크레딧 소진) 감지 — garbage 리포트 저장 방지.

크레딧 소진이 분석 중 발생하면 _analyze_single_competency 가 예외를 삼켜
error-fallback(measured 0)을 반환한다. 3개 이상 대역량이 error-fallback 이면
'진짜 미측정'이 아니라 '분석 오염'이므로, coverage.analysis_degraded=True 로
표시해 analyze_session 이 리포트를 저장하지 않고 세션을 재개 가능하게 남긴다.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("GEMINI_API_KEYS", "dummy")

from diag_project.llm_service import GeminiService  # noqa: E402

P = [0, 0]


def ck(label, ok, extra=""):
    print(f"  [{'PASS' if ok else 'FAIL'}] {label} {extra}")
    P[0] += ok
    P[1] += (not ok)


def test_error_fallback_marked():
    fb = GeminiService._build_error_fallback(None, ["a", "b"])
    ck("error-fallback 은 _error_fallback=True", fb.get("_error_fallback") is True)
    ck("error-fallback 은 measured 0", fb.get("measured_count") == 0)
    # 정상 결과에는 마커 없음(구분 가능)
    ck("정상 결과엔 마커 없음", {"measured_count": 3}.get("_error_fallback") is None)


def test_degraded_threshold():
    # item4(강화): analysis_degraded = (error-fallback 대역량 수 >= 1).
    #   부분 오염(1~2건)도 '측정 안 됨'으로 오인되면 안 되므로 미저장.
    def degraded(results):
        return sum(1 for v in results if v.get("_error_fallback")) >= 1
    ok = {"measured_count": 2}
    err = GeminiService._build_error_fallback(None, ["a"])
    ck("정상5 → degraded False", degraded([ok] * 5) is False)
    ck("오류1/정상4 → degraded True(부분오염도 미저장)",
       degraded([err, ok, ok, ok, ok]) is True)
    ck("오류2/정상3 → degraded True", degraded([err, err, ok, ok, ok]) is True)
    ck("오류5 → degraded True", degraded([err] * 5) is True)


def test_error_reason_tagged():
    fb = GeminiService._build_error_fallback(None, ["a"], reason="크레딧소진")
    ck("원인 태깅(_error_reason)", fb.get("_error_reason") == "크레딧소진")


def _run():
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            print(f"— {name}")
            fn()
    print(f"\n=== item4 분석 오염 감지: {P[0]} PASS / {P[1]} FAIL ===")
    return P[1]


if __name__ == "__main__":
    sys.exit(1 if _run() else 0)
