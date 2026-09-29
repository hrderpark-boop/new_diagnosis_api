"""리포트 분석(analyze) 진행 상태 — 세션별 in-memory.

분석은 LLM ~33콜(outer 3 × (심층 5 + 게이트 ≤5) + 종합 + D게이트)이라 수 분이
걸린다. 프론트가 스피너만 보여 '멈춘 것처럼' 보이던 문제를 풀기 위해, 단계마다
상태를 갱신하고 GET /reports/{sid}/progress 로 노출한다.

  stage: queued → analyze(영역 분석) → summary(종합 정리) → recommend(추천 생성)
         → saving → done | failed
  analyze 단계의 done/total 은 '5개 영역 중 outer run 전부(심층+게이트)를 마친
  영역 수'. 교차검증(outer) 완료 수는 outer_done/outer_total 로 따로 준다.

프로세스 메모리(Render 단일 인스턴스)라 재시작하면 사라진다 — 그때 progress 는
404 이고 프론트는 기존 리포트 폴링으로 폴백한다. 점수·저장에는 관여하지 않는다.
"""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

_TTL_S = 3600  # 끝난 상태는 1시간 뒤 정리
_STATE: Dict[str, Dict[str, Any]] = {}

STAGE_LABELS = {
    "queued": "분석 준비 중",
    "summary": "종합 정리 중",
    "recommend": "추천 생성 중",
    "saving": "리포트 저장 중",
    "done": "분석 완료",
    "failed": "분석 실패",
}


def _gc(now: float) -> None:
    for sid in [s for s, v in _STATE.items()
                if v.get("_ended") and now - v["_ended"] > _TTL_S]:
        _STATE.pop(sid, None)


def _analyze_label(st: Dict[str, Any]) -> str:
    lbl = f"{st['n_comp']}개 영역 분석 중 {st['done']}/{st['n_comp']}"
    if st["n_outer"] > 1:
        lbl += f" · 교차검증 {st['outer_done']}/{st['n_outer']}"
    return lbl


class AnalysisProgress:
    """한 세션의 분석 진행 기록기. 파이프라인은 이 객체만 호출한다(세션 모름)."""

    def __init__(self, session_id: str, competency_keys, n_outer: int,
                 names: Optional[Dict[str, str]] = None):
        self.sid = str(session_id)
        self.keys = list(competency_keys)
        now = time.monotonic()
        _gc(now)
        self._units: Dict[str, set] = {k: set() for k in self.keys}
        self._outer: Dict[int, set] = {o: set() for o in range(n_outer)}
        _STATE[self.sid] = {
            "stage": "queued", "done": 0, "total": len(self.keys),
            "label": STAGE_LABELS["queued"],
            "started_at": datetime.now(timezone.utc).isoformat(
                timespec="seconds"),
            "n_comp": len(self.keys), "n_outer": n_outer,
            "outer_done": 0, "outer_total": n_outer,
            "error": None, "_t0": now, "_ended": None,
            "_keys": self.keys, "_names": dict(names or {}),
            "_units": self._units, "_deep": {k: set() for k in self.keys},
        }

    @property
    def _st(self) -> Dict[str, Any]:
        return _STATE[self.sid]

    def start_analyze(self) -> None:
        st = self._st
        st.update(stage="analyze", done=0, total=st["n_comp"])
        st["label"] = _analyze_label(st)

    def deep_done(self, competency_key: str, outer_idx: int) -> None:
        """(대역량, outer) 심층분석이 끝났다(게이트 전) — 진행률(percent)용."""
        self._st["_deep"].setdefault(competency_key, set()).add(outer_idx)

    def unit_done(self, competency_key: str, outer_idx: int) -> None:
        """(대역량, outer run) 한 단위(심층분석+게이트)가 끝났다."""
        st = self._st
        self._units.setdefault(competency_key, set()).add(outer_idx)
        self._outer.setdefault(outer_idx, set()).add(competency_key)
        st["done"] = sum(1 for k in self.keys
                         if len(self._units.get(k, ())) >= st["n_outer"])
        st["outer_done"] = sum(1 for o in range(st["n_outer"])
                               if len(self._outer.get(o, ())) >= st["n_comp"])
        st["label"] = _analyze_label(st)

    def stage(self, stage: str, label: Optional[str] = None,
              done: int = 0, total: int = 1) -> None:
        st = self._st
        st.update(stage=stage, done=done, total=total,
                  label=label or STAGE_LABELS.get(stage, stage))
        if stage in ("done", "failed"):
            st["_ended"] = time.monotonic()

    def fail(self, error: str) -> None:
        self.stage("failed")
        self._st["error"] = (error or "")[:200]


def start(session_id: str, competency_keys, n_outer: int,
          names: Optional[Dict[str, str]] = None) -> AnalysisProgress:
    return AnalysisProgress(session_id, competency_keys, n_outer, names)


# 전체 진행률(percent) 가중치 — 실측 비중(심층+게이트 ~77%, 종합‖추천 ~23%).
_PCT_ANALYZE_END = 78
_PCT_STAGE_START = {"queued": 0, "summary": 80, "recommend": 94,
                    "saving": 98, "done": 100}


def _chapters(st: Dict[str, Any]) -> list:
    """챕터별 상태: done(outer 전부 심층+게이트 완료) / running / pending."""
    stage = st["stage"]
    out = []
    for k in st["_keys"]:
        n = len(st["_units"].get(k, ()))
        if n >= st["n_outer"]:
            status = "done"
        elif stage == "queued" or (stage == "failed" and n == 0):
            status = "pending"
        elif stage == "failed":
            status = "failed"
        else:
            status = "running"
        out.append({"key": k, "name": st["_names"].get(k, k),
                    "status": status, "units_done": n,
                    "units_total": st["n_outer"]})
    return out


def _percent(st: Dict[str, Any]) -> int:
    stage = st["stage"]
    if stage == "analyze" or (stage == "failed" and st["_units"]):
        n_units = len(st["_keys"]) * st["n_outer"] or 1
        deep = sum(len(v) for v in st["_deep"].values())
        units = sum(len(v) for v in st["_units"].values())
        # 한 단위 = 심층(60%) → 게이트(40%)
        frac = (0.6 * deep + 0.4 * units) / n_units
        return int(min(_PCT_ANALYZE_END, round(frac * _PCT_ANALYZE_END)))
    return _PCT_STAGE_START.get(stage, 0)


def get(session_id: str) -> Optional[Dict[str, Any]]:
    """공개 스냅샷 {stage, done, total, label, started_at, elapsed_s,
    percent, chapters:[{key,name,status}], summary_status, ...}."""
    st = _STATE.get(str(session_id))
    if st is None:
        return None
    end = st["_ended"] or time.monotonic()
    out = {k: v for k, v in st.items() if not k.startswith("_")}
    out["elapsed_s"] = round(end - st["_t0"], 1)
    out["percent"] = _percent(st)
    out["chapters"] = _chapters(st)
    stage = st["stage"]
    out["summary_status"] = (
        "done" if stage in ("saving", "done") else
        "running" if stage in ("summary", "recommend") else
        "failed" if stage == "failed" else "pending")
    return out


def is_running(session_id: str) -> bool:
    st = _STATE.get(str(session_id))
    return bool(st) and st["stage"] not in ("done", "failed")
