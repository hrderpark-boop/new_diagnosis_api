"""§3: 분석 결과 영속 캐시 (재분석 비용 절감의 핵심).

로직(추천·리포트 렌더링)만 고쳤을 때 LLM 호출이 0이 되도록, evidence 추출과
게이트 판정 결과를 파일에 영속 캐싱한다. 키에 prompt_version 을 포함하므로
프롬프트가 바뀌면 자동으로 캐시가 무효화된다(버전 미변경 호출만 캐시 반환).

  · evidence/분석 캐시 키: (transcript_hash, competency_key, prompt_version)
  · 게이트 캐시 키       : (evidence_hash, sub_key, level, prompt_version)

환경변수:
  ANALYSIS_CACHE_DIR      캐시 디렉터리(기본 .analysis_cache)
  ANALYSIS_CACHE_ENABLED  "0" 이면 비활성(A/B 등 신선 호출이 필요할 때)
"""
import hashlib
import json
import logging
import os
import threading

logger = logging.getLogger(__name__)

_CACHE_DIR = os.getenv("ANALYSIS_CACHE_DIR", ".analysis_cache")
_LOCK = threading.Lock()
_HITS = {"hit": 0, "miss": 0}


def enabled() -> bool:
    return os.getenv("ANALYSIS_CACHE_ENABLED", "1") != "0"


def make_key(*parts) -> str:
    raw = "|".join("" if p is None else str(p) for p in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _path(namespace: str) -> str:
    return os.path.join(_CACHE_DIR, f"{namespace}.json")


def _load(namespace: str) -> dict:
    try:
        with open(_path(namespace), encoding="utf-8") as f:
            return json.load(f)
    except Exception:  # noqa: BLE001 — 없거나 깨졌으면 빈 캐시
        return {}


def get(namespace: str, key: str):
    if not enabled():
        return None
    v = _load(namespace).get(key)
    _HITS["hit" if v is not None else "miss"] += 1
    return v


def set(namespace: str, key: str, value) -> None:  # noqa: A001
    if not enabled():
        return
    with _LOCK:
        os.makedirs(_CACHE_DIR, exist_ok=True)
        d = _load(namespace)
        d[key] = value
        tmp = _path(namespace) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False)
        os.replace(tmp, _path(namespace))  # 원자적 교체(프로세스 재시작에 견딤)


def stats() -> dict:
    return dict(_HITS)


def reset_stats() -> None:
    _HITS["hit"] = 0
    _HITS["miss"] = 0
