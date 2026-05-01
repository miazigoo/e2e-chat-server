from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_log
from app.core.exceptions import BadRequestError, ConflictError, GoneError, NotFoundError
from app.core.realtime import realtime_hub
from app.core.task_dispatch import dispatch_background_task
from app.models.chat_enums import EventType, ProtectionMode
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.user import User
from app.repositories.conversations import ConversationsRepository
from app.repositories.files import FilesRepository
from app.repositories.messages import MessagesRepository
from app.repositories.users import UsersRepository
from app.schemas.conversations import (
    ClearConversationRequest,
    ConversationLastMessageSchema,
    ConversationListItemSchema,
    ConversationPeerSchema,
    CreateConversationRequest,
    DeleteConversationResponseData,
    ListConversationsResponseData,
    PinConversationResponseData,
    UpdateConversationRequest,
    UpdateConversationSettingsRequest,
)
from app.schemas.messages import MessagePreviewSchema

users_repo = UsersRepository()
conversations_repo = ConversationsRepository()
messages_repo = MessagesRepository()
files_repo = FilesRepository()
SAVED_MESSAGES_TITLE = "Избранное"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _enqueue_recompute_unread(user_id: int) -> None:
    try:
        from app.worker.tasks import recompute_unread_counters_for_user_task
    except Exception:
        return

    dispatch_background_task(
        task_name="recompute_unread_counters_for_user_task",
        dispatcher=recompute_unread_counters_for_user_task.delay,
        args=(user_id,),
        extra={"user_id": user_id},
    )


def _peer_user_id(
    conversation_user_a_id: int,
    conversation_user_b_id: int,
    current_user_id: int,
) -> int:
    if conversation_user_a_id == current_user_id:
        return conversation_user_b_id
    return conversation_user_a_id


def _display_title(title: str | None, *, is_saved_messages: bool) -> str | None:
    if is_saved_messages:
        return SAVED_MESSAGES_TITLE
    return title


def _is_self_conversation(*, conversation: Conversation) -> bool:
    return (
        conversation.is_saved_messages
        or conversation.user_a_id == conversation.user_b_id
    )


async def _get_or_create_saved_messages(
    session: AsyncSession,
    *,
    current_user: User,
    message_ttl_days: int | None = 60,
    delete_after_read_seconds: int | None = None,
) -> tuple[Conversation, bool]:
    existing = await conversations_repo.get_saved_messages_for_user(
        session,
        user_id=current_user.id,
    )
    if existing is not None:
        return existing, False

    conversation = await conversations_repo.create_conversation(
        session,
        user_a_id=current_user.id,
        user_b_id=current_user.id,
        created_by_user_id=current_user.id,
        title=SAVED_MESSAGES_TITLE,
        protection_mode=ProtectionMode.NORMAL,
        message_ttl_days=message_ttl_days,
        delete_after_read_seconds=delete_after_read_seconds,
        is_saved_messages=True,
    )
    return conversation, True


def _ensure_conversation_mutable(*, is_purged: bool, is_active: bool) -> None:
    if is_purged:
        raise GoneError(
            code="CONVERSATION_PURGED",
            message="Conversation is purged",
        )

    if not is_active:
        raise ConflictError(
            code="CONVERSATION_INACTIVE",
            message="Conversation is inactive",
        )


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


def _preview_from_message(message: Message | None) -> MessagePreviewSchema | None:
    if message is None:
        return None
    return MessagePreviewSchema(
        message_id=message.id,
        message_uuid=message.message_uuid,
        sender_user_id=message.sender_user_id,
        sender_device_id=message.sender_device_id,
        message_type=message.message_type,
        ciphertext=message.ciphertext,
        has_attachments=message.has_attachments,
        client_created_at=message.client_created_at,
    )


async def create_conversation(
    session: AsyncSession,
    *,
    current_user: User,
    payload: CreateConversationRequest,
) -> dict:
    if payload.recipient_user_id == current_user.id:
        conversation, created = await _get_or_create_saved_messages(
            session,
            current_user=current_user,
            message_ttl_days=payload.message_ttl_days,
            delete_after_read_seconds=payload.delete_after_read_seconds,
        )
        if created:
            await session.commit()

        return {
            "conversation_id": conversation.id,
            "conversation_uuid": conversation.conversation_uuid,
            "recipient_user_id": current_user.id,
            "protection_mode": conversation.protection_mode.value,
            "is_saved_messages": True,
        }

    recipient = await users_repo.get_by_id(session, payload.recipient_user_id)
    if not recipient or recipient.is_deleted or recipient.pending_deletion:
        raise NotFoundError(
            code="RECIPIENT_NOT_FOUND",
            message="Recipient not found",
        )

    conversation = await conversations_repo.create_conversation(
        session,
        user_a_id=current_user.id,
        user_b_id=recipient.id,
        created_by_user_id=current_user.id,
        title=payload.title,
        protection_mode=payload.protection_mode,
        message_ttl_days=payload.message_ttl_days,
        delete_after_read_seconds=payload.delete_after_read_seconds,
    )

    await session.commit()

    return {
        "conversation_id": conversation.id,
        "conversation_uuid": conversation.conversation_uuid,
        "recipient_user_id": recipient.id,
        "protection_mode": conversation.protection_mode.value,
        "is_saved_messages": False,
    }


async def list_conversations(
    session: AsyncSession,
    *,
    current_user: User,
) -> ListConversationsResponseData:
    _, created_saved_messages = await _get_or_create_saved_messages(
        session,
        current_user=current_user,
    )
    if created_saved_messages:
        await session.commit()

    rows = await conversations_repo.list_overview_for_user(
        session,
        user_id=current_user.id,
    )

    items: list[ConversationListItemSchema] = []
    for row in rows:
        conversation = row["conversation"]
        last_message = row["last_message"]
        participant = row.get("participant")
        peer_participant = row.get("peer_participant")

        last_message_schema = None
        if last_message is not None:
            last_message_schema = ConversationLastMessageSchema(
                message_id=last_message.id,
                message_uuid=last_message.message_uuid,
                sender_user_id=last_message.sender_user_id,
                sender_device_id=last_message.sender_device_id,
                recipient_user_id=last_message.recipient_user_id,
                message_type=last_message.message_type.value,
                client_created_at=last_message.client_created_at,
                server_received_at=last_message.server_received_at,
                has_attachments=last_message.has_attachments,
            )

        items.append(
            ConversationListItemSchema(
                conversation_id=conversation.id,
                conversation_uuid=conversation.conversation_uuid,
                title=_display_title(
                    conversation.title,
                    is_saved_messages=conversation.is_saved_messages,
                ),
                is_saved_messages=conversation.is_saved_messages,
                protection_mode=conversation.protection_mode,
                message_ttl_days=conversation.message_ttl_days,
                delete_after_read_seconds=conversation.delete_after_read_seconds,
                shared_secret_enabled=(
                    participant.shared_secret_enabled
                    if participant is not None
                    else False
                ),
                shared_secret_fingerprint=(
                    participant.shared_secret_fingerprint
                    if participant is not None
                    else None
                ),
                shared_secret_updated_at=(
                    participant.shared_secret_updated_at
                    if participant is not None
                    else None
                ),
                peer_shared_secret_enabled=(
                    peer_participant.shared_secret_enabled
                    if peer_participant is not None
                    else False
                ),
                is_active=conversation.is_active,
                is_purged=conversation.is_purged,
                is_pinned=(participant.is_pinned if participant is not None else False),
                updated_at=conversation.updated_at,
                peer=ConversationPeerSchema(
                    user_id=row["peer_user_id"],
                    nickname=row["peer_nickname"],
                ),
                unread_count=row["unread_count"],
                last_message=last_message_schema,
                pinned_message=_preview_from_message(row.get("pinned_message")),
            )
        )

    return ListConversationsResponseData(items=items)


async def get_conversation(
    session: AsyncSession,
    *,
    current_user: User,
    conversation_id: int,
) -> dict:
    conversation = await conversations_repo.get_for_user(
        session,
        conversation_id=conversation_id,
        user_id=current_user.id,
    )
    if not conversation:
        raise NotFoundError(
            code="CONVERSATION_NOT_FOUND",
            message="Conversation not found",
        )

    participant = await conversations_repo.get_participant(
        session,
        conversation_id=conversation_id,
        user_id=current_user.id,
    )
    peer_user_id = _peer_user_id(
        conversation.user_a_id,
        conversation.user_b_id,
        current_user.id,
    )
    peer_participant = await conversations_repo.get_participant(
        session,
        conversation_id=conversation_id,
        user_id=peer_user_id,
    )
    pinned_message = None
    if conversation.pinned_message_id is not None:
        pinned_message = await messages_repo.get_by_id_in_conversation(
            session,
            message_id=conversation.pinned_message_id,
            conversation_id=conversation_id,
        )

    return {
        "conversation_id": conversation.id,
        "conversation_uuid": conversation.conversation_uuid,
        "title": _display_title(
            conversation.title,
            is_saved_messages=conversation.is_saved_messages,
        ),
        "peer_user_id": peer_user_id,
        "is_saved_messages": conversation.is_saved_messages,
        "protection_mode": conversation.protection_mode.value,
        "message_ttl_days": conversation.message_ttl_days,
        "delete_after_read_seconds": conversation.delete_after_read_seconds,
        "shared_secret_enabled": (
            participant.shared_secret_enabled if participant is not None else False
        ),
        "shared_secret_fingerprint": (
            participant.shared_secret_fingerprint if participant is not None else None
        ),
        "shared_secret_updated_at": (
            participant.shared_secret_updated_at if participant is not None else None
        ),
        "peer_shared_secret_enabled": (
            peer_participant.shared_secret_enabled
            if peer_participant is not None
            else False
        ),
        "is_active": conversation.is_active,
        "is_purged": conversation.is_purged,
        "is_pinned": participant.is_pinned if participant is not None else False,
        "pinned_message": (
            _preview_from_message(pinned_message)
            if pinned_message is not None
            else None
        ),
    }


async def update_conversation(
    session: AsyncSession,
    *,
    current_user: User,
    conversation_id: int,
    payload: UpdateConversationRequest,
) -> dict:
    conversation = await conversations_repo.get_for_user(
        session,
        conversation_id=conversation_id,
        user_id=current_user.id,
    )
    if not conversation:
        raise NotFoundError(
            code="CONVERSATION_NOT_FOUND",
            message="Conversation not found",
        )

    _ensure_conversation_mutable(
        is_purged=conversation.is_purged,
        is_active=conversation.is_active,
    )

    await conversations_repo.update_conversation(
        session,
        conversation=conversation,
        title=payload.title,
        message_ttl_days=payload.message_ttl_days,
        delete_after_read_seconds=payload.delete_after_read_seconds,
    )

    await session.commit()

    return {
        "conversation_id": conversation.id,
        "updated": True,
    }


async def update_conversation_settings(
    session: AsyncSession,
    *,
    current_user: User,
    conversation_id: int,
    payload: UpdateConversationSettingsRequest,
) -> dict:
    conversation = await conversations_repo.get_for_user(
        session,
        conversation_id=conversation_id,
        user_id=current_user.id,
    )
    if not conversation:
        raise NotFoundError(
            code="CONVERSATION_NOT_FOUND",
            message="Conversation not found",
        )

    _ensure_conversation_mutable(
        is_purged=conversation.is_purged,
        is_active=conversation.is_active,
    )

    participant = await conversations_repo.get_participant(
        session,
        conversation_id=conversation_id,
        user_id=current_user.id,
    )
    if participant is None:
        raise NotFoundError(
            code="CONVERSATION_NOT_FOUND",
            message="Conversation not found",
        )

    if (
        payload.shared_secret_enabled is None
        and payload.shared_secret_fingerprint is not None
        and not participant.shared_secret_enabled
    ):
        raise BadRequestError(
            code="SHARED_SECRET_DISABLED",
            message="Enable shared secret before setting its fingerprint",
        )

    updated_at = _now()
    participant = await conversations_repo.update_participant_settings(
        session,
        participant=participant,
        shared_secret_enabled=payload.shared_secret_enabled,
        shared_secret_fingerprint=payload.shared_secret_fingerprint,
        updated_at=updated_at,
    )

    event = await conversations_repo.create_event(
        session,
        conversation_id=conversation_id,
        actor_user_id=current_user.id,
        actor_device_id=None,
        event_type=EventType.CONVERSATION_SETTINGS_UPDATED,
        payload={
            "user_id": current_user.id,
            "shared_secret_enabled": participant.shared_secret_enabled,
            "shared_secret_updated_at": updated_at.isoformat(),
        },
    )

    await session.commit()

    audit_log(
        "conversation_settings_updated",
        user_id=current_user.id,
        conversation_id=conversation_id,
        extra={"shared_secret_enabled": participant.shared_secret_enabled},
    )

    realtime_payload = _event_to_realtime_payload(
        conversation_id=conversation_id,
        event_type=event.event_type.value,
        event_id=event.id,
        event_uuid=event.event_uuid,
        actor_user_id=event.actor_user_id,
        actor_device_id=event.actor_device_id,
        target_message_id=event.target_message_id,
        payload=event.payload,
        created_at=event.created_at,
    )
    await realtime_hub.publish_conversation_event(conversation_id, realtime_payload)

    return {
        "conversation_id": conversation_id,
        "user_id": current_user.id,
        "shared_secret_enabled": participant.shared_secret_enabled,
        "shared_secret_fingerprint": participant.shared_secret_fingerprint,
        "shared_secret_updated_at": participant.shared_secret_updated_at,
    }


async def clear_local(
    session: AsyncSession,
    *,
    current_user: User,
    conversation_id: int,
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

    conversation = await conversations_repo.get_for_user(
        session,
        conversation_id=conversation_id,
        user_id=current_user.id,
    )
    if conversation is None:
        raise NotFoundError(
            code="CONVERSATION_NOT_FOUND",
            message="Conversation not found",
        )

    _ensure_conversation_mutable(
        is_purged=conversation.is_purged,
        is_active=conversation.is_active,
    )

    cleared_at = _now()
    await conversations_repo.clear_local_for_user(
        session,
        participant=participant,
        cleared_at=cleared_at,
    )
    event = await conversations_repo.create_event(
        session,
        conversation_id=conversation_id,
        actor_user_id=current_user.id,
        actor_device_id=None,
        event_type=EventType.CONVERSATION_CLEARED_LOCAL,
        payload={"scope": "local"},
    )

    await conversations_repo.touch_conversation(
        session,
        conversation=conversation,
        touched_at=cleared_at,
    )

    await session.commit()

    audit_log(
        "conversation_cleared_local",
        user_id=current_user.id,
        conversation_id=conversation_id,
    )
    _enqueue_recompute_unread(current_user.id)

    realtime_payload = _event_to_realtime_payload(
        conversation_id=conversation_id,
        event_type=event.event_type.value,
        event_id=event.id,
        event_uuid=event.event_uuid,
        actor_user_id=event.actor_user_id,
        actor_device_id=event.actor_device_id,
        target_message_id=event.target_message_id,
        payload=event.payload,
        created_at=event.created_at,
    )
    await realtime_hub.publish_conversation_event(conversation_id, realtime_payload)

    return {
        "conversation_id": conversation_id,
        "scope": "local",
        "cleared": True,
        "cleared_at": cleared_at.isoformat(),
    }


async def clear_global(
    session: AsyncSession,
    *,
    current_user: User,
    conversation_id: int,
    payload: ClearConversationRequest,
) -> dict:
    conversation = await conversations_repo.get_for_user(
        session,
        conversation_id=conversation_id,
        user_id=current_user.id,
    )
    if not conversation:
        raise NotFoundError(
            code="CONVERSATION_NOT_FOUND",
            message="Conversation not found",
        )

    _ensure_conversation_mutable(
        is_purged=conversation.is_purged,
        is_active=conversation.is_active,
    )

    now_dt = _now()

    message_ids_result = await session.execute(
        select(Message.id).where(
            Message.conversation_id == conversation_id,
            Message.is_deleted_global.is_(False),
        )
    )
    message_ids = list(message_ids_result.scalars().all())

    deleted_count = await messages_repo.clear_global_conversation(
        session,
        conversation_id=conversation_id,
        actor_user_id=current_user.id,
        deleted_at=now_dt,
    )

    attachments = await files_repo.list_by_message_ids(
        session,
        message_ids=message_ids,
    )
    deleted_attachment_ids = await files_repo.mark_attachments_deleted(
        session,
        attachments=attachments,
        deleted_at=now_dt,
    )

    event = await conversations_repo.create_event(
        session,
        conversation_id=conversation_id,
        actor_user_id=current_user.id,
        actor_device_id=None,
        event_type=EventType.CONVERSATION_CLEARED_GLOBAL,
        payload={
            "scope": "global",
            "reason": payload.reason,
            "deleted_messages_count": deleted_count,
            "deleted_attachment_ids": deleted_attachment_ids,
        },
    )
    if conversation.pinned_message_id is not None:
        await conversations_repo.set_pinned_message(
            session,
            conversation=conversation,
            message_id=None,
        )

    await conversations_repo.touch_conversation(
        session,
        conversation=conversation,
        touched_at=now_dt,
    )

    await session.commit()

    peer_user_id = _peer_user_id(
        conversation.user_a_id,
        conversation.user_b_id,
        current_user.id,
    )

    audit_log(
        "conversation_cleared_global",
        user_id=current_user.id,
        conversation_id=conversation_id,
        extra={
            "deleted_messages_count": deleted_count,
            "deleted_attachment_ids": deleted_attachment_ids,
        },
    )
    _enqueue_recompute_unread(current_user.id)
    if not _is_self_conversation(conversation=conversation):
        _enqueue_recompute_unread(peer_user_id)

    realtime_payload = _event_to_realtime_payload(
        conversation_id=conversation_id,
        event_type=event.event_type.value,
        event_id=event.id,
        event_uuid=event.event_uuid,
        actor_user_id=event.actor_user_id,
        actor_device_id=event.actor_device_id,
        target_message_id=event.target_message_id,
        payload=event.payload,
        created_at=event.created_at,
    )
    await realtime_hub.publish_conversation_event(conversation_id, realtime_payload)
    if not _is_self_conversation(conversation=conversation):
        await realtime_hub.publish_user_event(peer_user_id, realtime_payload)

    return {
        "conversation_id": conversation_id,
        "scope": "global",
        "cleared": True,
        "deleted_messages_count": deleted_count,
        "deleted_attachment_ids": deleted_attachment_ids,
    }


async def pin_conversation(
    session: AsyncSession,
    *,
    current_user: User,
    conversation_id: int,
    is_pinned: bool,
) -> PinConversationResponseData:
    conversation = await conversations_repo.get_for_user(
        session,
        conversation_id=conversation_id,
        user_id=current_user.id,
    )
    if not conversation:
        raise NotFoundError(
            code="CONVERSATION_NOT_FOUND",
            message="Conversation not found",
        )

    _ensure_conversation_mutable(
        is_purged=conversation.is_purged,
        is_active=conversation.is_active,
    )

    participant = await conversations_repo.get_participant(
        session,
        conversation_id=conversation_id,
        user_id=current_user.id,
    )
    if participant is None:
        raise NotFoundError(
            code="CONVERSATION_NOT_FOUND",
            message="Conversation not found",
        )

    pinned_at = _now() if is_pinned else None
    await conversations_repo.update_participant_pin_state(
        session,
        participant=participant,
        is_pinned=is_pinned,
        pinned_at=pinned_at,
    )
    await session.commit()

    event_type = (
        EventType.CONVERSATION_PINNED if is_pinned else EventType.CONVERSATION_UNPINNED
    )
    realtime_payload = _event_to_realtime_payload(
        conversation_id=conversation_id,
        event_type=event_type.value,
        event_id=0,
        event_uuid=str(uuid4()),
        actor_user_id=current_user.id,
        actor_device_id=None,
        target_message_id=None,
        payload={"is_pinned": is_pinned},
        created_at=pinned_at or _now(),
    )
    await realtime_hub.publish_user_event(current_user.id, realtime_payload)

    return PinConversationResponseData(
        conversation_id=conversation_id,
        is_pinned=is_pinned,
    )


async def delete_conversation(
    session: AsyncSession,
    *,
    current_user: User,
    conversation_id: int,
) -> DeleteConversationResponseData:
    conversation = await conversations_repo.get_for_user(
        session,
        conversation_id=conversation_id,
        user_id=current_user.id,
    )
    if not conversation:
        raise NotFoundError(
            code="CONVERSATION_NOT_FOUND",
            message="Conversation not found",
        )

    if conversation.is_saved_messages:
        raise BadRequestError(
            code="SAVED_MESSAGES_DELETE_NOT_ALLOWED",
            message="Saved messages chat cannot be deleted",
        )

    _ensure_conversation_mutable(
        is_purged=conversation.is_purged,
        is_active=conversation.is_active,
    )

    message_ids_result = await session.execute(
        select(Message.id).where(Message.conversation_id == conversation_id)
    )
    message_ids = list(message_ids_result.scalars().all())
    attachments = await files_repo.list_by_conversation_id(
        session,
        conversation_id=conversation_id,
    )
    deleted_attachment_ids = sorted({attachment.id for attachment in attachments})
    deleted_messages_count = len(message_ids)

    if deleted_attachment_ids:
        await files_repo.delete_attachments(
            session,
            attachment_ids=deleted_attachment_ids,
        )
    await conversations_repo.delete_conversation(
        session,
        conversation=conversation,
    )
    await session.commit()

    peer_user_id = _peer_user_id(
        conversation.user_a_id,
        conversation.user_b_id,
        current_user.id,
    )

    audit_log(
        "conversation_deleted",
        user_id=current_user.id,
        conversation_id=conversation_id,
        extra={
            "deleted_messages_count": deleted_messages_count,
            "deleted_attachment_ids": deleted_attachment_ids,
        },
    )
    _enqueue_recompute_unread(current_user.id)
    if not _is_self_conversation(conversation=conversation):
        _enqueue_recompute_unread(peer_user_id)

    realtime_payload = _event_to_realtime_payload(
        conversation_id=conversation_id,
        event_type=EventType.CONVERSATION_DELETED.value,
        event_id=0,
        event_uuid=str(uuid4()),
        actor_user_id=current_user.id,
        actor_device_id=None,
        target_message_id=None,
        payload={
            "deleted": True,
            "deleted_messages_count": deleted_messages_count,
            "deleted_attachment_ids": deleted_attachment_ids,
        },
        created_at=_now(),
    )
    await realtime_hub.publish_user_event(current_user.id, realtime_payload)
    await realtime_hub.publish_user_event(peer_user_id, realtime_payload)

    return DeleteConversationResponseData(
        conversation_id=conversation_id,
        deleted=True,
        deleted_messages_count=deleted_messages_count,
        deleted_attachment_ids=deleted_attachment_ids,
    )
