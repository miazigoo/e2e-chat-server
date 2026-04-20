import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, NotFoundError
from app.schemas.conversations import CreateConversationRequest
from app.services.conversation_service import (
    create_conversation as create_conversation_service,
)
from app.services.conversation_service import get_conversation
from tests.integration.helpers import create_conversation as create_conversation_record
from tests.integration.helpers import create_user


async def test_create_conversation_with_self_forbidden(session: AsyncSession) -> None:
    user = await create_user(session, nickname="@u1")
    await session.commit()

    with pytest.raises(BadRequestError) as exc:
        await create_conversation_service(
            session,
            current_user=user,
            payload=CreateConversationRequest(
                recipient_user_id=user.id,
                title="Self chat",
                message_ttl_days=30,
            ),
        )

    assert exc.value.status_code == 400
    assert exc.value.code == "SELF_CONVERSATION_NOT_ALLOWED"
    assert exc.value.message == "Cannot create conversation with yourself"


async def test_get_conversation_for_non_participant_fails(
    session: AsyncSession,
) -> None:
    user1 = await create_user(session, nickname="@u1")
    user2 = await create_user(session, nickname="@u2")
    user3 = await create_user(session, nickname="@u3")
    await session.commit()

    conversation = await create_conversation_record(
        session,
        user_a_id=user1.id,
        user_b_id=user2.id,
        created_by_user_id=user1.id,
    )
    await session.commit()

    with pytest.raises(NotFoundError) as exc:
        await get_conversation(
            session,
            current_user=user3,
            conversation_id=conversation.id,
        )

    assert exc.value.status_code == 404
    assert exc.value.code == "CONVERSATION_NOT_FOUND"
    assert exc.value.message == "Conversation not found"
