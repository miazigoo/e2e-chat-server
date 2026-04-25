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

    async def list_overview_for_user(
        self,
        session: AsyncSession,
        *,
        user_id: int,
    ) -> list[dict[str, Any]]:
        from app.models.message import Message
        from app.models.user import User

        conversations = await self.list_for_user(session, user_id=user_id)
        if not conversations:
            return []

        conversation_ids = [conversation.id for conversation in conversations]

        participants_result = await session.execute(
            select(ConversationParticipant).where(
                ConversationParticipant.conversation_id.in_(conversation_ids)
            )
        )
        participants = list(participants_result.scalars().all())
        participant_by_conversation_id = {
            participant.conversation_id: participant
            for participant in participants
            if participant.user_id == user_id
        }
        peer_participant_by_conversation_id = {
            participant.conversation_id: participant
            for participant in participants
            if participant.user_id != user_id
        }

        peer_user_ids = {
            (
                conversation.user_b_id
                if conversation.user_a_id == user_id
                else conversation.user_a_id
            )
            for conversation in conversations
        }

        peers_result = await session.execute(
            select(User).where(User.id.in_(peer_user_ids))
        )
        peers = list(peers_result.scalars().all())
        peer_by_id = {peer.id: peer for peer in peers}

        messages_result = await session.execute(
            select(Message)
            .where(
                Message.conversation_id.in_(conversation_ids),
                Message.is_deleted_global.is_(False),
            )
            .order_by(Message.conversation_id.asc(), Message.id.desc())
        )
        all_messages = list(messages_result.scalars().all())
        pinned_message_ids = {
            conversation.pinned_message_id
            for conversation in conversations
            if conversation.pinned_message_id is not None
        }
        pinned_messages: dict[int, Message] = {}
        if pinned_message_ids:
            pinned_result = await session.execute(
                select(Message).where(
                    Message.id.in_(pinned_message_ids),
                    Message.is_deleted_global.is_(False),
                )
            )
            pinned_messages = {
                message.id: message for message in pinned_result.scalars().all()
            }

        last_message_by_conversation_id: dict[int, Message] = {}
        unread_count_by_conversation_id: dict[int, int] = {
            conversation_id: 0 for conversation_id in conversation_ids
        }

        for message in all_messages:
            participant = participant_by_conversation_id.get(message.conversation_id)
            cleared_at = participant.cleared_at if participant is not None else None

            if cleared_at is not None and message.created_at <= cleared_at:
                continue

            if message.conversation_id not in last_message_by_conversation_id:
                last_message_by_conversation_id[message.conversation_id] = message

            if message.recipient_user_id == user_id and message.read_at is None:
                unread_count_by_conversation_id[message.conversation_id] += 1

        items: list[dict[str, Any]] = []

        for conversation in conversations:
            peer_user_id = (
                conversation.user_b_id
                if conversation.user_a_id == user_id
                else conversation.user_a_id
            )
            peer = peer_by_id.get(peer_user_id)

            items.append(
                {
                    "conversation": conversation,
                    "peer_user_id": peer_user_id,
                    "peer_nickname": peer.nickname if peer is not None else None,
                    "unread_count": unread_count_by_conversation_id.get(
                        conversation.id, 0
                    ),
                    "last_message": last_message_by_conversation_id.get(
                        conversation.id
                    ),
                    "participant": participant_by_conversation_id.get(conversation.id),
                    "peer_participant": peer_participant_by_conversation_id.get(
                        conversation.id
                    ),
                    "pinned_message": (
                        pinned_messages.get(conversation.pinned_message_id)
                        if conversation.pinned_message_id is not None
                        else None
                    ),
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

    async def update_participant_settings(
        self,
        session: AsyncSession,
        *,
        participant: ConversationParticipant,
        shared_secret_enabled: bool | None,
        shared_secret_fingerprint: str | None,
        updated_at: datetime,
    ) -> ConversationParticipant:
        if shared_secret_enabled is not None:
            participant.shared_secret_enabled = shared_secret_enabled

        if participant.shared_secret_enabled:
            if shared_secret_fingerprint is not None:
                participant.shared_secret_fingerprint = shared_secret_fingerprint
        else:
            participant.shared_secret_fingerprint = None

        participant.shared_secret_updated_at = updated_at
        await session.flush()
        return participant

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

    async def touch_conversation(
        self,
        session: AsyncSession,
        *,
        conversation: Conversation,
        touched_at: datetime,
    ) -> None:
        conversation.updated_at = touched_at
        await session.flush()

    async def set_pinned_message(
        self,
        session: AsyncSession,
        *,
        conversation: Conversation,
        message_id: int | None,
    ) -> Conversation:
        conversation.pinned_message_id = message_id
        await session.flush()
        return conversation
