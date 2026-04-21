# coding=utf-8
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import ConflictError, NotFoundError
from app.schemas.messages import MarkReadRequest, SendMessageRequest
from app.services.message_service import mark_read, send_message
from tests.integration.helpers import (
    create_conversation,
    create_device,
    create_user,
    now_utc,
)


async def test_mark_read_foreign_message_fails(session: AsyncSession) -> None:
    sender = await create_user(session, nickname="@sender")
    recipient = await create_user(session, nickname="@recipient")
    stranger = await create_user(session, nickname="@stranger")

    sender_device = await create_device(
        session, user_id=sender.id, device_uuid="sender-device"
    )
    await create_device(session, user_id=recipient.id, device_uuid="recipient-device")
    stranger_device = await create_device(
        session, user_id=stranger.id, device_uuid="stranger-device"
    )

    conversation = await create_conversation(
        session,
        user_a_id=sender.id,
        user_b_id=recipient.id,
        created_by_user_id=sender.id,
        message_ttl_days=30,
    )
    await session.commit()

    sent = await send_message(
        session,
        current_user=sender,
        current_device=sender_device,
        payload=SendMessageRequest(
            conversation_id=conversation.id,
            recipient_user_id=recipient.id,
            message_uuid=str(uuid4()),
            message_type="text",
            ciphertext="msg",
            ciphertext_version=1,
            encryption_mode="signal",
            nonce="nonce",
            client_created_at=now_utc(),
            expires_at=now_utc() + timedelta(days=1),
        ),
    )

    with pytest.raises(NotFoundError) as exc:
        await mark_read(
            session,
            current_user=stranger,
            current_device=stranger_device,
            message_id=sent["message_id"],
            payload=MarkReadRequest(),
        )

    assert exc.value.status_code == 404
    assert exc.value.code == "MESSAGE_NOT_FOUND"


async def test_send_message_to_user_without_active_device_fails(
    session: AsyncSession,
) -> None:
    sender = await create_user(session, nickname="@u1")
    recipient = await create_user(session, nickname="@u2")

    sender_device = await create_device(session, user_id=sender.id)

    conversation = await create_conversation(
        session,
        user_a_id=sender.id,
        user_b_id=recipient.id,
        created_by_user_id=sender.id,
        message_ttl_days=30,
    )
    await session.commit()

    with pytest.raises(ConflictError) as exc:
        await send_message(
            session,
            current_user=sender,
            current_device=sender_device,
            payload=SendMessageRequest(
                conversation_id=conversation.id,
                recipient_user_id=recipient.id,
                message_uuid=str(uuid4()),
                message_type="text",
                ciphertext="cipher",
                encryption_mode="signal",
                nonce="nonce",
                client_created_at=now_utc(),
                expires_at=now_utc() + timedelta(days=1),
            ),
        )

    assert exc.value.status_code == 409
    assert exc.value.code == "RECIPIENT_DEVICE_NOT_READY"
    assert exc.value.message == "Recipient has no active device"
