"""Supabase(Postgres)에 앱 구동 필수 데이터를 '안전하게(멱등/비파괴)' 주입한다.

배경:
- 프론트가 코치를 선택하면 coach_id(예: Ella=...0011)를 보내고, 백엔드는 이를
  diagnosis_sessions.coach_id 에 넣는다. 이 컬럼은 coaches.id 를 참조하는 FK 라
  해당 코치 행이 coaches 테이블에 없으면 ForeignKeyViolationError 가 난다.
- 런타임 매핑(diagnoses.py 의 COACH_UUID_TO_KEY)과 /coaches API 는
  coach_id = ...00{key+10} → ...0011~0016 을 사용한다. (key 1~6)
  (기존 seed.py 는 key+9 → ...0010~0015 로 한 칸 어긋나 있었다.)
- 또 diagnosis_sessions.diagnosis_template_id → diagnosis_templates.id,
  diagnosis_templates.coach_id → coaches.id, coaches.user_id → participants.id
  FK 가 있으므로 참가자/코치/템플릿이 함께 있어야 한다.

이 스크립트의 원칙:
- 기존 데이터를 '삭제하지 않는다'. 이미 존재하는 행(같은 PK)은 건드리지 않고,
  '없는 것만' 추가한다 → 운영 DB(이미 세션 데이터 존재)에서도 안전하고 재실행 가능.
- 주입 순서: 그룹 → 참가자 → 코치 6 → 페르소나 6 → 템플릿 (FK 부모 → 자식).

실행:
    cd /Users/daniel/python_new/new_diagnosis_api
    /Users/daniel/python_new/.venv/bin/python seed_coaches.py
"""

import asyncio
import logging
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

# 전체 모델 로드(매퍼 구성) + 엔진/테이블 생성 함수
import diag_project.models  # noqa: F401
from diag_project.database import engine, init_db
from diag_project.models.group import Group
from diag_project.models.participant import Participant
from diag_project.models.coach import Coach
from diag_project.models.coach_persona import CoachPersona
from diag_project.models.diagnosis_template import DiagnosisTemplate
from diag_project.data.coaches_persona import COACHES_PERSONA

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("seed_coaches")

# 고정 ID (매번 동일하게 유지 → 멱등성 보장)
GROUP_ID = UUID("10000000-0000-0000-0000-000000000001")
OWNER_PARTICIPANT_ID = UUID("10000000-0000-0000-0000-000000000002")
TEMPLATE_ID = UUID("10000000-0000-0000-0000-000000000008")


def coach_uuid(key: str) -> UUID:
    """런타임 COACH_UUID_TO_KEY 와 정확히 일치: ...00{key+10} (Ella=...0011)."""
    return UUID(f"10000000-0000-0000-0000-0000000000{int(key) + 10:02d}")


def persona_uuid(key: str) -> UUID:
    return UUID(f"10000000-0000-0000-0000-0000000001{int(key) + 10:02d}")


async def _add_if_absent(db: AsyncSession, model, pk: UUID, factory) -> bool:
    """PK 가 없을 때만 추가. 추가했으면 True."""
    if await db.get(model, pk):
        return False
    db.add(factory())
    return True


async def seed() -> None:
    logger.info("🌱 필수 코치/템플릿 데이터 주입 시작 (멱등/비파괴)")

    # 테이블이 없으면 생성 (있으면 무시)
    await init_db()

    added = {"group": 0, "participant": 0, "coach": 0, "persona": 0, "template": 0}

    async with AsyncSession(engine) as db:
        # 1) 그룹
        if await _add_if_absent(
            db, Group, GROUP_ID,
            lambda: Group(id=GROUP_ID, name="커넥트앤컴퍼니", group_code="G-TEST"),
        ):
            added["group"] += 1

        # 2) 코치 소유자(참가자) — coaches.user_id FK 대상
        if await _add_if_absent(
            db, Participant, OWNER_PARTICIPANT_ID,
            lambda: Participant(
                id=OWNER_PARTICIPANT_ID,
                email="admin@connectn.com",
                name="시스템관리자",
                password_hash="dummy_hashed_password",
                group_id=GROUP_ID,
                is_active=True,
            ),
        ):
            added["participant"] += 1

        # 부모(그룹/참가자) 먼저 확정 → 이후 코치 FK 안전
        await db.flush()

        # 3) 코치 6 + 4) 페르소나 6
        for key, p in COACHES_PERSONA.items():
            c_id = coach_uuid(key)
            if await _add_if_absent(
                db, Coach, c_id,
                lambda p=p, c_id=c_id, key=key: Coach(
                    id=c_id,
                    name=p["name"],
                    email=f"coach{key}@connectn.com",
                    user_id=OWNER_PARTICIPANT_ID,
                    description=p.get("description"),
                    avatar_url=f"/images/{p.get('img_file', 'default.png')}",
                    character_tags=p.get("tags"),
                ),
            ):
                added["coach"] += 1

            await db.flush()  # 코치 확정 후 페르소나 FK 안전

            pe_id = persona_uuid(key)
            if await _add_if_absent(
                db, CoachPersona, pe_id,
                lambda p=p, pe_id=pe_id, c_id=c_id: CoachPersona(
                    id=pe_id,
                    coach_id=c_id,
                    name=p["name"].split()[0],
                    description=p.get("description"),
                    system_prompt=p.get("system_prompt", ""),
                    is_default=True,
                    is_active=True,
                    gender=p.get("gender"),
                    coaching_style=p.get("coaching_style"),
                ),
            ):
                added["persona"] += 1

        # 5) 진단 템플릿 (start 요청의 template_id 대상, coach_id 는 유효 코치로)
        if await _add_if_absent(
            db, DiagnosisTemplate, TEMPLATE_ID,
            lambda: DiagnosisTemplate(
                id=TEMPLATE_ID,
                coach_id=coach_uuid("1"),  # Ella(...0011) — 유효 코치
                name="리더십 핵심 역량 진단",
                description="5대 영역 리더십 진단",
                version="1.0",
                is_active=True,
            ),
        ):
            added["template"] += 1

        await db.commit()

    logger.info("✅ 주입 완료 (이미 있던 행은 건너뜀):")
    logger.info(
        "   그룹 +%d / 참가자 +%d / 코치 +%d / 페르소나 +%d / 템플릿 +%d",
        added["group"], added["participant"], added["coach"],
        added["persona"], added["template"],
    )
    logger.info("   코치 ID: %s ~ %s", coach_uuid("1"), coach_uuid("6"))

    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
