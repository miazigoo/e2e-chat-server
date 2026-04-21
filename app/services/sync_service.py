from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import NotFoundError
from app.models.user import User
from app.repositories.conversations import ConversationsRepository
from app.schemas.sync import ConversationEventItemSchema, ConversationEventsResponseData

conversations_repo = ConversationsRepository()


async def get_conversation_events(
    session: AsyncSession,
    *,
    current_user: User,
    conversation_id: int,
    after_event_id: int | None,
    limit: int,
) -> ConversationEventsResponseData:
    participant = await conversations_repo.get_participant(
        session,
        conversation_id=conversation_id,
        user_id=current_user.id,
    )
    if participant is None:
        raise NotFoundError(
            code="CONVERSATION_NOT_FOUND",
            message="Conversation not found",
        )

    raw_events = await conversations_repo.list_events_for_user(
        session,
        conversation_id=conversation_id,
        user_id=current_user.id,
        after_event_id=after_event_id,
        limit=limit + 1,
        cleared_at=participant.cleared_at,
    )

    has_more = len(raw_events) > limit
    events = raw_events[:limit]

    items = [
        ConversationEventItemSchema(
            event_id=event.id,
            event_uuid=event.event_uuid,
            event_type=event.event_type,
            actor_user_id=event.actor_user_id,
            actor_device_id=event.actor_device_id,
            target_message_id=event.target_message_id,
            payload=event.payload,
            created_at=event.created_at,
        )
        for event in events
    ]

    next_after_event_id = items[-1].event_id if items else after_event_id

    return ConversationEventsResponseData(
        conversation_id=conversation_id,
        items=items,
        next_after_event_id=next_after_event_id,
        has_more=has_more,
    )
