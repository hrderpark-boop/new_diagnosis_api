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

    # 4. CORS 설정
    # 프로덕션에서는 환경변수로 덮어쓸 것:
    #   CORS_ALLOWED_ORIGINS="https://app.example.com,https://admin.example.com"
    CORS_ALLOWED_ORIGINS: List[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
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