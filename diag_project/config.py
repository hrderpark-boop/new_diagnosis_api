# diag_project/config.py
# diag_project/config.py

import logging
import os
from dotenv import load_dotenv
from pydantic_settings import BaseSettings
from pydantic import ConfigDict
from typing import List

# 로컬 .env 를 import 시점에 로드한다(운영은 Render Environment 가 주입).
#   database.py 도 로드하지만, 모듈 import 순서에 따라 이 파일이 먼저 평가될 수
#   있어 SECRET_KEY 가 빈 값으로 굳는 것을 막는다(멱등 호출).
load_dotenv()

# 🔒 C1: 과거 개발 기본값. 이 값(또는 빈 값)으로는 절대 기동/서명하지 않는다 —
#   기본값이 살아 있으면 어드민 JWT(HS256)를 누구나 위조할 수 있다.
_INSECURE_SECRET_KEYS = {"", "default_super_secret_key_for_dev"}


class Settings(BaseSettings):
    PROJECT_NAME: str = "My Diagnosis API"

    # 1. (C-3 인증) 보안 설정 — 기본값 없음. 반드시 환경변수로 주입(openssl rand -hex 32).
    SECRET_KEY: str = os.getenv("SECRET_KEY", "")
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24 # 1일

    # 2. 비동기 DB URL
    ASYNC_DATABASE_URL: str = "sqlite+aiosqlite:///./sql_app.db"
    
    # 3. DB 로깅 설정 (False로 유지)
    DB_ECHO: bool = False 

    # 4. CORS 설정 — 화이트리스트 (여기 없는 origin 은 브라우저 접근 차단)
    # 공식 프론트엔드 도메인 + 로컬 개발용, 딱 두 곳만 허용.
    # 필요 시 환경변수로 덮어쓸 것:
    #   CORS_ALLOWED_ORIGINS="https://app.example.com,https://admin.example.com"
    CORS_ALLOWED_ORIGINS: List[str] = [
        "https://fm.connectn.co.kr",
        "http://localhost:3000",
    ]
    
    # 5. 💡 (C-4 LLM) Gemini API 설정 추가
    # .env 파일에 GEMINI_API_KEY=... 를 추가해야 합니다.
    # (Canvas 환경에서는 자동으로 키가 주입됩니다)
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "") 
    GEMINI_MODEL_NAME: str = "gemini-3.5-flash"

    model_config = ConfigDict(
        case_sensitive=True
        # env_file = ".env"
    )

settings = Settings()


def require_secret_key() -> str:
    """SECRET_KEY 가 운영에 쓸 수 있는 값인지 검증하고 반환한다.

    미설정/개발 기본값이면 RuntimeError — 앱 기동(main.on_startup)과 JWT
    서명·검증(services/auth) 양쪽에서 호출해 fail-closed 로 막는다.
    Render 에 SECRET_KEY 가 없으면 기동 자체가 실패하도록 의도된 동작이다.
    """
    key = (settings.SECRET_KEY or "").strip()
    if key in _INSECURE_SECRET_KEYS:
        raise RuntimeError(
            "SECRET_KEY 환경변수가 설정되지 않았거나 개발 기본값입니다. "
            "`openssl rand -hex 32` 로 생성해 Render Environment(또는 로컬 .env)에 "
            "SECRET_KEY 로 등록한 뒤 재기동하세요."
        )
    return key


def phase3a_enabled() -> bool:
    """USE_PHASE3A 를 '느슨하게' 파싱한다(공백·따옴표·1/yes/on 허용).

    기존 `.lower()=="true"` 는 " true "·'"true"'·"1" 에서 조용히 false 로 떨어져
    레거시 흐름으로 새는 함정이 있었다(품질 시스템 통째 OFF). 이 함수로 통일한다.
    """
    # M14: 기본값 true. 환경변수 누락 한 번으로 품질 시스템(제어역전·넓이게이트)
    #   전체가 조용히 레거시로 꺼지는 사고가 실제로 있었다. 레거시는 명시적으로
    #   USE_PHASE3A=false 를 줄 때만 쓴다.
    raw = os.getenv("USE_PHASE3A", "true")
    return raw.strip().strip('"').strip("'").lower() in {"true", "1", "yes", "on"}