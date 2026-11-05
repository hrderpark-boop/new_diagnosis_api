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
    commit: bool = True,
) -> Event:
    """새 사건 시작."""
    event = Event(
        session_id=session_id,
        chapter=chapter,
        sequence_num=sequence_num,
        started_at=datetime.utcnow(),
    )
    db.add(event)
    if commit:
        await db.commit()
        await db.refresh(event)
    else:
        await db.flush()   # id 확보만(턴 끝 1회 커밋)
    return event


async def update_event_star(
    db: AsyncSession,
    event_id: UUID,
    situation: str | None = None,
    task: str | None = None,
    action: str | None = None,
    result: str | None = None,
    commit: bool = True,
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
    if commit:
        await db.commit()
        await db.refresh(event)
    return event


async def complete_event(
    db: AsyncSession,
    event_id: UUID,
    metadata: dict,
    commit: bool = True,
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
    if commit:
        await db.commit()
        await db.refresh(event)
    return event




