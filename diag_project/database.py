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

# 1. DB URL 설정 — 보안상 코드에 하드코딩 금지. .env 의 DATABASE_URL 사용.
DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError(
        "DATABASE_URL 환경 변수가 설정되지 않았습니다. "
        ".env 파일에 DATABASE_URL=... 을 추가하세요."
    )
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

# 경량 마이그레이션 대상: create_all 은 '기존 테이블'에 컬럼을 추가하지
# 않으므로, 모델에 새 컬럼을 더할 때는 여기 등록해 방어적으로 ALTER 한다.
_LIGHT_MIGRATIONS = [
    "ALTER TABLE events ADD COLUMN mapped_subcompetency VARCHAR(100)",
    # ML 학습(Fine-Tuning) 대비: user/model 메시지 페어링용 턴 번호
    "ALTER TABLE chat_messages ADD COLUMN turn_index INTEGER",
]


# 5. DB 초기화 함수 (테이블 생성)
async def init_db():
    async with engine.begin() as conn:
        # ⚠️ [주의] 데이터 보존을 위해 drop_all은 주석 처리 유지
        # await conn.run_sync(SQLModel.metadata.drop_all)

        # 테이블 생성 (없는 테이블만)
        await conn.run_sync(SQLModel.metadata.create_all)

    # 경량 마이그레이션은 ALTER 하나당 '독립 트랜잭션'으로 실행한다.
    # (PostgreSQL 은 트랜잭션 안에서 한 문장이 실패하면 이후 문장이 전부
    #  중단되므로, 같은 트랜잭션에 묶으면 '이미 존재' 실패 하나가 나머지
    #  마이그레이션까지 막는다.)
    from sqlalchemy import text
    for _ddl in _LIGHT_MIGRATIONS:
        try:
            async with engine.begin() as conn:
                await conn.execute(text(_ddl))
            logger.info(f"✅ 경량 마이그레이션 적용: {_ddl}")
        except Exception:
            # 이미 존재하면 무시
            pass

    logger.info(f"✅ Database initialized at: {DATABASE_URL}")