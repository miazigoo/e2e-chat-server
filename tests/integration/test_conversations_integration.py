from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import ConversationParticipant
from app.schemas.conversations import CreateConversationRequest
from app.services.conversation_service import create_conversation
from tests.integration.helpers import create_user


async def test_create_conversation_creates_participants(session: AsyncSession) -> None:
    user1 = await create_user(session, nickname="@u1")
    user2 = await create_user(session, nickname="@u2")
    await session.commit()

    payload = CreateConversationRequest(
        recipient_user_id=user2.id,
        title="Main chat",
        protection_mode="normal",
        message_ttl_days=60,
    )

    result = await create_conversation(
        session,
        current_user=user1,
        payload=payload,
    )

    assert result["recipient_user_id"] == user2.id

    query = await session.execute(
        select(ConversationParticipant).where(
            ConversationParticipant.conversation_id == result["conversation_id"]
        )
    )
    participants = list(query.scalars().all())

    assert len(participants) == 2
    participant_ids = {item.user_id for item in participants}
    assert participant_ids == {user1.id, user2.id}


async def test_list_conversations_auto_creates_saved_messages(
    session: AsyncSession,
) -> None:
    from app.services.conversation_service import list_conversations

    user = await create_user(session, nickname="@solo")
    await session.commit()

    result = await list_conversations(session, current_user=user)

    assert len(result.items) == 1
    item = result.items[0]
    assert item.is_saved_messages is True
    assert item.title == "Избранное"
    assert item.peer.user_id == user.id
