from datetime import datetime
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_enums import EventType, ProtectionMode
from app.models.conversation import (
    Conversation,
    ConversationEvent,
    ConversationParticipant,
)


class ConversationsRepository:
    async def create_conversation(
        self,
        session: AsyncSession,
        *,
        user_a_id: int,
        user_b_id: int,
        created_by_user_id: int,
        title: str | None,
        protection_mode: ProtectionMode,
        message_ttl_days: int | None,
        delete_after_read_seconds: int | None,
    ) -> Conversation:
        ordered_a, ordered_b = sorted((user_a_id, user_b_id))

        conversation = Conversation(
            user_a_id=ordered_a,
            user_b_id=ordered_b,
            created_by_user_id=created_by_user_id,
            title=title,
            protection_mode=protection_mode,
            message_ttl_days=message_ttl_days,
            delete_after_read_seconds=delete_after_read_seconds,
        )
        session.add(conversation)
        await session.flush()

        session.add(
            ConversationParticipant(
                conversation_id=conversation.id,
                user_id=user_a_id,
            )
        )
        session.add(
            ConversationParticipant(
                conversation_id=conversation.id,
                user_id=user_b_id,
            )
        )
        await session.flush()

        return conversation

    async def get_by_id(
        self,
        session: AsyncSession,
        *,
        conversation_id: int,
    ) -> Conversation | None:
        result = await session.execute(
            select(Conversation).where(Conversation.id == conversation_id)
        )
        return result.scalar_one_or_none()

    async def get_for_user(
        self,
        session: AsyncSession,
        *,
        conversation_id: int,
        user_id: int,
    ) -> Conversation | None:
        result = await session.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                or_(
                    Conversation.user_a_id == user_id,
                    Conversation.user_b_id == user_id,
                ),
            )
        )
        return result.scalar_one_or_none()

    async def list_for_user(
        self,
        session: AsyncSession,
        *,
        user_id: int,
    ) -> list[Conversation]:
        result = await session.execute(
            select(Conversation)
            .where(
                or_(
                    Conversation.user_a_id == user_id,
                    Conversation.user_b_id == user_id,
                )
            )
            .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
        )
        return list(result.scalars().all())

    async def get_participant(
        self,
        session: AsyncSession,
        *,
        conversation_id: int,
        user_id: int,
    ) -> ConversationParticipant | None:
        result = await session.execute(
            select(ConversationParticipant).where(
                ConversationParticipant.conversation_id == conversation_id,
                ConversationParticipant.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def update_conversation(
        self,
        session: AsyncSession,
        *,
        conversation: Conversation,
        title: str | None,
        message_ttl_days: int | None,
        delete_after_read_seconds: int | None,
    ) -> Conversation:
        if title is not None:
            conversation.title = title
        if message_ttl_days is not None:
            conversation.message_ttl_days = message_ttl_days
        if delete_after_read_seconds is not None:
            conversation.delete_after_read_seconds = delete_after_read_seconds

        await session.flush()
        return conversation

    async def clear_local_for_user(
        self,
        session: AsyncSession,
        *,
        participant: ConversationParticipant,
        cleared_at: datetime,
    ) -> ConversationParticipant:
        participant.cleared_at = cleared_at
        await session.flush()
        return participant

    async def create_event(
        self,
        session: AsyncSession,
        *,
        conversation_id: int,
        actor_user_id: int | None,
        actor_device_id: int | None,
        event_type: EventType,
        target_message_id: int | None = None,
        payload: dict[str, Any] | None = None,
    ) -> ConversationEvent:
        event = ConversationEvent(
            conversation_id=conversation_id,
            actor_user_id=actor_user_id,
            actor_device_id=actor_device_id,
            event_type=event_type,
            target_message_id=target_message_id,
            payload=payload,
        )
        session.add(event)
        await session.flush()
        return event
