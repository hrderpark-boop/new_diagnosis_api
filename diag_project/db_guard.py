"""운영 DB 가드 (2026-10-19) — 앱 기동 시 로컬 환경이 운영 Supabase 를 가리키면 기동을 거부한다.

배경: 로컬 .env 의 DATABASE_URL 이 운영 Supabase 였고, 로컬 서버·도구가 그대로 운영에 붙을 수 있었다.
pytest 는 conftest 가 같은 가드를 하지만 앱 기동에는 없었다.

규칙
  · 운영(ENV=production, 또는 Render 가 자동 주입하는 RENDER=true)이면 통과.
  · 그 외 환경에서 DATABASE_URL 호스트가 supabase 를 가리키면 RuntimeError. ALLOW_PROD_DB=1 일 때만 예외.
  · sqlite·localhost·그 밖의 호스트(복제 DB 등)는 막지 않는다.
로그에는 비밀번호를 절대 남기지 않는다(mask_db_url: scheme·host·port·db 이름만).
"""
from __future__ import annotations

import os
from typing import Mapping
from urllib.parse import urlsplit

PROD_DB_HOST_MARKERS = ("supabase.co", "supabase.com", "supabase.in")


def mask_db_url(url: str | None) -> str:
    """자격증명을 뺀 접속 문자열. 예) postgresql+asyncpg://***@aws-1.pooler.supabase.com:6543/postgres"""
    if not url:
        return "(unset)"
    if url.startswith("sqlite"):
        return url
    try:
        u = urlsplit(url)
    except ValueError:
        return "(unparseable)"
    host = u.hostname or "?"
    port = f":{u.port}" if u.port else ""
    cred = "***@" if u.username or u.password else ""
    return f"{u.scheme}://{cred}{host}{port}{u.path or ''}"


def is_production_env(env: Mapping[str, str] | None = None) -> bool:
    env = os.environ if env is None else env
    if (env.get("ENV") or "").strip().lower() in ("production", "prod"):
        return True
    # Render 는 모든 서비스에 RENDER=true 를 자동 주입한다 — ENV 를 아직 안 넣은 배포가 기동 거부되지 않게 하는 폴백.
    return (env.get("RENDER") or "").strip().lower() in ("true", "1")


def is_prod_db_url(url: str | None) -> bool:
    if not url or url.startswith("sqlite"):
        return False
    try:
        host = (urlsplit(url).hostname or "").lower()
    except ValueError:
        host = url.lower()
    return any(m in host for m in PROD_DB_HOST_MARKERS)


def check_db_allowed(url: str | None, env: Mapping[str, str] | None = None) -> None:
    """운영 DB 를 비운영 환경에서 열려 하면 RuntimeError. 통과하면 None."""
    env = os.environ if env is None else env
    if not is_prod_db_url(url):
        return
    if is_production_env(env):
        return
    if (env.get("ALLOW_PROD_DB") or "").strip() == "1":
        return
    raise RuntimeError(
        f"DATABASE_URL 이 운영 DB({mask_db_url(url)})를 가리키는데 ENV=production 이 아닙니다. "
        "로컬에서는 sqlite(또는 복제 DB)를 쓰세요. 정말 운영 DB 가 필요하면 ALLOW_PROD_DB=1 을 명시하세요."
    )
