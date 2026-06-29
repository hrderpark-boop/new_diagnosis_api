# new_diagnosis_api/seed.py

import asyncio
import logging
from uuid import UUID
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import delete # 삭제 기능 추가

from diag_project.database import engine, init_db
from diag_project.models.group import Group
from diag_project.models.participant import Participant
from diag_project.models.coach import Coach
from diag_project.models.coach_persona import CoachPersona
from diag_project.models.diagnosis_template import DiagnosisTemplate
from diag_project.security import get_password_hash

# 데이터 파일 임포트
from diag_project.data.coaches_persona import COACHES_PERSONA

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("seed")

TEST_GROUP_ID = UUID("10000000-0000-0000-0000-000000000001")
TEST_PARTICIPANT_ID = UUID("10000000-0000-0000-0000-000000000002")
TEMPLATE_ID = UUID("10000000-0000-0000-0000-000000000008")

async def seed_data():
    logger.info("🌱 [진단 시스템] 데이터 시딩 시작...")
    
    # 테이블이 없으면 생성
    await init_db()

    async with AsyncSession(engine) as db:
        try:
            # 🧹 [중요] 기존 코치 데이터 깨끗하게 삭제 (초기화)
            logger.info("🧹 기존 데이터 정리 중...")
            await db.execute(delete(CoachPersona))
            await db.execute(delete(Coach))
            # 사용자와 그룹은 로그인 편의를 위해 유지하거나 없으면 생성
            
            # 1. 그룹 & 사용자
            if not await db.get(Group, TEST_GROUP_ID):
                db.add(Group(id=TEST_GROUP_ID, name="커넥트앤컴퍼니", group_code="G-TEST"))
            
            if not await db.get(Participant, TEST_PARTICIPANT_ID):
                # 비밀번호는 'password'로 통일 (bcrypt 호환)
                hashed_pwd = get_password_hash("password") 
                db.add(Participant(
                    id=TEST_PARTICIPANT_ID, email="test@example.com", name="박기진",
                    password_hash=hashed_pwd, group_id=TEST_GROUP_ID, is_active=True
                ))

            # 2. 코치 & 페르소나 (딕셔너리 순회)
            # 프론트엔드가 public/images 폴더를 바라본다고 가정하고 경로 설정
            
            for key, p_data in COACHES_PERSONA.items():
                # ID 생성 규칙 (고정 ID). 런타임 COACH_UUID_TO_KEY 및 /coaches API 와
                # 반드시 일치해야 한다: coach_id = ...00{key+10} → key '1' 이면 ...0011.
                coach_uuid = UUID(f"10000000-0000-0000-0000-0000000000{int(key) + 10:02d}")
                persona_uuid = UUID(f"10000000-0000-0000-0000-0000000001{int(key) + 10:02d}")

                # 코치 생성
                db.add(Coach(
                    id=coach_uuid, 
                    name=p_data['name'],
                    email=f"coach{key}@connectn.com",
                    user_id=TEST_PARTICIPANT_ID, # 관리자(User)와 연결
                    description=p_data['description'], 
                    # 프론트엔드 이미지 경로에 맞춤 (예: /images/female1.png)
                    avatar_url=f"/images/{p_data['img_file']}",
                    character_tags=p_data['tags']
                ))
                
                # 시스템 프롬프트 구성
                full_system_prompt = f"""
                {p_data['system_prompt']}
                [Opening Remarks]: "{p_data.get('opening_new', '')}"
                """
                
                # 페르소나 생성
                db.add(CoachPersona(
                    id=persona_uuid, 
                    coach_id=coach_uuid, 
                    name=p_data['name'].split()[0], # 화면 표시 이름 (Ella)
                    description=p_data['description'], # 설명 추가
                    system_prompt=full_system_prompt,
                    is_default=True,
                    is_active=True,
                    gender=p_data['gender'],
                    coaching_style=p_data['coaching_style']
                ))
                logger.info(f"✨ 코치 등록: {p_data['name']}")

            # 3. 진단 템플릿 (필수)
            if not await db.get(DiagnosisTemplate, TEMPLATE_ID):
                # Ella 코치(...0011)를 기본으로 하는 템플릿 생성 (유효 coach_id)
                default_coach_id = UUID("10000000-0000-0000-0000-000000000011")
                db.add(DiagnosisTemplate(
                    id=TEMPLATE_ID, 
                    coach_id=default_coach_id,
                    name="리더십 핵심 역량 진단", 
                    description="5대 영역 리더십 진단",
                    version="1.0",
                    is_active=True
                ))

            await db.commit()
            logger.info("✅ [성공] 모든 데이터가 정상적으로 업데이트되었습니다!")
            
        except Exception as e:
            await db.rollback()
            logger.error(f"❌ 시딩 실패: {e}")
            raise e

if __name__ == "__main__":
    asyncio.run(seed_data())