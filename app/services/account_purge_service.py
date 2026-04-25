from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attachment import Attachment, UploadSession
from app.models.auth_email_code import AuthEmailCode
from app.models.auth_session import AuthSession
from app.models.chat_enums import AttachmentStatus, EventType, UploadSessionStatus
from app.models.conversation import (
    Conversation,
    ConversationEvent,
    ConversationParticipant,
)
from app.models.device import Device
from app.models.device_prekey import DevicePreKey
from app.models.login_attempt import LoginAttempt
from app.models.message import Message, MessageRecipientState, MessageVisibilityOverride
from app.models.user import User


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def purge_account(
    session: AsyncSession,
    *,
    user_id: int,
    reason: str,
) -> dict[str, int | bool]:
    user = await session.get(User, user_id)
    if user is None:
        return {
            "found": False,
            "purged": False,
            "purged_conversations": 0,
            "purged_messages": 0,
            "purged_attachments": 0,
            "revoked_devices": 0,
        }

    if user.is_deleted and user.deleted_at is not None:
        return {
            "found": True,
            "purged": False,
            "purged_conversations": 0,
            "purged_messages": 0,
            "purged_attachments": 0,
            "revoked_devices": 0,
        }

    now_dt = _now()

    conversations_result = await session.execute(
        select(Conversation).where(
            or_(
                Conversation.user_a_id == user_id,
                Conversation.user_b_id == user_id,
            )
        )
    )
    conversations = list(conversations_result.scalars().all())
    conversation_ids = [conversation.id for conversation in conversations]

    newly_purged_conversations = 0
    for conversation in conversations:
        if not conversation.is_purged:
            newly_purged_conversations += 1
            conversation.is_purged = True
            conversation.is_active = False
            conversation.purged_at = now_dt

            session.add(
                ConversationEvent(
                    conversation_id=conversation.id,
                    actor_user_id=None,
                    actor_device_id=None,
                    event_type=EventType.CONVERSATION_PURGED,
                    target_message_id=None,
                    payload={"message": "Conversation unavailable"},
                )
            )

    messages: list[Message] = []
    if conversation_ids:
        messages_result = await session.execute(
            select(Message).where(
                Message.conversation_id.in_(conversation_ids),
            )
        )
        messages = list(messages_result.scalars().all())

    newly_deleted_messages = 0
    message_ids = [message.id for message in messages]
    for message in messages:
        if not message.is_deleted_global:
            newly_deleted_messages += 1
            message.is_deleted_global = True
            message.deleted_global_at = now_dt
            message.deleted_by_user_id = user_id

    linked_attachments: list[Attachment] = []
    if conversation_ids:
        linked_attachments_result = await session.execute(
            select(Attachment)
            .join(Message, Message.id == Attachment.message_id)
            .where(
                Message.conversation_id.in_(conversation_ids),
                Attachment.deleted_at.is_(None),
            )
        )
        linked_attachments = list(linked_attachments_result.scalars().all())

    orphan_attachments_result = await session.execute(
        select(Attachment)
        .join(UploadSession, UploadSession.id == Attachment.upload_session_id)
        .where(
            UploadSession.user_id == user_id,
            Attachment.message_id.is_(None),
            Attachment.deleted_at.is_(None),
        )
    )
    orphan_attachments = list(orphan_attachments_result.scalars().all())

    attachment_by_id: dict[int, Attachment] = {}
    for attachment in linked_attachments + orphan_attachments:
        attachment_by_id[attachment.id] = attachment

    newly_deleted_attachments = 0
    for attachment in attachment_by_id.values():
        if attachment.deleted_at is None:
            newly_deleted_attachments += 1
            attachment.deleted_at = now_dt
            attachment.upload_status = AttachmentStatus.DELETED

    upload_sessions_result = await session.execute(
        select(UploadSession).where(UploadSession.user_id == user_id)
    )
    upload_sessions = list(upload_sessions_result.scalars().all())
    for upload_session in upload_sessions:
        if upload_session.completed_at is None:
            upload_session.status = UploadSessionStatus.ABORTED

    devices_result = await session.execute(
        select(Device).where(Device.user_id == user_id)
    )
    devices = list(devices_result.scalars().all())
    device_ids = [device.id for device in devices]

    for device in devices:
        device.is_active = False
        device.revoked_at = now_dt
        device.fcm_token = None
        device.public_identity_key = "purged"
        device.public_signing_key = "purged"
        device.signed_prekey = "purged"
        device.signed_prekey_signature = "purged"
        device.prekeys_count = 0
        device.device_name = "purged-device"

    if device_ids:
        await session.execute(
            delete(DevicePreKey).where(DevicePreKey.device_id.in_(device_ids))
        )

    await session.execute(delete(AuthSession).where(AuthSession.user_id == user_id))
    await session.execute(delete(AuthEmailCode).where(AuthEmailCode.user_id == user_id))
    await session.execute(delete(LoginAttempt).where(LoginAttempt.user_id == user_id))

    if message_ids:
        await session.execute(
            delete(MessageRecipientState).where(
                MessageRecipientState.message_id.in_(message_ids)
            )
        )
        await session.execute(
            delete(MessageVisibilityOverride).where(
                MessageVisibilityOverride.message_id.in_(message_ids)
            )
        )

    await session.execute(
        delete(ConversationParticipant).where(
            ConversationParticipant.user_id == user_id
        )
    )

    user.nickname = f"deleted-{user.id}-{uuid4().hex[:10]}"
    user.password_hash = "purged"
    user.email = None
    user.email_2fa_enabled = False
    user.google_2fa_enabled = False
    user.google_2fa_secret = None
    user.google_2fa_pending_secret = None
    user.google_2fa_confirmed_at = None
    user.is_active = False
    user.is_frozen = True
    user.pending_deletion = False
    user.is_deleted = True
    user.deleted_at = now_dt
    user.lock_until = None
    user.failed_login_stage = 0

    await session.flush()

    return {
        "found": True,
        "purged": True,
        "purged_conversations": newly_purged_conversations,
        "purged_messages": newly_deleted_messages,
        "purged_attachments": newly_deleted_attachments,
        "revoked_devices": len(devices),
    }
