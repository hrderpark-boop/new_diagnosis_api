import os
import logging
from sqlmodel import SQLModel
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv

# [매우 중요] DB 테이블 생성 전에 모든 모델을 미리 Import 해야 합니다.
from diag_project.models.group import Group
from diag_project.models.participant import Participant
from diag_project.models.coach import Coach
from diag_project.models.coach_persona import CoachPersona
from diag_project.models.competency_indicator import Competency, Indicator
from diag_project.models.question_category import QuestionCategory
from diag_project.models.diagnosis_template import DiagnosisTemplate
from diag_project.models.diagnosis_question import DiagnosisQuestion
from diag_project.models.diagnosis_session import DiagnosisSession, ChatMessage
from diag_project.models.diagnosis_report import DiagnosisReport
from diag_project.models.event import Event

load_dotenv()

# 로깅 설정
logger = logging.getLogger(__name__)

# 1. DB URL 설정 (파일로 저장되도록 설정)
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./sql_app.db")

# 2. 비동기 엔진 생성
engine = create_async_engine(
    DATABASE_URL,
    echo=False, 
    future=True,
    connect_args={"check_same_thread": False} if "sqlite" in DATABASE_URL else {}
)

# 3. 세션 팩토리
async_session = sessionmaker(
    engine, class_=AsyncSession, expire_on_commit=False
)

# 4. DB 의존성 주입 함수
async def get_db():
    async with async_session() as session:
        yield session

# 5. DB 초기화 함수 (테이블 생성)
async def init_db():
    async with engine.begin() as conn:
        # ⚠️ [주의] 데이터 보존을 위해 drop_all은 주석 처리 유지
        # await conn.run_sync(SQLModel.metadata.drop_all)
        
        # 테이블 생성
        await conn.run_sync(SQLModel.metadata.create_all)

        # 경량 마이그레이션: 기존 events 테이블에 신규 컬럼이 없으면 추가.
        # (create_all 은 기존 테이블에 컬럼을 추가하지 않으므로 방어적으로 처리)
        try:
            from sqlalchemy import text
            await conn.execute(text(
                "ALTER TABLE events ADD COLUMN mapped_subcompetency VARCHAR(100)"
            ))
            logger.info("✅ events.mapped_subcompetency 컬럼 추가됨")
        except Exception:
            # 이미 존재하면 무시
            pass

    logger.info(f"✅ Database initialized at: {DATABASE_URL}")