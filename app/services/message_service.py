from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_enums import EventType, VisibilityReason
from app.models.device import Device
from app.models.user import User
from app.repositories.conversations import ConversationsRepository
from app.repositories.devices import DevicesRepository
from app.repositories.files import FilesRepository
from app.repositories.messages import MessagesRepository
from app.schemas.messages import (
    DeleteMessagesRequest,
    MarkReadRequest,
    SendMessageRequest,
)

conversations_repo = ConversationsRepository()
messages_repo = MessagesRepository()
devices_repo = DevicesRepository()
files_repo = FilesRepository()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _other_participant_id(
    conversation_user_a_id: int, conversation_user_b_id: int, current_user_id: int
) -> int:
    if conversation_user_a_id == current_user_id:
        return conversation_user_b_id
    return conversation_user_a_id


def _resolve_expires_at(
    *,
    explicit_expires_at: datetime | None,
    conversation_ttl_days: int | None,
) -> datetime:
    if explicit_expires_at is not None:
        return explicit_expires_at

    ttl_days = conversation_ttl_days or 60
    return _now() + timedelta(days=ttl_days)


async def send_message(
    session: AsyncSession,
    *,
    current_user: User,
    current_device: Device,
    payload: SendMessageRequest,
) -> dict:
    conversation = await conversations_repo.get_for_user(
        session,
        conversation_id=payload.conversation_id,
        user_id=current_user.id,
    )
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "CONVERSATION_NOT_FOUND",
                "message": "Conversation not found",
            },
        )

    if conversation.is_purged:
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={
                "code": "CONVERSATION_PURGED",
                "message": "Conversation is purged",
            },
        )

    expected_recipient_id = _other_participant_id(
        conversation.user_a_id,
        conversation.user_b_id,
        current_user.id,
    )
    if payload.recipient_user_id != expected_recipient_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_RECIPIENT",
                "message": "Recipient does not belong to conversation",
            },
        )

    recipient_device = await devices_repo.get_active_by_user_id(
        session,
        user_id=payload.recipient_user_id,
    )
    if not recipient_device:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "RECIPIENT_DEVICE_NOT_READY",
                "message": "Recipient has no active device",
            },
        )

    attachments = []
    if payload.attachment_ids:
        attachments = await files_repo.get_attachments_for_user_linking(
            session,
            user_id=current_user.id,
            attachment_ids=payload.attachment_ids,
        )
        if len(attachments) != len(payload.attachment_ids):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "INVALID_ATTACHMENT_IDS",
                    "message": "One or more attachments are invalid or unavailable",
                },
            )

    expires_at = _resolve_expires_at(
        explicit_expires_at=payload.expires_at,
        conversation_ttl_days=conversation.message_ttl_days,
    )
    auto_delete_after_read_seconds = (
        payload.auto_delete_after_read_seconds
        if payload.auto_delete_after_read_seconds is not None
        else conversation.delete_after_read_seconds
    )

    existing_message = (
        await messages_repo.get_by_message_uuid(
            session,
            conversation_id=conversation.id,
            sender_user_id=current_user.id,
            message_uuid=payload.message_uuid,
        )
        if payload.message_uuid
        else None
    )

    if existing_message is not None:
        return {
            "message_id": existing_message.id,
            "message_uuid": existing_message.message_uuid,
            "conversation_id": existing_message.conversation_id,
            "recipient_user_id": existing_message.recipient_user_id,
            "recipient_device_id": existing_message.recipient_device_id,
            "server_received_at": existing_message.server_received_at,
            "delivery_status": "server_received",
            "is_idempotent_replay": True,
        }

    message = await messages_repo.create_message(
        session,
        conversation_id=conversation.id,
        sender_user_id=current_user.id,
        sender_device_id=current_device.id,
        recipient_user_id=payload.recipient_user_id,
        recipient_device_id=recipient_device.id,
        message_uuid=payload.message_uuid,
        reply_to_message_id=payload.reply_to_message_id,
        message_type=payload.message_type,
        ciphertext=payload.ciphertext,
        ciphertext_version=payload.ciphertext_version,
        encryption_mode=payload.encryption_mode,
        nonce=payload.nonce,
        aad_hash=payload.aad_hash,
        client_created_at=payload.client_created_at,
        expires_at=expires_at,
        auto_delete_after_read_seconds=auto_delete_after_read_seconds,
        has_attachments=bool(payload.attachment_ids),
    )

    await messages_repo.create_recipient_state(
        session,
        message_id=message.id,
        recipient_user_id=payload.recipient_user_id,
        recipient_device_id=recipient_device.id,
    )

    if attachments:
        await files_repo.link_attachments_to_message(
            session,
            attachments=attachments,
            message_id=message.id,
        )

    await conversations_repo.create_event(
        session,
        conversation_id=conversation.id,
        actor_user_id=current_user.id,
        actor_device_id=current_device.id,
        event_type=EventType.MESSAGE_CREATED,
        target_message_id=message.id,
        payload={
            "message_id": message.id,
            "message_uuid": message.message_uuid,
            "attachment_ids": payload.attachment_ids,
            "sender_user_id": message.sender_user_id,
            "sender_device_id": message.sender_device_id,
            "recipient_user_id": message.recipient_user_id,
            "recipient_device_id": message.recipient_device_id,
            "message_type": message.message_type.value,
            "has_attachments": message.has_attachments,
            "client_created_at": message.client_created_at.isoformat(),
            "server_received_at": (
                message.server_received_at.isoformat()
                if message.server_received_at
                else None
            ),
        },
    )

    await session.commit()

    return {
        "message_id": message.id,
        "message_uuid": message.message_uuid,
        "conversation_id": message.conversation_id,
        "recipient_user_id": message.recipient_user_id,
        "recipient_device_id": message.recipient_device_id,
        "server_received_at": message.server_received_at,
        "delivery_status": "server_received",
        "is_idempotent_replay": False,
    }


async def list_messages(
    session: AsyncSession,
    *,
    current_user: User,
    conversation_id: int,
    before_id: int | None,
    limit: int,
) -> dict:
    participant = await conversations_repo.get_participant(
        session,
        conversation_id=conversation_id,
        user_id=current_user.id,
    )
    if not participant:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "CONVERSATION_NOT_FOUND",
                "message": "Conversation not found",
            },
        )

    messages = await messages_repo.list_for_user(
        session,
        conversation_id=conversation_id,
        user_id=current_user.id,
        before_id=before_id,
        limit=limit,
        cleared_at=participant.cleared_at,
    )

    items: list[dict] = []
    for message in messages:
        items.append(
            {
                "message_id": message.id,
                "message_uuid": message.message_uuid,
                "sender_user_id": message.sender_user_id,
                "recipient_user_id": message.recipient_user_id,
                "message_type": message.message_type.value,
                "ciphertext": message.ciphertext,
                "ciphertext_version": message.ciphertext_version,
                "encryption_mode": message.encryption_mode.value,
                "nonce": message.nonce,
                "aad_hash": message.aad_hash,
                "client_created_at": message.client_created_at.isoformat(),
                "server_received_at": message.server_received_at.isoformat(),
                "read_at": message.read_at.isoformat() if message.read_at else None,
                "expires_at": message.expires_at.isoformat(),
                "has_attachments": message.has_attachments,
            }
        )

    return {"items": items}


async def mark_read(
    session: AsyncSession,
    *,
    current_user: User,
    current_device: Device,
    message_id: int,
    payload: MarkReadRequest,
) -> dict:
    message = await messages_repo.get_message_for_recipient(
        session,
        message_id=message_id,
        user_id=current_user.id,
        recipient_device_id=current_device.id,
    )
    if not message:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "MESSAGE_NOT_FOUND",
                "message": "Message not found",
            },
        )

    read_at = payload.read_at or _now()
    state = await messages_repo.get_recipient_state(
        session,
        message_id=message.id,
        recipient_device_id=current_device.id,
    )
    await messages_repo.mark_read(
        session,
        message=message,
        state=state,
        read_at=read_at,
    )

    participant = await conversations_repo.get_participant(
        session,
        conversation_id=message.conversation_id,
        user_id=current_user.id,
    )
    if participant:
        participant.last_read_message_id = message.id
        participant.last_read_at = read_at

    await conversations_repo.create_event(
        session,
        conversation_id=message.conversation_id,
        actor_user_id=current_user.id,
        actor_device_id=current_device.id,
        event_type=EventType.MESSAGE_READ,
        target_message_id=message.id,
        payload={"message_id": message.id, "read_at": read_at.isoformat()},
    )

    await session.commit()

    return {
        "message_id": message.id,
        "status": "read",
        "read_at": read_at.isoformat(),
    }


async def delete_local(
    session: AsyncSession,
    *,
    current_user: User,
    payload: DeleteMessagesRequest,
) -> dict:
    conversation = await conversations_repo.get_for_user(
        session,
        conversation_id=payload.conversation_id,
        user_id=current_user.id,
    )
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "CONVERSATION_NOT_FOUND",
                "message": "Conversation not found",
            },
        )

    hidden_ids = await messages_repo.hide_messages_for_user(
        session,
        conversation_id=payload.conversation_id,
        user_id=current_user.id,
        message_ids=payload.message_ids,
        reason=VisibilityReason.USER_DELETED,
    )

    await conversations_repo.create_event(
        session,
        conversation_id=payload.conversation_id,
        actor_user_id=current_user.id,
        actor_device_id=None,
        event_type=EventType.MESSAGE_HIDDEN_FOR_USER,
        payload={"message_ids": hidden_ids, "scope": "local"},
    )

    await session.commit()

    return {
        "deleted": True,
        "scope": "local",
        "message_ids": hidden_ids,
    }


async def delete_global(
    session: AsyncSession,
    *,
    current_user: User,
    payload: DeleteMessagesRequest,
) -> dict:
    conversation = await conversations_repo.get_for_user(
        session,
        conversation_id=payload.conversation_id,
        user_id=current_user.id,
    )
    if not conversation:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "CONVERSATION_NOT_FOUND",
                "message": "Conversation not found",
            },
        )

    deleted_messages = await messages_repo.delete_global_messages(
        session,
        conversation_id=payload.conversation_id,
        actor_user_id=current_user.id,
        message_ids=payload.message_ids,
        deleted_at=_now(),
    )
    deleted_ids = [message.id for message in deleted_messages]

    await conversations_repo.create_event(
        session,
        conversation_id=payload.conversation_id,
        actor_user_id=current_user.id,
        actor_device_id=None,
        event_type=EventType.MESSAGE_DELETED_GLOBAL,
        payload={"message_ids": deleted_ids, "scope": "global"},
    )

    await session.commit()

    return {
        "deleted": True,
        "scope": "global",
        "message_ids": deleted_ids,
    }
