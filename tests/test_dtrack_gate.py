"""V-1: D트랙 강점 게이트 양방향 검증 (실제 LLM, 키 없으면 SKIP).

배경: 게이트가 max_tokens=300 이던 동안 thinking 모델이 예산을 소진해 항상
빈 응답 → fail-closed 로 카드가 '한 번도' 생성되지 않았다(=검증이 아니라 무조건
거부). 4096 상향 후 게이트가 '판단해서' 차단/통과하는지 양방향으로 고정한다.

  (a) 차단: 실무자적 직접 개입(Lv.1~2) → match=False → D카드 미생성
  (b) 통과: 조직 차원 시스템 설계·재설계(Lv.4) → match=True → D카드 생성

키가 없으면 SKIP(반환 0) — 결정론 회귀 스위트를 깨지 않는다.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BLOCK = {
    "comp_key": "work_management", "sub_name": "자원 및 시간관리", "score": 3.6,
    "evidence": ["담당 팀원이 혼자 해결하기 어려워 보여서, 제가 직접 나서서 "
                 "데이터를 하나하나 대조하며 오류를 찾아내고 수정해서 겨우 "
                 "마감 기한을 맞췄습니다"],
}
PASS = {
    "comp_key": "work_management", "sub_name": "자원 및 시간관리", "score": 3.8,
    "evidence": ["팀 예산이 매년 초과되는 구조를 발견하고, 부서 예산관리 "
                 "시스템 자체를 새로 설계해 자원 배분 기준을 재정립했습니다. "
                 "이후 조직 전체의 시간·자원 낭비 구조를 진단해 반복 업무 "
                 "프로세스를 재설계했고, 그 방식이 다른 부서로도 확산됐습니다"],
}


def _has_keys() -> bool:
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
    except Exception:  # noqa: BLE001
        pass
    return bool(os.getenv("GEMINI_API_KEYS") or os.getenv("GEMINI_API_KEY"))


async def _run():
    from diag_project.llm_service import GeminiService
    from diag_project.services.course_recommender import _strength_gate_pass
    svc = GeminiService()
    blocked = await _strength_gate_pass(BLOCK, svc)
    passed = await _strength_gate_pass(PASS, svc)
    return blocked, passed


def main():
    if not _has_keys():
        print("  [SKIP] GEMINI_API_KEYS 없음 — D트랙 게이트 실측 생략(정상)")
        return 0
    blocked, passed = asyncio.get_event_loop().run_until_complete(_run())
    p = [0, 0]

    def ck(label, ok):
        print(f"  [{'PASS' if ok else 'FAIL'}] {label}")
        p[0] += ok
        p[1] += (not ok)

    ck("(a) 실무자 직접개입 → 차단(match=False)", blocked is False)
    ck("(b) 조직 시스템 설계 → 통과(match=True)", passed is True)
    print(f"\n=== V-1 D트랙 게이트 양방향: {p[0]} PASS / {p[1]} FAIL ===")
    return p[1]


if __name__ == "__main__":
    sys.exit(1 if main() else 0)
