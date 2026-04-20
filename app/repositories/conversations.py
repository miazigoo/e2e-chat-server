from datetime import datetime
from typing import Any

from sqlalchemy import func, or_, select
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

    async def list_overview_for_user(
        self,
        session: AsyncSession,
        *,
        user_id: int,
    ) -> list[dict[str, Any]]:
        from app.models.message import Message
        from app.models.user import User

        conversations = await self.list_for_user(session, user_id=user_id)
        items: list[dict[str, Any]] = []

        for conversation in conversations:
            participant = await self.get_participant(
                session,
                conversation_id=conversation.id,
                user_id=user_id,
            )

            peer_user_id = (
                conversation.user_b_id
                if conversation.user_a_id == user_id
                else conversation.user_a_id
            )

            peer_result = await session.execute(
                select(User).where(User.id == peer_user_id)
            )
            peer = peer_result.scalar_one_or_none()

            last_message_stmt = (
                select(Message)
                .where(
                    Message.conversation_id == conversation.id,
                    Message.is_deleted_global.is_(False),
                )
                .order_by(Message.id.desc())
                .limit(1)
            )
            if participant and participant.cleared_at is not None:
                last_message_stmt = last_message_stmt.where(
                    Message.created_at > participant.cleared_at
                )

            last_message_result = await session.execute(last_message_stmt)
            last_message = last_message_result.scalar_one_or_none()

            unread_stmt = select(func.count(Message.id)).where(
                Message.conversation_id == conversation.id,
                Message.recipient_user_id == user_id,
                Message.read_at.is_(None),
                Message.is_deleted_global.is_(False),
            )
            if participant and participant.cleared_at is not None:
                unread_stmt = unread_stmt.where(
                    Message.created_at > participant.cleared_at
                )

            unread_result = await session.execute(unread_stmt)
            unread_count = int(unread_result.scalar() or 0)

            items.append(
                {
                    "conversation": conversation,
                    "peer_user_id": peer_user_id,
                    "peer_nickname": peer.nickname if peer is not None else None,
                    "unread_count": unread_count,
                    "last_message": last_message,
                }
            )

        return items

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

    async def list_events_for_user(
        self,
        session: AsyncSession,
        *,
        conversation_id: int,
        user_id: int,
        after_event_id: int | None,
        limit: int,
        cleared_at: datetime | None,
    ) -> list[ConversationEvent]:
        participant = await self.get_participant(
            session,
            conversation_id=conversation_id,
            user_id=user_id,
        )
        if participant is None:
            return []

        stmt = (
            select(ConversationEvent)
            .where(ConversationEvent.conversation_id == conversation_id)
            .order_by(ConversationEvent.id.asc())
            .limit(limit)
        )

        if after_event_id is not None:
            stmt = stmt.where(ConversationEvent.id > after_event_id)

        if cleared_at is not None:
            stmt = stmt.where(ConversationEvent.created_at > cleared_at)

        result = await session.execute(stmt)
        return list(result.scalars().all())

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
