"""A-2/A-4: 챕터 종료 사전분석(prewarm) + 리포트 준비 시간(ETA).

리포트 분석은 (대역량 5 × outer 3) 심층분석 + 레벨 게이트 + 종합·추천이다.
챕터 X 가 끝나는 순간 X 의 입력(챕터 발언·사건, X 끝까지의 대화, 질문된 하위역량)
은 더 바뀌지 않으므로, 그때 X 의 심층분석·게이트를 미리 돌려 analysis_cache 에
채워 두면 완료 시 analyze 는 같은 캐시 키로 0콜 재사용한다.

  · 입력이 바뀌면(재개 후 X 챕터에 메시지가 추가되는 등) 키가 달라져 자동으로
    재분석된다 — 틀린 결과를 재사용하지 않는다.
  · 실패(크레딧 소진·LLM 오류)는 캐시에 남지 않고 WARNING 로그만 — 완료 시
    analyze 가 평소대로 다시 부른다.
  · analyze 가 사전분석 진행 중인 키를 만나면 다시 부르지 않고 그 결과를
    기다린다(llm_service._DEEP_INFLIGHT, level_gate._INFLIGHT).

호출(대화 흐름 쪽, 턴 커밋 이후):
    from diag_project.services.report_prewarm import schedule_chapter_prewarm
    schedule_chapter_prewarm(session_id, chapter_key)   # fire-and-forget
"""
from __future__ import annotations

import asyncio
import logging
import math
import time
import uuid
from typing import Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

# (session_id, chapter) → 시작 시각(monotonic). 중복 실행 방지 + ETA 계산용.
_RUNNING: Dict[Tuple[str, str], float] = {}
# create_task 결과를 붙잡아 둔다(참조가 없으면 실행 중 GC 될 수 있다).
_TASKS: Set[asyncio.Task] = set()

# ── ETA 보정값(2026-09-29 실측, 세션 420f1341, 231 메시지, gemini-2.5-pro,
#    동시 상한 15) ──
#   미캐시 5챕터: 115s (심층+게이트 88s + 종합‖추천 26s)
#   미캐시 1챕터(4챕터 사전분석): 91s (심층+게이트 62s + 종합‖추천 30s)
#   전부 사전분석: 24.5s (종합‖추천만, 2콜)
#   마지막 챕터 사전분석 30s 진행 중 합류: 55s (중복 호출 없음)
#   챕터 1개 사전분석(심층 3 → 게이트) 자체는 55~65s.
ETA_MAP_BASE_S = 55     # 남은 챕터의 심층+게이트 한 파(병렬) 기본
ETA_MAP_PER_CH_S = 8    # 챕터가 늘 때마다(동시 호출 꼬리) 추가
ETA_PREWARM_S = 60      # 진행 중 사전분석 한 챕터의 총 소요
ETA_TAIL_S = 28         # 종합 요약 ‖ 추천(D게이트) + 저장
N_CHAPTERS = 5


def estimate_seconds(remaining_chapters: int,
                     inflight_elapsed: Optional[List[float]] = None) -> int:
    """남은(미캐시·미진행) 챕터 수와 사전분석 진행 중 챕터들의 경과초 → ETA(초)."""
    from diag_project.llm_service import (
        _ANALYSIS_CONCURRENCY, _ANALYSIS_OUTER_RUNS,
    )
    m = max(0, int(remaining_chapters))
    map_s = 0.0
    if m:
        waves = math.ceil(m * _ANALYSIS_OUTER_RUNS / max(1, _ANALYSIS_CONCURRENCY))
        map_s = (ETA_MAP_BASE_S + ETA_MAP_PER_CH_S * m) * waves
    for el in inflight_elapsed or []:
        map_s = max(map_s, max(5.0, ETA_PREWARM_S - el))
    return int(round(map_s + ETA_TAIL_S))


def _label(seconds: int) -> str:
    if seconds <= 45:
        return "1분 이내"
    return f"약 {max(1, round(seconds / 60))}분"


def estimate_label(cached_chapters: int) -> str:
    """순수 함수: 사전분석이 끝난 챕터 수 → '약 N분' / '1분 이내'.

    (대화 마무리 문구 등에서 재사용) 진행 중 사전분석은 모르므로 보수적이다.
    """
    cached = max(0, min(N_CHAPTERS, int(cached_chapters)))
    return _label(estimate_seconds(N_CHAPTERS - cached))


async def prewarm_chapter_analysis(session_id: str, chapter: str) -> None:
    """챕터 하나의 심층분석(outer 전부) + 레벨 게이트를 미리 돌려 캐시에 채운다.

    자체 DB 세션(async_session)으로 '읽기만' 한다. 모든 예외를 삼킨다(WARNING).
    fire-and-forget 태스크로 안전 — 호출부를 막거나 깨뜨리지 않는다.
    """
    key = (str(session_id), str(chapter))
    if key in _RUNNING:
        return
    _RUNNING[key] = time.monotonic()
    t0 = time.monotonic()
    try:
        from diag_project.llm_service import GeminiService, _get_competency_keys
        if chapter not in _get_competency_keys():
            logger.warning("사전분석 스킵 — 알 수 없는 챕터 %r (session=%s)",
                           chapter, session_id)
            return
        from diag_project.database import async_session
        from diag_project.models.diagnosis_session import DiagnosisSession
        from diag_project.routes.reports import load_analysis_inputs
        async with async_session() as db:
            session = await db.get(DiagnosisSession, uuid.UUID(str(session_id)))
            if session is None:
                logger.warning("사전분석 스킵 — 세션 없음 %s", session_id)
                return
            inp = await load_analysis_inputs(db, session)
        llm = GeminiService()
        # 이미 캐시돼 있으면 심층·게이트 모두 캐시 적중이라 0콜로 끝난다.
        await llm.prewarm_chapter(
            inp["history"], inp["chapter_transcripts"], inp["asked_subs"],
            chapter, role_summary=inp["role_summary"])
        logger.info("🔥 사전분석 완료 [%s·%s] %.1fs", session_id, chapter,
                    time.monotonic() - t0)
    except asyncio.CancelledError:
        logger.warning("사전분석 취소 [%s·%s]", session_id, chapter)
    except Exception as e:  # noqa: BLE001 — 사전분석 실패는 조용히(완료 시 재시도)
        logger.warning("사전분석 실패(무시, 완료 시 재분석) [%s·%s]: %s: %s",
                       session_id, chapter, type(e).__name__, str(e)[:200])
    finally:
        _RUNNING.pop(key, None)


def schedule_chapter_prewarm(session_id: str, chapter: str) -> Optional[asyncio.Task]:
    """prewarm_chapter_analysis 를 백그라운드 태스크로 띄운다(참조 보관).

    실행 중인 이벤트 루프가 없으면 None(아무것도 안 함). 예외를 던지지 않는다.
    """
    try:
        task = asyncio.get_running_loop().create_task(
            prewarm_chapter_analysis(str(session_id), str(chapter)))
    except Exception as e:  # noqa: BLE001
        logger.warning("사전분석 예약 실패(무시) [%s·%s]: %s", session_id, chapter, e)
        return None
    _TASKS.add(task)
    task.add_done_callback(_TASKS.discard)
    return task


def inflight_elapsed(session_id: str) -> Dict[str, float]:
    """이 세션에서 사전분석 진행 중인 챕터 → 경과초."""
    now = time.monotonic()
    return {ch: now - t for (sid, ch), t in list(_RUNNING.items())
            if sid == str(session_id)}
