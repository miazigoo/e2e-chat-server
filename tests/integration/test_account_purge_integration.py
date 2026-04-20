from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attachment import Attachment, UploadSession
from app.models.chat_enums import AttachmentStatus, UploadSessionStatus
from app.models.conversation import Conversation, ConversationEvent
from app.models.device import Device
from app.models.message import Message
from app.models.user import User
from app.services.account_purge_service import purge_account
from tests.integration.helpers import (
    create_conversation,
    create_device,
    create_message,
    create_user,
)


async def test_purge_account_marks_related_data_deleted(session: AsyncSession) -> None:
    user = await create_user(session, nickname="@purge_me", email="purge@example.com")
    peer = await create_user(session, nickname="@peer")

    device = await create_device(session, user_id=user.id, device_uuid="device-1")
    peer_device = await create_device(session, user_id=peer.id, device_uuid="device-2")

    conversation = await create_conversation(
        session,
        user_a_id=user.id,
        user_b_id=peer.id,
        created_by_user_id=user.id,
    )
    message = await create_message(
        session,
        conversation_id=conversation.id,
        sender_user_id=user.id,
        sender_device_id=device.id,
        recipient_user_id=peer.id,
        recipient_device_id=peer_device.id,
    )

    upload_session = UploadSession(
        user_id=user.id,
        conversation_id=conversation.id,
        files_expected_count=1,
        files_uploaded_count=1,
        status=UploadSessionStatus.COMPLETED,
        expires_at=message.expires_at,
    )
    session.add(upload_session)
    await session.flush()

    attachment = Attachment(
        message_id=message.id,
        upload_session_id=upload_session.id,
        storage_key="attachments/test",
        bucket_name="bucket",
        file_size=123,
        sha256_encrypted_blob="a" * 64,
        upload_status=AttachmentStatus.LINKED,
    )
    session.add(attachment)
    await session.commit()

    result = await purge_account(
        session,
        user_id=user.id,
        reason="too_many_failed_attempts",
    )
    await session.commit()

    assert result["found"] is True
    assert result["purged"] is True
    assert result["purged_conversations"] == 1

    refreshed_user = await session.get(User, user.id)
    assert refreshed_user is not None
    assert refreshed_user.is_deleted is True
    assert refreshed_user.deleted_at is not None
    assert refreshed_user.email is None

    refreshed_conversation = await session.get(Conversation, conversation.id)
    assert refreshed_conversation is not None
    assert refreshed_conversation.is_purged is True
    assert refreshed_conversation.purged_at is not None

    refreshed_message = await session.get(Message, message.id)
    assert refreshed_message is not None
    assert refreshed_message.is_deleted_global is True
    assert refreshed_message.deleted_global_at is not None

    refreshed_attachment = await session.get(Attachment, attachment.id)
    assert refreshed_attachment is not None
    assert refreshed_attachment.deleted_at is not None
    assert refreshed_attachment.upload_status == AttachmentStatus.DELETED

    refreshed_device = await session.get(Device, device.id)
    assert refreshed_device is not None
    assert refreshed_device.is_active is False
    assert refreshed_device.revoked_at is not None

    events_result = await session.execute(
        select(ConversationEvent).where(
            ConversationEvent.conversation_id == conversation.id
        )
    )
    events = list(events_result.scalars().all())
    assert len(events) >= 1
