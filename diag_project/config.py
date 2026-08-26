# diag_project/config.py
# diag_project/config.py

import logging
import os
from pydantic_settings import BaseSettings
from pydantic import ConfigDict
from typing import List

# (참고) .env 파일이 있다면 여기서 로드합니다.
# from dotenv import load_dotenv
# load_dotenv()

class Settings(BaseSettings):
    PROJECT_NAME: str = "My Diagnosis API"
    
    # 1. (C-3 인증) 보안 설정
    SECRET_KEY: str = os.getenv("SECRET_KEY", "default_super_secret_key_for_dev")
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


def phase3a_enabled() -> bool:
    """USE_PHASE3A 를 '느슨하게' 파싱한다(공백·따옴표·1/yes/on 허용).

    기존 `.lower()=="true"` 는 " true "·'"true"'·"1" 에서 조용히 false 로 떨어져
    레거시 흐름으로 새는 함정이 있었다(품질 시스템 통째 OFF). 이 함수로 통일한다.
    """
    raw = os.getenv("USE_PHASE3A", "false")
    return raw.strip().strip('"').strip("'").lower() in {"true", "1", "yes", "on"}