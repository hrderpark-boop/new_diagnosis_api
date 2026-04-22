# diag_project/main.py

import logging
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles # ✅ 이미지 서빙을 위해 필요

from diag_project.database import init_db
# ✅ [수정] coaches 모듈을 반드시 포함해야 합니다.
from diag_project.routes import diagnoses, reports, participants, coaches 
from diag_project.config import settings

# 로깅 설정
logging.basicConfig(
    level=logging.INFO,
    format="%(levelname)s:     %(message)s",
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Diagnosis API",
    version="1.0.0"
)

# CORS 설정
# allow_credentials=True를 쓸 때는 allow_origins=["*"]가 스펙 위반이므로
# config.py의 명시적 목록을 사용한다.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------------------------------
# ✅ [신규] 이미지 파일 서빙 설정 (images 폴더를 /coaches 주소로 연결)
# --------------------------------------------------------------------------
# 프로젝트 루트에 'images' 라는 폴더가 있어야 작동합니다.
# 만약 폴더명이 다르다면 directory="폴더명"을 수정해주세요.
if os.path.exists("images"):
    app.mount("/coaches", StaticFiles(directory="images"), name="coaches")
else:
    logger.warning("⚠️ 'images' folder not found. Coach avatars might not load.")


@app.on_event("startup")
async def on_startup():
    logger.info("🚀 Application startup: Initializing database...")
    await init_db()
    logger.info("✅ Database initialized.")

@app.on_event("shutdown")
async def on_shutdown():
    logger.info("👋 Application shutdown: Closing database connection...")

# --------------------------------------------------------------------------
# ✅ 라우터 등록 (이 부분이 있어야 404 에러가 사라집니다)
# --------------------------------------------------------------------------
app.include_router(participants.router, prefix="/api/v1/participants") 
app.include_router(coaches.router, prefix="/api/v1/coaches")           # 👈 코치 목록 담당 (필수!)
app.include_router(diagnoses.router, prefix="/api/v1/diagnoses")       
app.include_router(reports.router, prefix="/api/v1/reports")           

# 헬스 체크
@app.get("/")
async def root():
    return {"message": "Diagnosis API is running"}