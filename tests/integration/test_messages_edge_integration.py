# coding=utf-8
from datetime import timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError
from app.schemas.messages import DeleteMessagesRequest, SendMessageRequest
from app.services.message_service import delete_global, send_message
from tests.integration.helpers import (
    create_conversation,
    create_device,
    create_user,
    now_utc,
)


async def test_send_message_wrong_recipient_in_conversation(
    session: AsyncSession,
) -> None:
    sender = await create_user(session, nickname="@u1")
    recipient = await create_user(session, nickname="@u2")
    stranger = await create_user(session, nickname="@u3")

    sender_device = await create_device(session, user_id=sender.id)
    await create_device(session, user_id=recipient.id)

    conversation = await create_conversation(
        session,
        user_a_id=sender.id,
        user_b_id=recipient.id,
        created_by_user_id=sender.id,
        message_ttl_days=30,
    )
    await session.commit()

    with pytest.raises(BadRequestError) as exc:
        await send_message(
            session,
            current_user=sender,
            current_device=sender_device,
            payload=SendMessageRequest(
                conversation_id=conversation.id,
                recipient_user_id=stranger.id,
                message_type="text",
                ciphertext="cipher",
                encryption_mode="signal",
                nonce="nonce",
                client_created_at=now_utc(),
                expires_at=now_utc() + timedelta(days=1),
            ),
        )

    assert exc.value.status_code == 400
    assert exc.value.code == "INVALID_RECIPIENT"
    assert exc.value.message == "Recipient does not belong to conversation"


async def test_delete_global_does_not_delete_foreign_messages(
    session: AsyncSession,
) -> None:
    sender = await create_user(session, nickname="@sender")
    recipient = await create_user(session, nickname="@recipient")

    sender_device = await create_device(
        session, user_id=sender.id, device_uuid="sender-device"
    )
    recipient_device = await create_device(
        session, user_id=recipient.id, device_uuid="recipient-device"
    )

    conversation = await create_conversation(
        session,
        user_a_id=sender.id,
        user_b_id=recipient.id,
        created_by_user_id=sender.id,
        message_ttl_days=30,
    )
    await session.commit()

    sender_msg = await send_message(
        session,
        current_user=sender,
        current_device=sender_device,
        payload=SendMessageRequest(
            conversation_id=conversation.id,
            recipient_user_id=recipient.id,
            message_type="text",
            ciphertext="msg1",
            ciphertext_version=1,
            encryption_mode="signal",
            nonce="nonce1",
            client_created_at=now_utc(),
            expires_at=now_utc() + timedelta(days=1),
        ),
    )

    recipient_msg = await send_message(
        session,
        current_user=recipient,
        current_device=recipient_device,
        payload=SendMessageRequest(
            conversation_id=conversation.id,
            recipient_user_id=sender.id,
            message_type="text",
            ciphertext="msg2",
            ciphertext_version=1,
            encryption_mode="signal",
            nonce="nonce2",
            client_created_at=now_utc(),
            expires_at=now_utc() + timedelta(days=1),
        ),
    )

    result = await delete_global(
        session,
        current_user=sender,
        payload=DeleteMessagesRequest(
            conversation_id=conversation.id,
            message_ids=[sender_msg["message_id"], recipient_msg["message_id"]],
        ),
    )

    assert result["message_ids"] == [sender_msg["message_id"]]
