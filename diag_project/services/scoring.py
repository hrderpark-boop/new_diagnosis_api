"""진단 점수 연산 — 순수 함수 계층 (LLM 판단과 분리).

지시서 P0-1/P0-3 준수. LLM 은 '하위역량 단위 레벨 판정(1~4) + 근거 발화 추출'
까지만 하고, 이 모듈이 아래를 '코드로만' 결정론적으로 계산한다.

산식 (P0-3):
  · 하위역량 점수 = clamp(level, 1.0, 4.0)   — 가점 없음. measured 아니면 None
  · 대역량 행동지표평가 = mean(measured 하위역량 점수)  — 독립 산출 금지
  · 대역량 최종점수 = clamp(행동지표평가 + STAR가점 + 확신도가점, 1.0, 5.0)
  · 종합 리더십 점수 = mean(measured 대역량 최종점수)

measured (P0-1): asked == True AND len(evidence_utterances) >= 1
  (미측정 하위역량은 점수 산출하지 않고 None → 리포트 '미측정' 표기)

방어(보완 지시): measured 하위역량이 0개인 대역량은 평균 계산 시 ZeroDivision
  없이 None 을 반환하여 대역량 자체를 '미측정'으로 안전 렌더링한다.
"""

from __future__ import annotations

from dataclasses import dataclass, field

SUB_SCORE_MIN = 1.0
SUB_SCORE_MAX = 4.0   # 하위역량은 레벨 1~4 와 1:1 → 상한 4.0 하드 클램프
COMP_SCORE_MIN = 1.0
COMP_SCORE_MAX = 5.0  # 대역량은 가점 포함 → 상한 5.0
STAR_BONUS_MAX = 0.5
CONFIDENCE_ADJ_MIN = -0.5
CONFIDENCE_ADJ_MAX = 0.5


def clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


@dataclass
class SubLedger:
    """하위역량 증거 원장 (P0-1)."""
    name: str
    asked: bool = False
    evidence_utterances: list[str] = field(default_factory=list)
    level: int | None = None  # LLM 레벨 판정 1~4

    @property
    def measured(self) -> bool:
        return bool(self.asked) and len(self.evidence_utterances) >= 1

    @property
    def score(self) -> float | None:
        """측정된 경우에만 [1.0, 4.0] 클램프 점수. 아니면 None(미측정)."""
        if not self.measured or self.level is None:
            return None
        return round(clamp(float(self.level), SUB_SCORE_MIN, SUB_SCORE_MAX), 1)


def competency_behavior_score(sub_scores: list[float | None]) -> float | None:
    """대역량 행동지표평가 = measured 하위역량 점수 평균. 없으면 None (ZeroDiv 방어)."""
    measured = [s for s in sub_scores if s is not None]
    if not measured:
        return None
    return round(sum(measured) / len(measured), 2)


def competency_final_score(
    behavior_score: float | None,
    star_bonus: float = 0.0,
    confidence_adj: float = 0.0,
) -> float | None:
    """대역량 최종점수 = clamp(행동지표평가 + STAR가점 + 확신도가점, 1.0, 5.0).

    behavior_score 가 None(미측정)이면 None 을 그대로 반환.
    가점은 유효 범위로 먼저 클램프해 상한 붕괴를 막는다.
    """
    if behavior_score is None:
        return None
    sb = clamp(float(star_bonus or 0.0), 0.0, STAR_BONUS_MAX)
    ca = clamp(float(confidence_adj or 0.0), CONFIDENCE_ADJ_MIN, CONFIDENCE_ADJ_MAX)
    return round(clamp(behavior_score + sb + ca, COMP_SCORE_MIN, COMP_SCORE_MAX), 1)


def overall_score(competency_finals: list[float | None]) -> float | None:
    """종합 리더십 점수 = measured 대역량 최종점수 평균. 없으면 None."""
    measured = [s for s in competency_finals if s is not None]
    if not measured:
        return None
    return round(sum(measured) / len(measured), 1)


def coverage(total_measured: int, total_subs: int) -> dict:
    """측정 커버리지 메타. 분모는 26(창의적 사고 통합 후 하위역량 총수)."""
    pct = (total_measured / total_subs) if total_subs else 0.0
    return {
        "measured": total_measured,
        "total": total_subs,
        "ratio": round(pct, 3),
        "label": f"측정 {total_measured} / {total_subs}",
        "is_low_confidence": pct < 0.40,   # 40% 미만 → 재진단 권고
    }


def competency_is_reference(measured_subs: int, total_subs: int) -> bool:
    """대역량 커버리지 50% 미만 → '참고치' 배지."""
    if total_subs <= 0:
        return True
    return (measured_subs / total_subs) < 0.50
