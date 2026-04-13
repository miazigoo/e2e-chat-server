import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.conversations import CreateConversationRequest
from app.services.conversation_service import create_conversation, get_conversation
from tests.integration.helpers import create_user


async def test_create_conversation_with_self_forbidden(session: AsyncSession) -> None:
    user = await create_user(session, nickname="@u1")
    await session.commit()

    with pytest.raises(HTTPException) as exc:
        await create_conversation(
            session,
            current_user=user,
            payload=CreateConversationRequest(
                recipient_user_id=user.id,
                title="self",
                protection_mode="normal",
                message_ttl_days=60,
            ),
        )

    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "SELF_CONVERSATION_NOT_ALLOWED"


async def test_get_conversation_for_non_participant_fails(
    session: AsyncSession,
) -> None:
    user1 = await create_user(session, nickname="@u1")
    user2 = await create_user(session, nickname="@u2")
    outsider = await create_user(session, nickname="@u3")
    await session.commit()

    created = await create_conversation(
        session,
        current_user=user1,
        payload=CreateConversationRequest(
            recipient_user_id=user2.id,
            title="secret",
            protection_mode="normal",
            message_ttl_days=60,
        ),
    )

    with pytest.raises(HTTPException) as exc:
        await get_conversation(
            session,
            current_user=outsider,
            conversation_id=created["conversation_id"],
        )

    assert exc.value.status_code == 404
    assert exc.value.detail["code"] == "CONVERSATION_NOT_FOUND"
