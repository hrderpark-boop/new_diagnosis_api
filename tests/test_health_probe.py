"""D-1: LLM health probe (CI 상시 편입).

thinking 모델(gemini-2.5-pro/flash)은 max_tokens 가 작으면 사고 토큰이 예산을
소진해 출력이 빈다. 이 probe 는 128/2048/8192 예산에서 실제 응답 여부를
점검한다. API 키가 없으면 SKIP(반환 0) — 결정론 회귀 스위트를 깨지 않는다.

용도:
  · 크레딧/쿼터 상태 점검
  · thinking 모델의 '작은 예산 → 빈 응답' 회귀 감시
  · 게이트/추천/요약 등 저예산 호출이 다시 생기면 조기 경보
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PROMPT = ("아래 문장을 한국어로 자연스럽게 한 문장으로 바꿔줘: "
          "리더십 진단을 시작합니다.")


def _has_keys() -> bool:
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
    except Exception:  # noqa: BLE001
        pass
    return bool(os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY"))


async def _probe():
    from diag_project.llm_service import GeminiService, ANALYSIS_MODEL
    svc = GeminiService()
    results = {}
    for budget in (128, 2048, 8192):
        try:
            r = await svc._generate_with_retry(
                PROMPT, max_tokens=budget, model=ANALYSIS_MODEL)
            results[budget] = bool(r and r.strip())
        except Exception:  # noqa: BLE001
            results[budget] = False
    return results


def main():
    if not _has_keys():
        print("  [SKIP] GEMINI_API_KEYS 없음 — health probe 생략(정상)")
        return 0
    res = asyncio.get_event_loop().run_until_complete(_probe())
    print(f"  probe 결과(비어있지 않음): {res}")
    ok = res.get(8192, False)  # 8192 는 반드시 정상이어야 한다
    print(f"  [{'PASS' if ok else 'FAIL'}] 8192 예산 정상 응답")
    if res.get(128) and not res.get(8192):
        print("  ⚠️ 128 성공/8192 실패 — 비정상")
    print("\n=== health probe: %s ===" % ("PASS" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
