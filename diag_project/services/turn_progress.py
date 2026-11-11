"""(2026-11-11 단계 표시) 코치 턴 진행 단계 — 세션별 in-memory.

한 턴은 슬롯 판정 → (사례 종료 시 매핑) → 코치 본 호출 → 후처리로 3~10초가 걸린다. 프론트가 점 세 개만 보여 주던 대기를
단계 문구로 바꾸기 위해, 턴 핸들러가 단계가 바뀔 때마다 여기에 적고 GET /diagnoses/{sid}/turn_stage 가 읽는다.

  reading    답을 읽는 중      — 턴 시작 ~ 코치 본 호출 직전(슬롯 판정·매핑)
  thinking   질문을 고르는 중  — 코치 본 호출(여는 문장 렌더와 병렬)
  polishing  문장을 다듬는 중  — 후처리(검사·수선·재생성 1회)
  idle       돌고 있는 턴 없음

analysis_progress 와 같은 방식(프로세스 메모리, Render 단일 인스턴스). 재시작하면 사라지고 프론트는 점만 보인다. 대화 내용·점수에는 관여하지 않는다.
"""
from __future__ import annotations

import time
from typing import Any, Dict

STAGES = ("reading", "thinking", "polishing")
STAGE_LABELS = {"reading": "답변을 읽고 있어요", "thinking": "질문을 고르고 있어요", "polishing": "문장을 다듬고 있어요", "idle": ""}
_TTL_S = 120.0          # 끝났는데 clear 가 안 불린 기록(예외 경로)은 2분 뒤 버린다
_STATE: Dict[str, Dict[str, Any]] = {}


def _gc(now: float) -> None:
    for sid in [s for s, v in _STATE.items() if now - v.get("t0", now) > _TTL_S]:
        _STATE.pop(sid, None)


def start(session_id: str) -> None:
    now = time.monotonic()
    _gc(now)
    _STATE[str(session_id)] = {"stage": "reading", "t0": now, "t_stage": now}


def set_stage(session_id: str, stage: str) -> None:
    st = _STATE.get(str(session_id))
    if st is None or stage not in STAGES:
        return
    if STAGES.index(stage) >= STAGES.index(st["stage"]):       # 단계는 앞으로만 간다
        st["stage"] = stage
        st["t_stage"] = time.monotonic()


def clear(session_id: str) -> None:
    _STATE.pop(str(session_id), None)


def get_stage(session_id: str) -> Dict[str, Any]:
    st = _STATE.get(str(session_id))
    now = time.monotonic()
    if st is None or now - st["t0"] > _TTL_S:
        return {"stage": "idle", "label": "", "elapsed_s": 0.0}
    return {"stage": st["stage"], "label": STAGE_LABELS[st["stage"]], "elapsed_s": round(now - st["t0"], 1)}
