from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_log
from app.core.exceptions import BadRequestError, ConflictError, GoneError, NotFoundError
from app.core.realtime import realtime_hub
from app.models.chat_enums import EventType
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
    ListConversationsResponseData,
    UpdateConversationRequest,
)

users_repo = UsersRepository()
conversations_repo = ConversationsRepository()
messages_repo = MessagesRepository()
files_repo = FilesRepository()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _enqueue_recompute_unread(user_id: int) -> None:
    try:
        from app.worker.tasks import recompute_unread_counters_for_user_task

        recompute_unread_counters_for_user_task.delay(user_id)
    except Exception:
        return


def _peer_user_id(
    conversation_user_a_id: int,
    conversation_user_b_id: int,
    current_user_id: int,
) -> int:
    if conversation_user_a_id == current_user_id:
        return conversation_user_b_id
    return conversation_user_a_id


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


async def create_conversation(
    session: AsyncSession,
    *,
    current_user: User,
    payload: CreateConversationRequest,
) -> dict:
    if payload.recipient_user_id == current_user.id:
        raise BadRequestError(
            code="SELF_CONVERSATION_NOT_ALLOWED",
            message="Cannot create conversation with yourself",
        )

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
    }


async def list_conversations(
    session: AsyncSession,
    *,
    current_user: User,
) -> ListConversationsResponseData:
    rows = await conversations_repo.list_overview_for_user(
        session,
        user_id=current_user.id,
    )

    items: list[ConversationListItemSchema] = []
    for row in rows:
        conversation = row["conversation"]
        last_message = row["last_message"]

        last_message_schema = None
        if last_message is not None:
            last_message_schema = ConversationLastMessageSchema(
                message_id=last_message.id,
                message_uuid=last_message.message_uuid,
                sender_user_id=last_message.sender_user_id,
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
                title=conversation.title,
                protection_mode=conversation.protection_mode,
                message_ttl_days=conversation.message_ttl_days,
                delete_after_read_seconds=conversation.delete_after_read_seconds,
                is_active=conversation.is_active,
                is_purged=conversation.is_purged,
                updated_at=conversation.updated_at,
                peer=ConversationPeerSchema(
                    user_id=row["peer_user_id"],
                    nickname=row["peer_nickname"],
                ),
                unread_count=row["unread_count"],
                last_message=last_message_schema,
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

    return {
        "conversation_id": conversation.id,
        "conversation_uuid": conversation.conversation_uuid,
        "title": conversation.title,
        "peer_user_id": _peer_user_id(
            conversation.user_a_id,
            conversation.user_b_id,
            current_user.id,
        ),
        "protection_mode": conversation.protection_mode.value,
        "message_ttl_days": conversation.message_ttl_days,
        "delete_after_read_seconds": conversation.delete_after_read_seconds,
        "is_active": conversation.is_active,
        "is_purged": conversation.is_purged,
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
    await realtime_hub.publish_user_event(peer_user_id, realtime_payload)

    return {
        "conversation_id": conversation_id,
        "scope": "global",
        "cleared": True,
        "deleted_messages_count": deleted_count,
        "deleted_attachment_ids": deleted_attachment_ids,
    }
