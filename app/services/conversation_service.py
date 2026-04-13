from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_enums import EventType
from app.models.user import User
from app.repositories.conversations import ConversationsRepository
from app.repositories.messages import MessagesRepository
from app.repositories.users import UsersRepository
from app.schemas.conversations import (
    ClearConversationRequest,
    CreateConversationRequest,
    UpdateConversationRequest,
)

users_repo = UsersRepository()
conversations_repo = ConversationsRepository()
messages_repo = MessagesRepository()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _peer_user_id(
    conversation_user_a_id: int, conversation_user_b_id: int, current_user_id: int
) -> int:
    if conversation_user_a_id == current_user_id:
        return conversation_user_b_id
    return conversation_user_a_id


async def create_conversation(
    session: AsyncSession,
    *,
    current_user: User,
    payload: CreateConversationRequest,
) -> dict:
    if payload.recipient_user_id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "SELF_CONVERSATION_NOT_ALLOWED",
                "message": "Cannot create conversation with yourself",
            },
        )

    recipient = await users_repo.get_by_id(session, payload.recipient_user_id)
    if not recipient or recipient.is_deleted or recipient.pending_deletion:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "RECIPIENT_NOT_FOUND",
                "message": "Recipient not found",
            },
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
) -> dict:
    conversations = await conversations_repo.list_for_user(
        session,
        user_id=current_user.id,
    )

    items: list[dict] = []
    for conversation in conversations:
        if conversation.is_purged:
            continue

        items.append(
            {
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
                "created_at": conversation.created_at.isoformat(),
                "updated_at": conversation.updated_at.isoformat(),
            }
        )

    return {"items": items}


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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "CONVERSATION_NOT_FOUND",
                "message": "Conversation not found",
            },
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "CONVERSATION_NOT_FOUND",
                "message": "Conversation not found",
            },
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "CONVERSATION_NOT_FOUND",
                "message": "Conversation not found",
            },
        )

    cleared_at = _now()
    await conversations_repo.clear_local_for_user(
        session,
        participant=participant,
        cleared_at=cleared_at,
    )
    await conversations_repo.create_event(
        session,
        conversation_id=conversation_id,
        actor_user_id=current_user.id,
        actor_device_id=None,
        event_type=EventType.CONVERSATION_CLEARED_LOCAL,
        payload={"scope": "local"},
    )

    await session.commit()

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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "CONVERSATION_NOT_FOUND",
                "message": "Conversation not found",
            },
        )

    deleted_count = await messages_repo.clear_global_conversation(
        session,
        conversation_id=conversation_id,
        actor_user_id=current_user.id,
        deleted_at=_now(),
    )

    await conversations_repo.create_event(
        session,
        conversation_id=conversation_id,
        actor_user_id=current_user.id,
        actor_device_id=None,
        event_type=EventType.CONVERSATION_CLEARED_GLOBAL,
        payload={
            "scope": "global",
            "reason": payload.reason,
            "deleted_messages_count": deleted_count,
        },
    )

    await session.commit()

    return {
        "conversation_id": conversation_id,
        "scope": "global",
        "cleared": True,
        "deleted_messages_count": deleted_count,
    }
