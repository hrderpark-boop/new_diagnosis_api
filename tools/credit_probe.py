"""크레딧 프리플라이트 — 값비싼 배치 실행 전 1콜로 크레딧 가용 여부만 판정.

flash + thinking=0 최소 호출. 출력(마지막 줄):
  CREDIT_OK        : 사용 가능 → 배치 진행 가능
  CREDIT_DEPLETED  : 선불 크레딧 소진 → 배치 시작 금지
  PROBE_ERROR:<..> : 그 외 오류(네트워크/키 등) → 시작 금지(보수적)

exit code: 0=OK, 3=DEPLETED, 4=기타오류. 배치 하버스트가 이 코드로 분기한다.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), ".env"))


async def main() -> int:
    from diag_project.llm_service import GeminiService
    svc = GeminiService()
    try:
        raw = await svc._generate_with_retry(
            "reply with the single word: ok", max_tokens=64,
            thinking_budget=0, call_type="credit_probe",
        )
        print("probe reply:", (raw or "").strip()[:40])
        print("CREDIT_OK")
        return 0
    except Exception as e:  # noqa: BLE001
        s = str(e)
        if "CREDIT_DEPLETED" in s or "prepayment credit" in s.lower():
            print("CREDIT_DEPLETED")
            return 3
        print("PROBE_ERROR:", s[:160])
        return 4


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
