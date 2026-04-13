import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.messages import (
    DeleteMessagesRequest,
    MarkReadRequest,
    SendMessageRequest,
)
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
    recipient_device = await create_device(
        session, user_id=recipient.id, device_uuid="recipient-device"
    )
    stranger_device = await create_device(
        session, user_id=stranger.id, device_uuid="stranger-device"
    )

    conversation = await create_conversation(
        session,
        user_a_id=sender.id,
        user_b_id=recipient.id,
        created_by_user_id=sender.id,
    )
    await session.commit()

    sent = await send_message(
        session,
        current_user=sender,
        current_device=sender_device,
        payload=SendMessageRequest(
            conversation_id=conversation.id,
            recipient_user_id=recipient.id,
            message_type="text",
            ciphertext="msg",
            ciphertext_version=1,
            encryption_mode="signal",
            nonce="nonce",
            client_created_at=now_utc(),
        ),
    )

    with pytest.raises(HTTPException) as exc:
        await mark_read(
            session,
            current_user=stranger,
            current_device=stranger_device,
            message_id=sent["message_id"],
            payload=MarkReadRequest(),
        )

    assert exc.value.status_code == 404
    assert exc.value.detail["code"] == "MESSAGE_NOT_FOUND"


async def test_send_message_to_user_without_active_device_fails(
    session: AsyncSession,
) -> None:
    sender = await create_user(session, nickname="@sender")
    recipient = await create_user(session, nickname="@recipient")

    sender_device = await create_device(
        session, user_id=sender.id, device_uuid="sender-device"
    )
    await create_device(
        session,
        user_id=recipient.id,
        device_uuid="recipient-device",
        is_active=False,
    )

    conversation = await create_conversation(
        session,
        user_a_id=sender.id,
        user_b_id=recipient.id,
        created_by_user_id=sender.id,
    )
    await session.commit()

    with pytest.raises(HTTPException) as exc:
        await send_message(
            session,
            current_user=sender,
            current_device=sender_device,
            payload=SendMessageRequest(
                conversation_id=conversation.id,
                recipient_user_id=recipient.id,
                message_type="text",
                ciphertext="msg",
                ciphertext_version=1,
                encryption_mode="signal",
                nonce="nonce",
                client_created_at=now_utc(),
            ),
        )

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "RECIPIENT_DEVICE_NOT_READY"
