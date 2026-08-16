"""레벨 서술 매칭 게이트 (T-A 확장).

기존 D트랙 근거 검증 게이트(인용문 ↔ Lv.4 서술 매칭)를 '모든 레벨 판정'으로
확장한다. 판정기가 서술의 유창함이 아니라 competencies.py 의 레벨 서술과
대조해 레벨을 확정하도록 강제한다.

  현재: evidence → (주제 매칭) → sub_key → (유창함) → level
  수정: evidence → (주제 매칭) → sub_key → (levels[N] 서술 대조) → level
        매칭 실패 시 한 단계 낮추고 재검증. 최하위에서도 실패하면 measured=False.

효율을 위해 대역량 단위로 배치 검증(측정된 하위역량들을 한 번의 LLM 호출로
판정)한다. LLM 이 없으면(단위 테스트 등) 게이트를 건너뛰고 claimed_level 을
그대로 둔다(보수적: 판사 없이 강등하지 않음).
"""
import asyncio
import json
import logging
from typing import Any, Dict

from diag_project.data.competencies import COMPETENCY_FRAMEWORK

logger = logging.getLogger(__name__)

# 게이트 호출을 전역 직렬화 — 대역량 분석 5건이 병렬(gather)로 도는 동안
# 게이트 LLM 호출까지 겹쳐 일부 키가 LLM_EMPTY_RESPONSE 를 반환하는 것을 막는다.
# 한 번에 하나의 게이트 호출만 나가게 해 동시성 스파이크를 제거한다.
_GATE_SEMAPHORE = asyncio.Semaphore(1)


def level_reference(competency_key: str, sub_name: str) -> Dict[int, str]:
    """해당 하위역량의 레벨(1~4) 서술 + 행동 예시를 합쳐 반환.

    게이트가 evidence 를 대조할 '기준 서술'. 없으면 빈 dict.
    """
    comp = COMPETENCY_FRAMEWORK.get(competency_key) or {}
    for ind in (comp.get("indicators") or {}).values():
        if ind.get("name") == sub_name:
            levels = ind.get("levels") or {}
            examples = ind.get("examples") or {}
            out: Dict[int, str] = {}
            for lv in (1, 2, 3, 4):
                desc = str(levels.get(lv, "")).strip()
                ex = str(examples.get(lv, "")).strip()
                out[lv] = (desc + ("\n" + ex if ex else "")).strip()
            return out
    return {}


def _build_gate_prompt(items: list) -> str:
    """배치 게이트 프롬프트. items: [{sub_name, evidence, claimed_level, ref}]."""
    blocks = []
    for i, it in enumerate(items, 1):
        ref = it["ref"]
        ref_txt = "\n".join(f"  · Lv.{lv}: {ref.get(lv, '')}" for lv in (1, 2, 3, 4))
        ev_txt = "\n".join(f"  - {e}" for e in it["evidence"])
        blocks.append(
            f"[{i}] 하위역량: {it['sub_name']} (판정기 주장 레벨: Lv.{it['claimed_level']})\n"
            f"[레벨 기준 서술]\n{ref_txt}\n[리더 발화(근거)]\n{ev_txt}"
        )
    body = "\n\n".join(blocks)
    return (
        "당신은 BEI(행동사건면접) 채점 감사관이다. 아래 각 하위역량에 대해, "
        "제시된 '리더 발화'가 어느 레벨의 '기준 서술'에 실제로 부합하는지 "
        "냉정하게 판정하라.\n\n"
        "🚨 판정 원칙 (엄격 적용):\n"
        "1. BEI 근거는 '구체 행동 사례'여야 한다 = 시점 + 상황 + 리더가 실제로 "
        "한 행동. 아래는 근거가 아니므로 supported_level=0:\n"
        "   · 태도·신념 진술('~가 중요하다고 생각합니다')\n"
        "   · 일반화 서술('보통 제가 직접 처리하는 편입니다')\n"
        "   · 부재 진술('그런 경험은 없습니다') — 오히려 낮은 수준의 신호\n"
        "2. 구체 행동 사례라면, 그 행동이 '실제로 도달한 가장 높은 레벨'을 고른다. "
        "서술이 유창하다고 레벨을 올리지 말 것. 기준 서술과의 '행동 수준' 일치만 본다.\n"
        "3. 주장 레벨보다 높게 올리지 말 것(게이트는 강등 또는 유지만 한다). "
        "발화가 기준에 못 미치면 한 단계씩 낮춘다. Lv.1 기준에도 못 미치면 0.\n\n"
        f"{body}\n\n"
        '출력(JSON, 마크다운 금지): {"results": [{"idx": <번호>, '
        '"supported_level": <0~4>, "category": "구체행동|태도|일반화|부재", '
        '"reason": "판정 근거 한 줄"}]}'
    )


async def gate_verify_levels(
    competency_key: str,
    measured: Dict[str, Dict[str, Any]],
    llm,
) -> Dict[str, Dict[str, Any]]:
    """측정된 하위역량들의 레벨을 배치 검증.

    measured: {sub_name: {"evidence": [str...], "claimed_level": int}}
    반환: {sub_name: {"verified_level": int|None, "category": str, "reason": str,
                      "downgraded": bool, "dropped": bool}}
      · verified_level=None → measured=False (근거 자격 미달)
      · verified_level < claimed → 강등
    LLM 이 없거나 실패하면 claimed_level 을 그대로 통과(보수적).
    """
    out: Dict[str, Dict[str, Any]] = {}
    items = []
    for sub, info in measured.items():
        ref = level_reference(competency_key, sub)
        claimed = info.get("claimed_level") or 1
        if not ref or not info.get("evidence"):
            # 기준 서술이 없으면 게이트 불가 → 유지(보수적)
            out[sub] = {"verified_level": claimed, "category": "미검증",
                        "reason": "레벨 기준 서술 없음", "downgraded": False,
                        "dropped": False}
            continue
        items.append({"sub_name": sub, "evidence": info["evidence"],
                      "claimed_level": claimed, "ref": ref})

    if not items:
        return out
    if llm is None:
        for it in items:
            out[it["sub_name"]] = {
                "verified_level": it["claimed_level"], "category": "미검증",
                "reason": "LLM 게이트 미가동", "downgraded": False,
                "dropped": False}
        return out

    prompt = _build_gate_prompt(items)

    async def _call_gate():
        # 직렬화 + 빈 응답/오류 시 1회 재시도(동시성 스파이크 해소용 지연).
        async with _GATE_SEMAPHORE:
            last = None
            for attempt in range(2):
                try:
                    raw = await llm(prompt)
                    if raw and raw.strip():
                        return raw
                    last = "빈 응답"
                except Exception as e:  # noqa: BLE001
                    last = str(e)
                await asyncio.sleep(2.0 * (attempt + 1))
            raise RuntimeError(last or "게이트 응답 없음")

    try:
        raw = await _call_gate()
        raw = (raw or "").replace("```json", "").replace("```", "").strip()
        res = json.loads(raw)
        by_idx = {int(r.get("idx")): r for r in (res.get("results") or [])}
    except Exception as e:  # noqa: BLE001
        logger.warning("레벨 게이트 판정 실패(%s) → claimed 유지", e)
        for it in items:
            out[it["sub_name"]] = {
                "verified_level": it["claimed_level"], "category": "미검증",
                "reason": f"게이트 오류: {e}", "downgraded": False,
                "dropped": False}
        return out

    for i, it in enumerate(items, 1):
        r = by_idx.get(i) or {}
        claimed = it["claimed_level"]
        sup = r.get("supported_level")
        sup = int(sup) if isinstance(sup, (int, float)) else claimed
        sup = max(0, min(sup, claimed))  # 강등/유지만, 상향 금지
        verified = None if sup <= 0 else sup
        out[it["sub_name"]] = {
            "verified_level": verified,
            "category": r.get("category", "미검증"),
            "reason": str(r.get("reason", ""))[:120],
            "downgraded": verified is not None and verified < claimed,
            "dropped": verified is None,
        }
        if verified is None:
            logger.info("🚧 레벨게이트 탈락 [%s/%s] claimed=Lv.%s → 근거미달(%s)",
                        competency_key, it["sub_name"], claimed,
                        out[it["sub_name"]]["category"])
        elif verified < claimed:
            logger.info("🔽 레벨게이트 강등 [%s/%s] Lv.%s→Lv.%s (%s)",
                        competency_key, it["sub_name"], claimed, verified,
                        out[it["sub_name"]]["reason"])
    return out
