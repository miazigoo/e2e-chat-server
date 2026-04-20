from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_log
from app.core.exceptions import BadRequestError, ConflictError, GoneError, NotFoundError
from app.core.realtime import realtime_hub
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


def _enqueue_push_notification(
    *,
    user_id: int,
    conversation_id: int,
    message_id: int,
) -> None:
    try:
        from app.worker.tasks import send_new_message_push_task

        send_new_message_push_task.delay(user_id, conversation_id, message_id)
    except Exception:
        return


def _enqueue_recompute_unread(user_id: int) -> None:
    try:
        from app.worker.tasks import recompute_unread_counters_for_user_task

        recompute_unread_counters_for_user_task.delay(user_id)
    except Exception:
        return


def _other_participant_id(
    conversation_user_a_id: int,
    conversation_user_b_id: int,
    current_user_id: int,
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


def _event_to_realtime_payload(
    *,
    conversation_id: int,
    event_type: str,
    event_id: int,
    event_uuid: str,
    actor_user_id: int | None,
    actor_device_id: int | None,
    target_message_id: int | None,
    payload: dict | None,
    created_at: datetime,
) -> dict:
    return {
        "type": "conversation.event",
        "conversation_id": conversation_id,
        "event": {
            "event_id": event_id,
            "event_uuid": event_uuid,
            "event_type": event_type,
            "actor_user_id": actor_user_id,
            "actor_device_id": actor_device_id,
            "target_message_id": target_message_id,
            "payload": payload,
            "created_at": created_at.isoformat(),
        },
    }


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
        raise NotFoundError(
            code="CONVERSATION_NOT_FOUND",
            message="Conversation not found",
        )

    if conversation.is_purged:
        raise GoneError(
            code="CONVERSATION_PURGED",
            message="Conversation is purged",
        )

    expected_recipient_id = _other_participant_id(
        conversation.user_a_id,
        conversation.user_b_id,
        current_user.id,
    )
    if payload.recipient_user_id != expected_recipient_id:
        raise BadRequestError(
            code="INVALID_RECIPIENT",
            message="Recipient does not belong to conversation",
        )

    if payload.reply_to_message_id is not None:
        reply_target = await messages_repo.get_by_id_in_conversation(
            session,
            message_id=payload.reply_to_message_id,
            conversation_id=conversation.id,
        )
        if reply_target is None:
            raise NotFoundError(
                code="REPLY_TARGET_NOT_FOUND",
                message="Reply target message not found",
            )

    recipient_device = await devices_repo.get_active_by_user_id(
        session,
        user_id=payload.recipient_user_id,
    )
    if not recipient_device:
        raise ConflictError(
            code="RECIPIENT_DEVICE_NOT_READY",
            message="Recipient has no active device",
        )

    attachments = []
    if payload.attachment_ids:
        attachments = await files_repo.get_attachments_for_user_linking(
            session,
            user_id=current_user.id,
            conversation_id=conversation.id,
            attachment_ids=payload.attachment_ids,
        )
        if len(attachments) != len(payload.attachment_ids):
            raise BadRequestError(
                code="INVALID_ATTACHMENT_IDS",
                message="One or more attachments are invalid or unavailable",
            )

    now_dt = _now()
    expires_at = _resolve_expires_at(
        explicit_expires_at=payload.expires_at,
        conversation_ttl_days=conversation.message_ttl_days,
    )

    if expires_at <= now_dt:
        raise BadRequestError(
            code="INVALID_EXPIRES_AT",
            message="expires_at must be in the future",
        )

    if conversation.message_ttl_days is not None:
        max_expires_at = now_dt + timedelta(days=conversation.message_ttl_days)
        if expires_at > max_expires_at:
            raise BadRequestError(
                code="EXPIRES_AT_EXCEEDS_CONVERSATION_TTL",
                message="Message expiration exceeds conversation TTL",
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

    event = await conversations_repo.create_event(
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

    await conversations_repo.touch_conversation(
        session,
        conversation=conversation,
        touched_at=now_dt,
    )

    await session.commit()

    audit_log(
        "message_sent",
        user_id=current_user.id,
        device_id=current_device.id,
        conversation_id=conversation.id,
        message_id=message.id,
        extra={"recipient_user_id": payload.recipient_user_id},
    )

    _enqueue_push_notification(
        user_id=payload.recipient_user_id,
        conversation_id=conversation.id,
        message_id=message.id,
    )
    _enqueue_recompute_unread(payload.recipient_user_id)
    _enqueue_recompute_unread(current_user.id)

    realtime_payload = _event_to_realtime_payload(
        conversation_id=conversation.id,
        event_type=event.event_type.value,
        event_id=event.id,
        event_uuid=event.event_uuid,
        actor_user_id=event.actor_user_id,
        actor_device_id=event.actor_device_id,
        target_message_id=event.target_message_id,
        payload=event.payload,
        created_at=event.created_at,
    )
    await realtime_hub.publish_conversation_event(conversation.id, realtime_payload)
    await realtime_hub.publish_user_event(payload.recipient_user_id, realtime_payload)

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
        raise NotFoundError(
            code="CONVERSATION_NOT_FOUND",
            message="Conversation not found",
        )

    messages = await messages_repo.list_for_user(
        session,
        conversation_id=conversation_id,
        user_id=current_user.id,
        before_id=before_id,
        limit=limit,
        cleared_at=participant.cleared_at,
    )

    ordered_messages = list(reversed(messages))

    items: list[dict] = []
    for message in ordered_messages:
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
        raise NotFoundError(
            code="MESSAGE_NOT_FOUND",
            message="Message not found",
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

    event = await conversations_repo.create_event(
        session,
        conversation_id=message.conversation_id,
        actor_user_id=current_user.id,
        actor_device_id=current_device.id,
        event_type=EventType.MESSAGE_READ,
        target_message_id=message.id,
        payload={"message_id": message.id, "read_at": read_at.isoformat()},
    )

    conversation = await conversations_repo.get_for_user(
        session,
        conversation_id=message.conversation_id,
        user_id=current_user.id,
    )
    if conversation is not None:
        await conversations_repo.touch_conversation(
            session,
            conversation=conversation,
            touched_at=read_at,
        )

    await session.commit()

    audit_log(
        "message_read",
        user_id=current_user.id,
        device_id=current_device.id,
        conversation_id=message.conversation_id,
        message_id=message.id,
    )

    _enqueue_recompute_unread(current_user.id)
    _enqueue_recompute_unread(message.sender_user_id)

    realtime_payload = _event_to_realtime_payload(
        conversation_id=message.conversation_id,
        event_type=event.event_type.value,
        event_id=event.id,
        event_uuid=event.event_uuid,
        actor_user_id=event.actor_user_id,
        actor_device_id=event.actor_device_id,
        target_message_id=event.target_message_id,
        payload=event.payload,
        created_at=event.created_at,
    )
    await realtime_hub.publish_conversation_event(
        message.conversation_id, realtime_payload
    )
    await realtime_hub.publish_user_event(message.sender_user_id, realtime_payload)

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
        raise NotFoundError(
            code="CONVERSATION_NOT_FOUND",
            message="Conversation not found",
        )

    hidden_ids = await messages_repo.hide_messages_for_user(
        session,
        conversation_id=payload.conversation_id,
        user_id=current_user.id,
        message_ids=payload.message_ids,
        reason=VisibilityReason.USER_DELETED,
    )

    event = await conversations_repo.create_event(
        session,
        conversation_id=payload.conversation_id,
        actor_user_id=current_user.id,
        actor_device_id=None,
        event_type=EventType.MESSAGE_HIDDEN_FOR_USER,
        payload={"message_ids": hidden_ids, "scope": "local"},
    )

    await conversations_repo.touch_conversation(
        session,
        conversation=conversation,
        touched_at=_now(),
    )

    await session.commit()

    audit_log(
        "message_deleted_local",
        user_id=current_user.id,
        conversation_id=payload.conversation_id,
        extra={"message_ids": hidden_ids},
    )
    _enqueue_recompute_unread(current_user.id)

    realtime_payload = _event_to_realtime_payload(
        conversation_id=payload.conversation_id,
        event_type=event.event_type.value,
        event_id=event.id,
        event_uuid=event.event_uuid,
        actor_user_id=event.actor_user_id,
        actor_device_id=event.actor_device_id,
        target_message_id=event.target_message_id,
        payload=event.payload,
        created_at=event.created_at,
    )
    await realtime_hub.publish_conversation_event(
        payload.conversation_id, realtime_payload
    )

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
        raise NotFoundError(
            code="CONVERSATION_NOT_FOUND",
            message="Conversation not found",
        )

    deleted_messages = await messages_repo.delete_global_messages(
        session,
        conversation_id=payload.conversation_id,
        actor_user_id=current_user.id,
        message_ids=payload.message_ids,
        deleted_at=_now(),
    )
    deleted_ids = [message.id for message in deleted_messages]

    event = await conversations_repo.create_event(
        session,
        conversation_id=payload.conversation_id,
        actor_user_id=current_user.id,
        actor_device_id=None,
        event_type=EventType.MESSAGE_DELETED_GLOBAL,
        payload={"message_ids": deleted_ids, "scope": "global"},
    )

    await conversations_repo.touch_conversation(
        session,
        conversation=conversation,
        touched_at=_now(),
    )

    await session.commit()

    audit_log(
        "message_deleted_global",
        user_id=current_user.id,
        conversation_id=payload.conversation_id,
        extra={"message_ids": deleted_ids},
    )
    _enqueue_recompute_unread(current_user.id)

    realtime_payload = _event_to_realtime_payload(
        conversation_id=payload.conversation_id,
        event_type=event.event_type.value,
        event_id=event.id,
        event_uuid=event.event_uuid,
        actor_user_id=event.actor_user_id,
        actor_device_id=event.actor_device_id,
        target_message_id=event.target_message_id,
        payload=event.payload,
        created_at=event.created_at,
    )
    await realtime_hub.publish_conversation_event(
        payload.conversation_id, realtime_payload
    )

    return {
        "deleted": True,
        "scope": "global",
        "message_ids": deleted_ids,
    }
