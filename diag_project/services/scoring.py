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


def is_measured(asked: bool, evidence_count: int) -> bool:
    """측정 판정 — 단일 진실 함수 (T1 유령 측정 방지).

    measured = asked(앵커가 실제 발화됨) AND evidence_count >= 1.
    🚨 asked 와 evidence 는 '서로 독립'이어야 한다. asked 를 evidence 에서
    파생시키면(예: asked = ... or evidence>=1) AND 게이트가 붕괴해 유령 측정이
    발생한다. LLM 의 measured 응답은 신뢰하지 않고, 코드가 asked 를 확인한다.
    """
    return bool(asked) and int(evidence_count or 0) >= 1


@dataclass
class SubLedger:
    """하위역량 증거 원장 (P0-1)."""
    name: str
    asked: bool = False
    evidence_utterances: list[str] = field(default_factory=list)
    level: int | None = None  # LLM 레벨 판정 1~4

    @property
    def measured(self) -> bool:
        return is_measured(self.asked, len(self.evidence_utterances))

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


def score_shutdown(none_competencies: int, measured_total: int,
                   subs_total: int = 26) -> bool:
    """T4(레거시): 종합 점수 셧다운 — 절대 측정 수 기준.
      ① 대역량 3개 이상 미측정(None)  ② 전체 측정률 40% 미만(measured<11/26)

    ⚠️ V-6: 절대값(measured<11) 기준은 경계에서 불안정하다 — 동일 대상자
    반복 진단에서 measured 5~14 로 흔들려 정식/부분 리포트가 오락가락한다.
    신규 경로는 score_suppressed_structural 을 쓴다(이 함수는 회귀 보존용).
    """
    if none_competencies >= 3:
        return True
    threshold = subs_total * 0.40  # 26*0.4 = 10.4 → measured<11
    return measured_total < threshold


# V-6: 구조적 셧다운 기준 — 절대 측정 수가 아니라 '깊이+분산'으로 판정.
#   정식 발행(종합점수 산출)은 '대역량 MIN_QUAL_COMPS 개 이상에서 각
#   MIN_PER_COMP 건 이상 measured' 일 때만. 개별 하위역량의 drop↔Lv.1 변동
#   (±1~2건)에 흔들리지 않는다. 김보통 3회 실측: 자격 대역량 1·2·5 →
#   경계(3)에서 넓은 간격 → 반복 진단 간 안정.
#   🚨 임계를 '낮춰' 정식 발행을 늘리는 방향이 아니다 — 산발적 measured
#   (대역량당 1건)로는 정식 발행되지 않도록 오히려 구조를 요구한다.
MIN_QUAL_COMPS = 3   # 정식 발행에 필요한 '자격 대역량' 최소 수
MIN_PER_COMP = 2     # 자격 대역량이 되려면 대역량당 measured 최소 건수


def score_suppressed_structural(comp_measured_counts: list[int],
                                min_qual_comps: int = MIN_QUAL_COMPS,
                                min_per_comp: int = MIN_PER_COMP) -> bool:
    """[레거시/회귀 보존] 자격 대역량(measured ≥ min_per_comp) 이 min_qual_comps
    개 미만이면 True. V-6(1) 로 발행 게이트에서 물러남 — qualifying 임계(3)가
    실측 분포(2~3) 한복판이라 경계에서 진동. 신규 경로는 measured_total 기반
    composite_shown 을 쓴다. 이 함수는 단위 테스트 회귀 보존용으로만 남긴다.

    comp_measured_counts: 대역량별 measured 하위역량 수 리스트.
    """
    qualifying = sum(1 for c in (comp_measured_counts or []) if c >= min_per_comp)
    return qualifying < min_qual_comps


# V-6(1): 종합 섹션(종합점수·레이더·상대비교) 표시 게이트.
#   qualifying 임계(0~5, 경계 2~3에서 진동) 대신 measured_total(0~26, 전형
#   분포 8~12에서 임계 18까지 넉넉)로 판정 → 전형 세션은 임계 근처에 없어
#   경계 뒤집힘이 구조적으로 소멸. 종합점수는 '넓은 커버리지'에서만 유효하다는
#   측정 무결성과도 부합(측정 10/26로 낸 평균을 26 종합처럼 오해시키지 않는다).
#   🚨 임계 18 은 김보통 flat 프로파일 하나로 정한 '잠정값' — 파일럿의 measured
#      분포로 확정한다. env(COMPOSITE_MIN_MEASURED)로 오버라이드.
import os as _os  # noqa: E402

COMPOSITE_MIN_MEASURED = int(_os.getenv("COMPOSITE_MIN_MEASURED", "18"))


def composite_shown(measured_total: int,
                    threshold: int = COMPOSITE_MIN_MEASURED) -> bool:
    """종합 섹션을 표시할지 — measured_total ≥ threshold 일 때만 True.

    False 여도 '실패/미달'이 아니라 '확인된 근거 중심 리포트'가 기본 출력이다.
    """
    return int(measured_total or 0) >= threshold
