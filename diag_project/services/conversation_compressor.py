"""대화 이력 압축

완료된 사건의 turn-by-turn 대화는 요약으로 교체.
긴 챕터에서 비용/품질 모두 영향.

설계 출처: docs/phase3a/01_design.md (Section 8.3)
"""

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from diag_project.models.diagnosis_session import ChatMessage
from diag_project.models.event import Event


# 비정상 코치 응답(폴백/에러/파싱 실패) 시그니처 — 컨텍스트 오염 방지용.
_ERROR_SIGNATURES = (
    "잠시 생각할 시간을 주시겠어요",
    "다시 한번 말씀해 주시면 감사",
    "오류가 발생",
    "서버 내부 오류",
    "네트워크 통신 오류",
    "분석 중 오류",
    "sql_app.db",
)


def _is_garbage_or_error(content: str | None) -> bool:
    """코치 메시지가 비정상(에러 폴백·'?'·무의미 기호)인지 판정.

    이런 메시지가 다음 턴 컨텍스트로 재주입되면 LLM 이 '내가 에러 냈다'고
    오인해 사과 루프에 빠지므로, 히스토리에서 제외한다.
    """
    if not content:
        return True
    s = content.strip()
    if not s:
        return True
    # '?', '？', 마침표/점만으로 이뤄진 무의미 응답
    if set(s) <= set("?？.…·ㆍ​ \t\n"):
        return True
    if len(s) <= 1:
        return True
    return any(sig in s for sig in _ERROR_SIGNATURES)


async def compress_conversation_history(
    db: AsyncSession,
    session_id: UUID,
    chapter: str,
) -> list[dict]:
    """완료된 사건의 메시지를 요약으로 교체.

    Returns:
        LLM 에 전달할 message 리스트 [{role, content}, ...]
    """
    # 1. 이 챕터의 모든 메시지 (시간순)
    msg_result = await db.execute(
        select(ChatMessage)
        .where(ChatMessage.session_id == session_id)
        .where(ChatMessage.chapter == chapter)
        .order_by(ChatMessage.created_at)
    )
    messages = list(msg_result.scalars().all())

    # 2. 완료된 사건들 조회
    event_result = await db.execute(
        select(Event)
        .where(Event.session_id == session_id)
        .where(Event.chapter == chapter)
        .where(Event.is_complete == True)  # noqa: E712
    )
    completed_events = list(event_result.scalars().all())

    completed_event_ids = {e.id for e in completed_events}
    events_by_id = {e.id: e for e in completed_events}

    # 3. 압축
    compressed = []
    seen_events: set = set()

    for msg in messages:
        # 비정상 코치 응답(에러 폴백·'?')은 컨텍스트에서 제외 → 사과 루프 차단
        if msg.role == "model" and _is_garbage_or_error(msg.content):
            continue
        if msg.event_id and msg.event_id in completed_event_ids:
            # 완료된 사건의 메시지 → 첫 번째만 요약으로 교체
            if msg.event_id not in seen_events:
                event = events_by_id[msg.event_id]
                summary = _format_event_summary(event)
                compressed.append({
                    "role": "system",
                    "content": summary,
                })
                seen_events.add(msg.event_id)
            # 같은 사건의 후속 메시지는 스킵
        else:
            # 진행 중인 사건 또는 사건 없음 → 그대로 유지
            compressed.append({
                "role": msg.role,
                "content": msg.content,
            })

    return compressed


def _format_event_summary(event: Event) -> str:
    """Event 객체를 요약 텍스트로 변환."""
    parts = [f"[Completed Event Summary - Event #{event.sequence_num}]"]

    if event.summary:
        parts.append(f"요약: {event.summary}")

    if event.key_person:
        parts.append(f"인물: {event.key_person}")

    if event.core_action:
        parts.append(f"핵심 행동: {event.core_action}")

    star_parts = []
    if event.situation:
        star_parts.append(f"S: {event.situation[:100]}")
    if event.task:
        star_parts.append(f"T: {event.task[:100]}")
    if event.action:
        star_parts.append(f"A: {event.action[:100]}")
    if event.result:
        star_parts.append(f"R: {event.result[:100]}")

    if star_parts:
        parts.append("STAR: " + " | ".join(star_parts))

    return "\n".join(parts)
