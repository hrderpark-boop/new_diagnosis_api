"""Event 테이블 CRUD + STAR 진행 추적

기존 services/ 패턴(async, AsyncSession) 따름.

설계 출처: docs/phase3a/01_design.md (Section 8.1)
"""

from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from diag_project.models.event import Event


async def create_event(
    db: AsyncSession,
    session_id: UUID,
    chapter: str,
    sequence_num: int,
) -> Event:
    """새 사건 시작."""
    event = Event(
        session_id=session_id,
        chapter=chapter,
        sequence_num=sequence_num,
        started_at=datetime.utcnow(),
    )
    db.add(event)
    await db.commit()
    await db.refresh(event)
    return event


async def update_event_star(
    db: AsyncSession,
    event_id: UUID,
    situation: str | None = None,
    task: str | None = None,
    action: str | None = None,
    result: str | None = None,
) -> Event | None:
    """사건의 STAR 요소 업데이트. 자동으로 star_coverage 재계산."""
    event = await db.get(Event, event_id)
    if not event:
        return None

    if situation is not None:
        event.situation = situation
    if task is not None:
        event.task = task
    if action is not None:
        event.action = action
    if result is not None:
        event.result = result

    coverage = sum([
        bool(event.situation),
        bool(event.task),
        bool(event.action),
        bool(event.result),
    ]) / 4.0
    event.star_coverage = coverage

    db.add(event)
    await db.commit()
    await db.refresh(event)
    return event


async def complete_event(
    db: AsyncSession,
    event_id: UUID,
    metadata: dict,
) -> Event | None:
    """사건 완료 + 메타데이터 저장 (Module 4용)."""
    event = await db.get(Event, event_id)
    if not event:
        return None

    event.is_complete = True
    event.completed_at = datetime.utcnow()
    event.summary = metadata.get("summary")
    event.key_person = metadata.get("key_person")
    event.time_context = metadata.get("time_context")
    event.core_action = metadata.get("core_action")
    event.tags = metadata.get("tags", []) or []
    # 동적 태깅: 실제 스토리에 가장 부합하는 하위역량
    _mapped = metadata.get("mapped_subcompetency")
    if _mapped:
        event.mapped_subcompetency = _mapped

    db.add(event)
    await db.commit()
    await db.refresh(event)
    return event


async def increment_probe_count(
    db: AsyncSession,
    event_id: UUID,
) -> None:
    """탐침 횟수 증가."""
    event = await db.get(Event, event_id)
    if event:
        event.probe_count += 1
        db.add(event)
        await db.commit()


async def get_active_event(
    db: AsyncSession,
    session_id: UUID,
    chapter: str,
) -> Event | None:
    """현재 챕터의 진행 중인 사건 (is_complete == False) 1개 반환."""
    result = await db.execute(
        select(Event)
        .where(Event.session_id == session_id)
        .where(Event.chapter == chapter)
        .where(Event.is_complete == False)  # noqa: E712
        .order_by(Event.sequence_num.desc())
        .limit(1)
    )
    return result.scalars().first()


async def get_chapter_events(
    db: AsyncSession,
    session_id: UUID,
    chapter: str,
) -> list[Event]:
    """현재 챕터의 모든 사건 (완료/미완료 모두) 반환."""
    result = await db.execute(
        select(Event)
        .where(Event.session_id == session_id)
        .where(Event.chapter == chapter)
        .order_by(Event.sequence_num)
    )
    return list(result.scalars().all())
