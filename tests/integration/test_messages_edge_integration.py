# coding=utf-8
from datetime import timedelta
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError
from app.models.attachment import Attachment, AttachmentMediaTag, UploadSession
from app.models.chat_enums import AttachmentStatus, UploadSessionStatus
from app.models.message import MessageDevicePayload, MessageRecipientState
from app.schemas.media_tags import CreateMediaTagRequest
from app.schemas.messages import DeleteMessagesRequest, SendMessageRequest
from app.services.media_tag_service import create_media_tag
from app.services.message_service import (
    delete_global,
    list_shared_messages,
    send_message,
)
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
                message_uuid=str(uuid4()),
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
            message_uuid=str(uuid4()),
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
            message_uuid=str(uuid4()),
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


async def test_send_message_fans_out_to_all_active_recipient_devices(
    session: AsyncSession,
) -> None:
    sender = await create_user(session, nickname="@sender-fanout")
    recipient = await create_user(session, nickname="@recipient-fanout")
    sender_device = await create_device(
        session, user_id=sender.id, device_uuid="sender-fanout-device"
    )
    recipient_device_1 = await create_device(
        session, user_id=recipient.id, device_uuid="recipient-fanout-1"
    )
    recipient_device_2 = await create_device(
        session, user_id=recipient.id, device_uuid="recipient-fanout-2"
    )
    revoked_recipient_device = await create_device(
        session,
        user_id=recipient.id,
        device_uuid="recipient-fanout-revoked",
        is_active=False,
    )
    conversation = await create_conversation(
        session,
        user_a_id=sender.id,
        user_b_id=recipient.id,
        created_by_user_id=sender.id,
        message_ttl_days=30,
    )
    await session.commit()

    result = await send_message(
        session,
        current_user=sender,
        current_device=sender_device,
        payload=SendMessageRequest(
            conversation_id=conversation.id,
            recipient_user_id=recipient.id,
            message_uuid=str(uuid4()),
            message_type="text",
            ciphertext="legacy-cipher",
            ciphertext_version=1,
            encryption_mode="signal",
            nonce="legacy-nonce",
            client_created_at=now_utc(),
            expires_at=now_utc() + timedelta(days=1),
            device_payloads=[
                {
                    "device_id": recipient_device_1.id,
                    "ciphertext": "cipher-1",
                    "ciphertext_version": 1,
                    "nonce": "nonce-1",
                },
                {
                    "device_id": recipient_device_2.id,
                    "ciphertext": "cipher-2",
                    "ciphertext_version": 1,
                    "nonce": "nonce-2",
                },
            ],
        ),
    )

    assert result["recipient_device_ids"] == [
        recipient_device_1.id,
        recipient_device_2.id,
    ]

    states = (
        (
            await session.execute(
                select(MessageRecipientState).where(
                    MessageRecipientState.message_id == result["message_id"]
                )
            )
        )
        .scalars()
        .all()
    )
    payloads = (
        (
            await session.execute(
                select(MessageDevicePayload).where(
                    MessageDevicePayload.message_id == result["message_id"]
                )
            )
        )
        .scalars()
        .all()
    )

    assert {state.recipient_device_id for state in states} == {
        recipient_device_1.id,
        recipient_device_2.id,
    }
    assert {payload.device_id for payload in payloads} == {
        recipient_device_1.id,
        recipient_device_2.id,
    }
    assert revoked_recipient_device.id not in {
        state.recipient_device_id for state in states
    }


async def test_send_file_message_assigns_media_tags_and_filters_shared(
    session: AsyncSession,
) -> None:
    sender = await create_user(session, nickname="@sender-tags")
    recipient = await create_user(session, nickname="@recipient-tags")
    sender_device = await create_device(
        session, user_id=sender.id, device_uuid="sender-tags-device"
    )
    await create_device(
        session, user_id=recipient.id, device_uuid="recipient-tags-device"
    )
    conversation = await create_conversation(
        session,
        user_a_id=sender.id,
        user_b_id=recipient.id,
        created_by_user_id=sender.id,
        message_ttl_days=30,
    )
    upload_session = UploadSession(
        user_id=sender.id,
        conversation_id=conversation.id,
        status=UploadSessionStatus.COMPLETED,
        files_expected_count=1,
        files_uploaded_count=1,
        expires_at=now_utc() + timedelta(hours=1),
        completed_at=now_utc(),
    )
    session.add(upload_session)
    await session.flush()
    attachment = Attachment(
        upload_session_id=upload_session.id,
        storage_key="attachments/tagged-check",
        bucket_name="attachments",
        encrypted_file_name="check.enc",
        encrypted_metadata={"kind": "check"},
        file_size=123,
        mime_hint="image/png",
        sha256_encrypted_blob="a" * 64,
        upload_status=AttachmentStatus.UPLOADED,
        expires_at=now_utc() + timedelta(days=1),
    )
    session.add(attachment)
    await session.commit()

    tag = await create_media_tag(
        session,
        current_user=sender,
        conversation_id=conversation.id,
        payload=CreateMediaTagRequest(name="Чеки", color="#00AA55"),
    )

    sent = await send_message(
        session,
        current_user=sender,
        current_device=sender_device,
        payload=SendMessageRequest(
            conversation_id=conversation.id,
            recipient_user_id=recipient.id,
            message_uuid=str(uuid4()),
            message_type="file",
            ciphertext="file-cipher",
            ciphertext_version=1,
            encryption_mode="signal",
            nonce="file-nonce",
            client_created_at=now_utc(),
            expires_at=now_utc() + timedelta(days=1),
            attachment_ids=[attachment.id],
            attachment_tag_ids=[tag.tag_id],
        ),
    )

    link = (
        await session.execute(
            select(AttachmentMediaTag).where(
                AttachmentMediaTag.attachment_id == attachment.id,
                AttachmentMediaTag.tag_id == tag.tag_id,
            )
        )
    ).scalar_one_or_none()
    assert link is not None

    shared = await list_shared_messages(
        session,
        current_user=sender,
        current_device=sender_device,
        conversation_id=conversation.id,
        tab="media",
        before_message_id=None,
        tag_id=tag.tag_id,
        limit=20,
    )
    assert [item.message_id for item in shared.items] == [sent["message_id"]]


async def test_replace_attachment_tags_updates_shared_filtering(
    session: AsyncSession,
) -> None:
    from app.schemas.media_tags import CreateMediaTagRequest, SetAttachmentTagsRequest
    from app.services.attachment_service import list_attachments_for_messages
    from app.services.media_tag_service import create_media_tag, set_tags_for_attachment

    sender = await create_user(session, nickname="@sender-retag")
    recipient = await create_user(session, nickname="@recipient-retag")
    sender_device = await create_device(
        session, user_id=sender.id, device_uuid="sender-retag-device"
    )
    await create_device(
        session, user_id=recipient.id, device_uuid="recipient-retag-device"
    )
    conversation = await create_conversation(
        session,
        user_a_id=sender.id,
        user_b_id=recipient.id,
        created_by_user_id=sender.id,
        message_ttl_days=30,
    )
    upload_session = UploadSession(
        user_id=sender.id,
        conversation_id=conversation.id,
        status=UploadSessionStatus.COMPLETED,
        files_expected_count=1,
        files_uploaded_count=1,
        expires_at=now_utc() + timedelta(hours=1),
        completed_at=now_utc(),
    )
    session.add(upload_session)
    await session.flush()
    attachment = Attachment(
        upload_session_id=upload_session.id,
        storage_key="attachments/retagged-check",
        bucket_name="attachments",
        encrypted_file_name="retag.enc",
        encrypted_metadata={"kind": "retag"},
        file_size=321,
        mime_hint="image/png",
        sha256_encrypted_blob="c" * 64,
        upload_status=AttachmentStatus.UPLOADED,
        expires_at=now_utc() + timedelta(days=1),
    )
    session.add(attachment)
    await session.commit()

    checks = await create_media_tag(
        session,
        current_user=sender,
        conversation_id=conversation.id,
        payload=CreateMediaTagRequest(name="Чеки", color="#00AA55"),
    )
    photos = await create_media_tag(
        session,
        current_user=sender,
        conversation_id=conversation.id,
        payload=CreateMediaTagRequest(name="Фото", color="#3366FF"),
    )

    sent = await send_message(
        session,
        current_user=sender,
        current_device=sender_device,
        payload=SendMessageRequest(
            conversation_id=conversation.id,
            recipient_user_id=recipient.id,
            message_uuid=str(uuid4()),
            message_type="file",
            ciphertext="file-cipher",
            ciphertext_version=1,
            encryption_mode="signal",
            nonce="file-nonce",
            client_created_at=now_utc(),
            expires_at=now_utc() + timedelta(days=1),
            attachment_ids=[attachment.id],
            attachment_tag_ids=[checks.tag_id],
        ),
    )

    updated = await set_tags_for_attachment(
        session,
        current_user=sender,
        attachment_id=attachment.id,
        payload=SetAttachmentTagsRequest(tag_ids=[photos.tag_id]),
    )
    assert [item.tag_id for item in updated.items] == [photos.tag_id]

    shared_checks = await list_shared_messages(
        session,
        current_user=sender,
        current_device=sender_device,
        conversation_id=conversation.id,
        tab="media",
        before_message_id=None,
        tag_id=checks.tag_id,
        limit=20,
    )
    assert shared_checks.items == []

    shared_photos = await list_shared_messages(
        session,
        current_user=sender,
        current_device=sender_device,
        conversation_id=conversation.id,
        tab="media",
        before_message_id=None,
        tag_id=photos.tag_id,
        limit=20,
    )
    assert [item.message_id for item in shared_photos.items] == [sent["message_id"]]

    batch = await list_attachments_for_messages(
        session,
        current_user=sender,
        message_ids=[sent["message_id"]],
    )
    assert len(batch.items) == 1
    assert len(batch.items[0].items) == 1
    assert [tag.tag_id for tag in batch.items[0].items[0].media_tags] == [photos.tag_id]
