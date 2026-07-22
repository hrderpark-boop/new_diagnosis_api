# diag_project/main.py

import logging
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles # ✅ 이미지 서빙을 위해 필요

# ✅ [중요] 모든 ORM 모델을 미리 로드해 SQLAlchemy 매퍼가 한 번에 평가되도록 한다.
# (Participant 등 일부 모델이 Relationship("EvaluationResult") 처럼 '문자열'로
#  다른 모델을 참조하므로, 해당 모델 모듈이 import 되어 있지 않으면 런타임에
#  'failed to locate a name' 에러가 난다.)
import diag_project.models  # noqa: F401

from diag_project.database import init_db
# ✅ [수정] coaches 모듈을 반드시 포함해야 합니다.
from diag_project.routes import diagnoses, reports, participants, coaches
from diag_project.routes import framework
from diag_project.routes import admin
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

# CORS 설정 — 화이트리스트만 허용 (와일드카드 금지)
# config.py 의 CORS_ALLOWED_ORIGINS: 공식 프론트 도메인 + 로컬 개발용 두 곳.
# 명시적 origin 목록이므로 allow_credentials=True 도 스펙상 안전.
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
app.include_router(coaches.router, prefix="/api/v1/coaches")
app.include_router(diagnoses.router, prefix="/api/v1/diagnoses")
app.include_router(reports.router, prefix="/api/v1/reports")
app.include_router(framework.router, prefix="/api/v1/framework")
# 어드민(RBAC): 라우터 자체가 prefix="/admin" 을 갖고 있어 최종 경로는
# /api/v1/admin/... 이 된다. 모든 엔드포인트는 JWT 인증을 요구한다.
app.include_router(admin.router, prefix="/api/v1")

# 헬스 체크
@app.get("/")
async def root():
    return {"message": "Diagnosis API is running"}