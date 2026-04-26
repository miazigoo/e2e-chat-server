from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, TypedDict
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import audit_log
from app.core.exceptions import BadRequestError, ConflictError, GoneError, NotFoundError
from app.core.realtime import realtime_hub
from app.core.storage import copy_object
from app.core.task_dispatch import dispatch_background_task
from app.models.chat_enums import (
    EncryptionMode,
    EventType,
    MessageType,
    VisibilityReason,
)
from app.models.device import Device
from app.models.user import User
from app.repositories.conversations import ConversationsRepository
from app.repositories.devices import DevicesRepository
from app.repositories.files import FilesRepository
from app.repositories.messages import MessagesRepository
from app.schemas.messages import (
    DeleteMessagesRequest,
    ForwardMessagesRequest,
    MarkDeliveredRequest,
    MarkReadRequest,
    MessageListItemSchema,
    MessagePreviewSchema,
    MessageReactionSummarySchema,
    PinMessageResponseData,
    SearchMessagesResponseData,
    SendMessageRequest,
    SetMessageReactionRequest,
    SharedMessagesResponseData,
    SharedTabCountsSchema,
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
    except Exception:
        return

    dispatch_background_task(
        task_name="send_new_message_push_task",
        dispatcher=send_new_message_push_task.delay,
        args=(user_id, conversation_id, message_id),
        extra={
            "user_id": user_id,
            "conversation_id": conversation_id,
            "message_id": message_id,
        },
    )


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


def _other_participant_id(
    conversation_user_a_id: int,
    conversation_user_b_id: int,
    current_user_id: int,
) -> int:
    if conversation_user_a_id == current_user_id:
        return conversation_user_b_id
    return conversation_user_a_id


def _is_self_conversation(*, conversation: Any) -> bool:
    return bool(
        getattr(conversation, "is_saved_messages", False)
        or conversation.user_a_id == conversation.user_b_id
    )


def _resolve_expires_at(
    *,
    explicit_expires_at: datetime | None,
    conversation_ttl_days: int | None,
    now_dt: datetime | None = None,
) -> datetime:
    if explicit_expires_at is not None:
        return explicit_expires_at

    reference_now = now_dt or _now()
    ttl_days = conversation_ttl_days or 60
    return reference_now + timedelta(days=ttl_days)


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


def _validate_client_message_payload(payload: SendMessageRequest) -> None:
    if payload.message_type == MessageType.SERVICE:
        raise BadRequestError(
            code="CLIENT_MESSAGE_TYPE_NOT_ALLOWED",
            message="Clients cannot send service messages",
        )

    if payload.message_type == MessageType.FILE and not payload.attachment_ids:
        raise BadRequestError(
            code="FILE_MESSAGE_REQUIRES_ATTACHMENTS",
            message="File messages must include attachment_ids",
        )


def _validate_encryption_mode_for_participant(
    *,
    shared_secret_enabled: bool,
    encryption_mode: EncryptionMode,
) -> None:
    if (
        shared_secret_enabled
        and encryption_mode != EncryptionMode.SIGNAL_PLUS_SHARED_SECRET
    ):
        raise BadRequestError(
            code="INVALID_ENCRYPTION_MODE",
            message=(
                "Shared secret chat setting requires signal_plus_shared_secret mode"
            ),
        )

    if not shared_secret_enabled and encryption_mode != EncryptionMode.SIGNAL:
        raise BadRequestError(
            code="INVALID_ENCRYPTION_MODE",
            message="Normal chat setting requires signal encryption mode",
        )


class ReactionSummary(TypedDict):
    reaction: str
    count: int
    me: bool


def _build_reaction_summaries(
    reactions: list[Any],
    *,
    current_user_id: int,
) -> list[MessageReactionSummarySchema]:
    summaries: dict[str, ReactionSummary] = {}

    for reaction in reactions:
        reaction_value = str(reaction.reaction)
        summary = summaries.setdefault(
            reaction_value,
            {"reaction": reaction_value, "count": 0, "me": False},
        )
        summary["count"] += 1
        if reaction.user_id == current_user_id:
            summary["me"] = True

    return [
        MessageReactionSummarySchema(
            reaction=str(item["reaction"]),
            count=int(item["count"]),
            me=bool(item["me"]),
        )
        for item in sorted(
            summaries.values(),
            key=lambda item: (-item["count"], item["reaction"]),
        )
    ]


async def _get_reactable_message(
    session: AsyncSession,
    *,
    current_user: User,
    message_id: int,
) -> tuple[Any, Any]:
    message = await messages_repo.get_by_id(session, message_id=message_id)
    if message is None:
        raise NotFoundError(
            code="MESSAGE_NOT_FOUND",
            message="Message not found",
        )

    conversation = await conversations_repo.get_for_user(
        session,
        conversation_id=message.conversation_id,
        user_id=current_user.id,
    )
    if conversation is None:
        raise NotFoundError(
            code="MESSAGE_NOT_FOUND",
            message="Message not found",
        )

    _ensure_conversation_mutable(
        is_purged=conversation.is_purged,
        is_active=conversation.is_active,
    )

    hidden = await messages_repo.is_hidden_for_user(
        session,
        message_id=message.id,
        user_id=current_user.id,
    )
    if hidden:
        raise NotFoundError(
            code="MESSAGE_NOT_FOUND",
            message="Message not found",
        )

    return message, conversation


def _preview_from_message(message: Any) -> MessagePreviewSchema:
    return MessagePreviewSchema(
        message_id=message.id,
        message_uuid=message.message_uuid,
        sender_user_id=message.sender_user_id,
        message_type=message.message_type,
        ciphertext=message.ciphertext,
        has_attachments=message.has_attachments,
        client_created_at=message.client_created_at,
    )


async def _build_message_items(
    session: AsyncSession,
    *,
    current_user: User,
    messages: list[Any],
) -> list[MessageListItemSchema]:
    if not messages:
        return []

    message_ids = [message.id for message in messages]
    reactions = await messages_repo.list_reactions_for_messages(
        session,
        message_ids=message_ids,
    )
    reactions_by_message_id: dict[int, list[Any]] = defaultdict(list)
    for reaction in reactions:
        reactions_by_message_id[reaction.message_id].append(reaction)

    preview_ids = {
        preview_id
        for message in messages
        for preview_id in (message.reply_to_message_id, message.forward_from_message_id)
        if preview_id is not None
    }
    previews_by_id: dict[int, Any] = {}
    if preview_ids:
        previews = await messages_repo.list_by_ids(
            session,
            message_ids=list(preview_ids),
        )
        previews_by_id = {message.id: message for message in previews}

    return [
        MessageListItemSchema(
            message_id=message.id,
            message_uuid=message.message_uuid,
            sender_user_id=message.sender_user_id,
            recipient_user_id=message.recipient_user_id,
            message_type=message.message_type,
            ciphertext=message.ciphertext,
            ciphertext_version=message.ciphertext_version,
            encryption_mode=message.encryption_mode,
            nonce=message.nonce,
            aad_hash=message.aad_hash,
            client_created_at=message.client_created_at,
            server_received_at=message.server_received_at,
            delivered_at=message.delivered_at,
            read_at=message.read_at,
            expires_at=message.expires_at,
            has_attachments=message.has_attachments,
            reply_to_message_id=message.reply_to_message_id,
            forward_from_message_id=message.forward_from_message_id,
            reply_preview=(
                _preview_from_message(previews_by_id[message.reply_to_message_id])
                if message.reply_to_message_id in previews_by_id
                else None
            ),
            forward_preview=(
                _preview_from_message(previews_by_id[message.forward_from_message_id])
                if message.forward_from_message_id in previews_by_id
                else None
            ),
            reactions=_build_reaction_summaries(
                reactions_by_message_id[message.id],
                current_user_id=current_user.id,
            ),
        )
        for message in messages
    ]


async def _clone_forward_attachments(
    session: AsyncSession,
    *,
    source_message_id: int,
    target_message_id: int,
) -> None:
    source_attachments = await files_repo.list_by_message_id(
        session,
        message_id=source_message_id,
    )
    for attachment in source_attachments:
        storage_key = f"attachments/forwards/{target_message_id}/{uuid4()}"
        await copy_object(
            src_bucket_name=attachment.bucket_name,
            src_object_name=attachment.storage_key,
            dst_bucket_name=attachment.bucket_name,
            dst_object_name=storage_key,
        )
        await files_repo.clone_attachment(
            session,
            source_attachment=attachment,
            message_id=target_message_id,
            storage_key=storage_key,
        )


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

    _ensure_conversation_mutable(
        is_purged=conversation.is_purged,
        is_active=conversation.is_active,
    )

    _validate_client_message_payload(payload)

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

    participant = await conversations_repo.get_participant(
        session,
        conversation_id=conversation.id,
        user_id=current_user.id,
    )
    if participant is None:
        raise NotFoundError(
            code="CONVERSATION_NOT_FOUND",
            message="Conversation not found",
        )

    _validate_encryption_mode_for_participant(
        shared_secret_enabled=participant.shared_secret_enabled,
        encryption_mode=payload.encryption_mode,
    )

    recipient_device = await devices_repo.get_active_by_user_id(
        session,
        user_id=payload.recipient_user_id,
    )
    if _is_self_conversation(conversation=conversation):
        recipient_device = current_device
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

    if payload.client_created_at > now_dt + timedelta(minutes=5):
        raise BadRequestError(
            code="INVALID_CLIENT_CREATED_AT",
            message="client_created_at is too far in the future",
        )

    expires_at = _resolve_expires_at(
        explicit_expires_at=payload.expires_at,
        conversation_ttl_days=conversation.message_ttl_days,
        now_dt=now_dt,
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

    existing_message = await messages_repo.get_by_message_uuid(
        session,
        conversation_id=conversation.id,
        sender_user_id=current_user.id,
        message_uuid=payload.message_uuid,
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
        forward_from_message_id=None,
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

    recipient_state = await messages_repo.create_recipient_state(
        session,
        message_id=message.id,
        recipient_user_id=payload.recipient_user_id,
        recipient_device_id=recipient_device.id,
    )
    if _is_self_conversation(conversation=conversation):
        await messages_repo.mark_delivered(
            session,
            message=message,
            state=recipient_state,
            delivered_at=now_dt,
        )
        await messages_repo.mark_read(
            session,
            message=message,
            state=recipient_state,
            read_at=now_dt,
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
            "reply_to_message_id": message.reply_to_message_id,
            "forward_from_message_id": None,
            "sender_user_id": message.sender_user_id,
            "sender_device_id": message.sender_device_id,
            "recipient_user_id": message.recipient_user_id,
            "recipient_device_id": message.recipient_device_id,
            "message_type": message.message_type.value,
            "encryption_mode": message.encryption_mode.value,
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

    if not _is_self_conversation(conversation=conversation):
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
    if not _is_self_conversation(conversation=conversation):
        await realtime_hub.publish_user_event(
            payload.recipient_user_id,
            realtime_payload,
        )

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
    return {
        "items": await _build_message_items(
            session,
            current_user=current_user,
            messages=ordered_messages,
        )
    }


async def search_messages(
    session: AsyncSession,
    *,
    current_user: User,
    conversation_id: int,
    query: str,
    limit: int,
) -> SearchMessagesResponseData:
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

    normalized_query = query.strip()
    if not normalized_query:
        return SearchMessagesResponseData(
            conversation_id=conversation_id,
            query="",
            items=[],
        )

    messages = await messages_repo.search_in_conversation_for_user(
        session,
        conversation_id=conversation_id,
        user_id=current_user.id,
        query=normalized_query,
        limit=limit,
        cleared_at=participant.cleared_at,
    )

    return SearchMessagesResponseData(
        conversation_id=conversation_id,
        query=normalized_query,
        items=await _build_message_items(
            session,
            current_user=current_user,
            messages=messages,
        ),
    )


async def list_shared_messages(
    session: AsyncSession,
    *,
    current_user: User,
    conversation_id: int,
    tab: str,
    before_message_id: int | None,
    limit: int,
) -> SharedMessagesResponseData:
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

    normalized_tab = tab.strip().lower()
    if normalized_tab not in {"media", "links", "files"}:
        raise BadRequestError(
            code="INVALID_SHARED_TAB",
            message="tab must be one of: media, links, files",
        )

    messages = await messages_repo.list_shared_messages_for_user(
        session,
        conversation_id=conversation_id,
        user_id=current_user.id,
        tab=normalized_tab,
        before_message_id=before_message_id,
        limit=limit,
        cleared_at=participant.cleared_at,
    )
    counts = await messages_repo.get_shared_counts_for_user(
        session,
        conversation_id=conversation_id,
        user_id=current_user.id,
        cleared_at=participant.cleared_at,
    )

    return SharedMessagesResponseData(
        conversation_id=conversation_id,
        tab=normalized_tab,
        counts=SharedTabCountsSchema(**counts),
        items=await _build_message_items(
            session,
            current_user=current_user,
            messages=messages,
        ),
    )


async def forward_messages(
    session: AsyncSession,
    *,
    current_user: User,
    current_device: Device,
    payload: ForwardMessagesRequest,
) -> dict[str, Any]:
    conversation = await conversations_repo.get_for_user(
        session,
        conversation_id=payload.conversation_id,
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

    participant = await conversations_repo.get_participant(
        session,
        conversation_id=conversation.id,
        user_id=current_user.id,
    )
    if participant is None:
        raise NotFoundError(
            code="CONVERSATION_NOT_FOUND",
            message="Conversation not found",
        )

    recipient_device = await devices_repo.get_active_by_user_id(
        session,
        user_id=payload.recipient_user_id,
    )
    if _is_self_conversation(conversation=conversation):
        recipient_device = current_device
    if recipient_device is None:
        raise ConflictError(
            code="RECIPIENT_DEVICE_NOT_READY",
            message="Recipient has no active device",
        )

    client_created_at = payload.client_created_at or _now()
    if client_created_at > _now() + timedelta(minutes=5):
        raise BadRequestError(
            code="INVALID_CLIENT_CREATED_AT",
            message="client_created_at is too far in the future",
        )

    created_items: list[dict[str, Any]] = []
    realtime_payloads: list[dict[str, Any]] = []

    for source_message_id in payload.message_ids:
        source_message, _ = await _get_reactable_message(
            session,
            current_user=current_user,
            message_id=source_message_id,
        )

        expires_at = _resolve_expires_at(
            explicit_expires_at=None,
            conversation_ttl_days=conversation.message_ttl_days,
            now_dt=client_created_at,
        )
        forwarded_message = await messages_repo.create_message(
            session,
            conversation_id=conversation.id,
            sender_user_id=current_user.id,
            sender_device_id=current_device.id,
            recipient_user_id=payload.recipient_user_id,
            recipient_device_id=recipient_device.id,
            message_uuid=str(uuid4()),
            reply_to_message_id=None,
            forward_from_message_id=source_message.id,
            message_type=source_message.message_type,
            ciphertext=source_message.ciphertext,
            ciphertext_version=source_message.ciphertext_version,
            encryption_mode=source_message.encryption_mode,
            nonce=source_message.nonce,
            aad_hash=source_message.aad_hash,
            client_created_at=client_created_at,
            expires_at=expires_at,
            auto_delete_after_read_seconds=conversation.delete_after_read_seconds,
            has_attachments=source_message.has_attachments,
        )
        recipient_state = await messages_repo.create_recipient_state(
            session,
            message_id=forwarded_message.id,
            recipient_user_id=payload.recipient_user_id,
            recipient_device_id=recipient_device.id,
        )
        if _is_self_conversation(conversation=conversation):
            await messages_repo.mark_delivered(
                session,
                message=forwarded_message,
                state=recipient_state,
                delivered_at=client_created_at,
            )
            await messages_repo.mark_read(
                session,
                message=forwarded_message,
                state=recipient_state,
                read_at=client_created_at,
            )
        if source_message.has_attachments:
            await _clone_forward_attachments(
                session,
                source_message_id=source_message.id,
                target_message_id=forwarded_message.id,
            )

        event = await conversations_repo.create_event(
            session,
            conversation_id=conversation.id,
            actor_user_id=current_user.id,
            actor_device_id=current_device.id,
            event_type=EventType.MESSAGE_FORWARDED,
            target_message_id=forwarded_message.id,
            payload={
                "message_id": forwarded_message.id,
                "message_uuid": forwarded_message.message_uuid,
                "source_message_id": source_message.id,
                "forward_from_message_id": source_message.id,
                "sender_user_id": forwarded_message.sender_user_id,
                "sender_device_id": forwarded_message.sender_device_id,
                "recipient_user_id": forwarded_message.recipient_user_id,
                "recipient_device_id": forwarded_message.recipient_device_id,
                "message_type": forwarded_message.message_type.value,
                "has_attachments": forwarded_message.has_attachments,
                "client_created_at": forwarded_message.client_created_at.isoformat(),
            },
        )
        realtime_payloads.append(
            _event_to_realtime_payload(
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
        )
        created_items.append(
            {
                "source_message_id": source_message.id,
                "message_id": forwarded_message.id,
                "message_uuid": forwarded_message.message_uuid,
                "recipient_device_id": forwarded_message.recipient_device_id,
                "server_received_at": forwarded_message.server_received_at,
            }
        )

    await conversations_repo.touch_conversation(
        session,
        conversation=conversation,
        touched_at=_now(),
    )
    await session.commit()

    if not _is_self_conversation(conversation=conversation):
        _enqueue_recompute_unread(payload.recipient_user_id)
    _enqueue_recompute_unread(current_user.id)

    for item, realtime_payload in zip(created_items, realtime_payloads, strict=False):
        if not _is_self_conversation(conversation=conversation):
            _enqueue_push_notification(
                user_id=payload.recipient_user_id,
                conversation_id=conversation.id,
                message_id=item["message_id"],
            )
        await realtime_hub.publish_conversation_event(conversation.id, realtime_payload)
        if not _is_self_conversation(conversation=conversation):
            await realtime_hub.publish_user_event(
                payload.recipient_user_id,
                realtime_payload,
            )

    return {
        "conversation_id": conversation.id,
        "recipient_user_id": payload.recipient_user_id,
        "items": created_items,
    }


async def pin_message(
    session: AsyncSession,
    *,
    current_user: User,
    current_device: Device,
    conversation_id: int,
    message_id: int,
) -> PinMessageResponseData:
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

    message = await messages_repo.get_by_id_in_conversation(
        session,
        message_id=message_id,
        conversation_id=conversation_id,
    )
    if message is None:
        raise NotFoundError(
            code="MESSAGE_NOT_FOUND",
            message="Message not found",
        )

    await conversations_repo.set_pinned_message(
        session,
        conversation=conversation,
        message_id=message.id,
    )
    event = await conversations_repo.create_event(
        session,
        conversation_id=conversation_id,
        actor_user_id=current_user.id,
        actor_device_id=current_device.id,
        event_type=EventType.MESSAGE_PINNED,
        target_message_id=message.id,
        payload={
            "message_id": message.id,
            "pinned_message_id": message.id,
            "preview": _preview_from_message(message).model_dump(mode="json"),
        },
    )
    await session.commit()

    peer_user_id = _other_participant_id(
        conversation.user_a_id,
        conversation.user_b_id,
        current_user.id,
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
    if not _is_self_conversation(conversation=conversation):
        await realtime_hub.publish_user_event(peer_user_id, realtime_payload)

    return PinMessageResponseData(
        conversation_id=conversation_id,
        message_id=message.id,
        pinned=True,
    )


async def unpin_message(
    session: AsyncSession,
    *,
    current_user: User,
    current_device: Device,
    conversation_id: int,
) -> PinMessageResponseData:
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

    previous_pinned_message_id = conversation.pinned_message_id
    await conversations_repo.set_pinned_message(
        session,
        conversation=conversation,
        message_id=None,
    )
    event = await conversations_repo.create_event(
        session,
        conversation_id=conversation_id,
        actor_user_id=current_user.id,
        actor_device_id=current_device.id,
        event_type=EventType.MESSAGE_UNPINNED,
        target_message_id=previous_pinned_message_id,
        payload={"pinned_message_id": None},
    )
    await session.commit()

    peer_user_id = _other_participant_id(
        conversation.user_a_id,
        conversation.user_b_id,
        current_user.id,
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
    if not _is_self_conversation(conversation=conversation):
        await realtime_hub.publish_user_event(peer_user_id, realtime_payload)

    return PinMessageResponseData(
        conversation_id=conversation_id,
        message_id=None,
        pinned=False,
    )


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
    if read_at > _now() + timedelta(seconds=30):
        read_at = _now()

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
    if message.sender_user_id != current_user.id:
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
    if message.sender_user_id != current_user.id:
        await realtime_hub.publish_user_event(
            message.sender_user_id,
            realtime_payload,
        )

    return {
        "message_id": message.id,
        "status": "read",
        "read_at": read_at,
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

    _ensure_conversation_mutable(
        is_purged=conversation.is_purged,
        is_active=conversation.is_active,
    )

    hidden_ids = await messages_repo.hide_messages_for_user(
        session,
        conversation_id=payload.conversation_id,
        user_id=current_user.id,
        message_ids=payload.message_ids,
        reason=VisibilityReason.USER_DELETED,
    )

    if not hidden_ids:
        return {
            "deleted": False,
            "scope": "local",
            "message_ids": [],
        }

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

    _ensure_conversation_mutable(
        is_purged=conversation.is_purged,
        is_active=conversation.is_active,
    )

    deleted_messages = await messages_repo.delete_global_messages(
        session,
        conversation_id=payload.conversation_id,
        actor_user_id=current_user.id,
        message_ids=payload.message_ids,
        deleted_at=_now(),
    )
    deleted_ids = [message.id for message in deleted_messages]

    if not deleted_ids:
        return {
            "deleted": False,
            "scope": "global",
            "message_ids": [],
        }

    attachments = await files_repo.list_by_message_ids(
        session,
        message_ids=deleted_ids,
    )
    deleted_attachment_ids = await files_repo.mark_attachments_deleted(
        session,
        attachments=attachments,
        deleted_at=_now(),
    )

    event = await conversations_repo.create_event(
        session,
        conversation_id=payload.conversation_id,
        actor_user_id=current_user.id,
        actor_device_id=None,
        event_type=EventType.MESSAGE_DELETED_GLOBAL,
        payload={
            "message_ids": deleted_ids,
            "attachment_ids": deleted_attachment_ids,
            "scope": "global",
        },
    )
    if conversation.pinned_message_id in deleted_ids:
        await conversations_repo.set_pinned_message(
            session,
            conversation=conversation,
            message_id=None,
        )

    await conversations_repo.touch_conversation(
        session,
        conversation=conversation,
        touched_at=_now(),
    )

    await session.commit()

    peer_user_id = _other_participant_id(
        conversation.user_a_id,
        conversation.user_b_id,
        current_user.id,
    )

    audit_log(
        "message_deleted_global",
        user_id=current_user.id,
        conversation_id=payload.conversation_id,
        extra={
            "message_ids": deleted_ids,
            "attachment_ids": deleted_attachment_ids,
        },
    )
    _enqueue_recompute_unread(current_user.id)
    if not _is_self_conversation(conversation=conversation):
        _enqueue_recompute_unread(peer_user_id)

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
    if not _is_self_conversation(conversation=conversation):
        await realtime_hub.publish_user_event(peer_user_id, realtime_payload)

    return {
        "deleted": True,
        "scope": "global",
        "message_ids": deleted_ids,
    }


async def set_message_reaction(
    session: AsyncSession,
    *,
    current_user: User,
    current_device: Device,
    message_id: int,
    payload: SetMessageReactionRequest,
) -> dict:
    message, conversation = await _get_reactable_message(
        session,
        current_user=current_user,
        message_id=message_id,
    )

    reaction = await messages_repo.upsert_reaction(
        session,
        message_id=message.id,
        user_id=current_user.id,
        reaction=payload.reaction,
    )

    event = await conversations_repo.create_event(
        session,
        conversation_id=message.conversation_id,
        actor_user_id=current_user.id,
        actor_device_id=current_device.id,
        event_type=EventType.MESSAGE_REACTION_SET,
        target_message_id=message.id,
        payload={
            "message_id": message.id,
            "user_id": current_user.id,
            "reaction": reaction.reaction,
        },
    )

    await session.commit()

    peer_user_id = _other_participant_id(
        conversation.user_a_id,
        conversation.user_b_id,
        current_user.id,
    )

    audit_log(
        "message_reaction_set",
        user_id=current_user.id,
        device_id=current_device.id,
        conversation_id=message.conversation_id,
        message_id=message.id,
        extra={"reaction": reaction.reaction},
    )

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
    if not _is_self_conversation(conversation=conversation):
        await realtime_hub.publish_user_event(peer_user_id, realtime_payload)

    return {
        "message_id": message.id,
        "reaction": reaction.reaction,
        "updated": True,
    }


async def delete_message_reaction(
    session: AsyncSession,
    *,
    current_user: User,
    current_device: Device,
    message_id: int,
) -> dict:
    message, conversation = await _get_reactable_message(
        session,
        current_user=current_user,
        message_id=message_id,
    )

    removed = await messages_repo.delete_reaction(
        session,
        message_id=message.id,
        user_id=current_user.id,
    )

    if not removed:
        return {"message_id": message.id, "removed": False}

    event = await conversations_repo.create_event(
        session,
        conversation_id=message.conversation_id,
        actor_user_id=current_user.id,
        actor_device_id=current_device.id,
        event_type=EventType.MESSAGE_REACTION_REMOVED,
        target_message_id=message.id,
        payload={"message_id": message.id, "user_id": current_user.id},
    )

    await session.commit()

    peer_user_id = _other_participant_id(
        conversation.user_a_id,
        conversation.user_b_id,
        current_user.id,
    )

    audit_log(
        "message_reaction_removed",
        user_id=current_user.id,
        device_id=current_device.id,
        conversation_id=message.conversation_id,
        message_id=message.id,
    )

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
    if not _is_self_conversation(conversation=conversation):
        await realtime_hub.publish_user_event(peer_user_id, realtime_payload)

    return {"message_id": message.id, "removed": True}


async def mark_delivered(
    session: AsyncSession,
    *,
    current_user: User,
    current_device: Device,
    message_id: int,
    payload: MarkDeliveredRequest,
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

    delivered_at = payload.delivered_at or _now()
    if delivered_at > _now() + timedelta(seconds=30):
        delivered_at = _now()

    state = await messages_repo.get_recipient_state(
        session,
        message_id=message.id,
        recipient_device_id=current_device.id,
    )
    await messages_repo.mark_delivered(
        session,
        message=message,
        state=state,
        delivered_at=delivered_at,
    )

    event = await conversations_repo.create_event(
        session,
        conversation_id=message.conversation_id,
        actor_user_id=current_user.id,
        actor_device_id=current_device.id,
        event_type=EventType.MESSAGE_DELIVERED,
        target_message_id=message.id,
        payload={"message_id": message.id, "delivered_at": delivered_at.isoformat()},
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
            touched_at=delivered_at,
        )

    await session.commit()

    audit_log(
        "message_delivered",
        user_id=current_user.id,
        device_id=current_device.id,
        conversation_id=message.conversation_id,
        message_id=message.id,
    )

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
    if message.sender_user_id != current_user.id:
        await realtime_hub.publish_user_event(
            message.sender_user_id,
            realtime_payload,
        )

    return {
        "message_id": message.id,
        "status": "delivered",
        "delivered_at": delivered_at,
    }
