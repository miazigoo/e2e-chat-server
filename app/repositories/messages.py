from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.chat_enums import (
    DeliveryStatus,
    EncryptionMode,
    MessageType,
    VisibilityReason,
)
from app.models.message import Message, MessageRecipientState, MessageVisibilityOverride


class MessagesRepository:
    async def create_message(
        self,
        session: AsyncSession,
        *,
        conversation_id: int,
        sender_user_id: int,
        sender_device_id: int,
        recipient_user_id: int,
        recipient_device_id: int,
        message_uuid: str | None,
        reply_to_message_id: int | None,
        message_type: MessageType,
        ciphertext: str,
        ciphertext_version: int,
        encryption_mode: EncryptionMode,
        nonce: str,
        aad_hash: str | None,
        client_created_at: datetime,
        expires_at: datetime,
        auto_delete_after_read_seconds: int | None,
        has_attachments: bool,
    ) -> Message:
        message_kwargs = {
            "conversation_id": conversation_id,
            "sender_user_id": sender_user_id,
            "sender_device_id": sender_device_id,
            "recipient_user_id": recipient_user_id,
            "recipient_device_id": recipient_device_id,
            "reply_to_message_id": reply_to_message_id,
            "message_type": message_type,
            "ciphertext": ciphertext,
            "ciphertext_version": ciphertext_version,
            "encryption_mode": encryption_mode,
            "nonce": nonce,
            "aad_hash": aad_hash,
            "client_created_at": client_created_at,
            "expires_at": expires_at,
            "auto_delete_after_read_seconds": auto_delete_after_read_seconds,
            "has_attachments": has_attachments,
        }

        if message_uuid is not None:
            message_kwargs["message_uuid"] = message_uuid

        message = Message(**message_kwargs)
        session.add(message)
        await session.flush()
        return message

    async def create_recipient_state(
        self,
        session: AsyncSession,
        *,
        message_id: int,
        recipient_user_id: int,
        recipient_device_id: int,
    ) -> MessageRecipientState:
        state = MessageRecipientState(
            message_id=message_id,
            recipient_user_id=recipient_user_id,
            recipient_device_id=recipient_device_id,
            delivery_status=DeliveryStatus.SERVER_RECEIVED,
        )
        session.add(state)
        await session.flush()
        return state

    async def list_for_user(
        self,
        session: AsyncSession,
        *,
        conversation_id: int,
        user_id: int,
        before_id: int | None,
        limit: int,
        cleared_at: datetime | None,
    ) -> list[Message]:
        hidden_subquery = select(MessageVisibilityOverride.message_id).where(
            MessageVisibilityOverride.user_id == user_id
        )

        stmt = (
            select(Message)
            .where(
                Message.conversation_id == conversation_id,
                Message.is_deleted_global.is_(False),
                ~Message.id.in_(hidden_subquery),
            )
            .order_by(Message.id.desc())
            .limit(limit)
        )

        if before_id is not None:
            stmt = stmt.where(Message.id < before_id)

        if cleared_at is not None:
            stmt = stmt.where(Message.created_at > cleared_at)

        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_message_for_recipient(
        self,
        session: AsyncSession,
        *,
        message_id: int,
        user_id: int,
        recipient_device_id: int,
    ) -> Message | None:
        result = await session.execute(
            select(Message).where(
                Message.id == message_id,
                Message.recipient_user_id == user_id,
                Message.recipient_device_id == recipient_device_id,
                Message.is_deleted_global.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def get_recipient_state(
        self,
        session: AsyncSession,
        *,
        message_id: int,
        recipient_device_id: int,
    ) -> MessageRecipientState | None:
        result = await session.execute(
            select(MessageRecipientState).where(
                MessageRecipientState.message_id == message_id,
                MessageRecipientState.recipient_device_id == recipient_device_id,
            )
        )
        return result.scalar_one_or_none()

    async def get_by_message_uuid(
        self,
        session: AsyncSession,
        *,
        conversation_id: int,
        sender_user_id: int,
        message_uuid: str | None,
    ) -> Message | None:
        stmt = select(Message).where(
            Message.conversation_id == conversation_id,
            Message.sender_user_id == sender_user_id,
            Message.message_uuid == message_uuid,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def mark_read(
        self,
        session: AsyncSession,
        *,
        message: Message,
        state: MessageRecipientState | None,
        read_at: datetime,
    ) -> None:
        if message.read_at is None:
            message.read_at = read_at

        if state is not None:
            state.read_at = read_at
            state.delivery_status = DeliveryStatus.READ

        await session.flush()

    async def hide_messages_for_user(
        self,
        session: AsyncSession,
        *,
        conversation_id: int,
        user_id: int,
        message_ids: list[int],
        reason: VisibilityReason,
    ) -> list[int]:
        result = await session.execute(
            select(Message.id).where(
                Message.conversation_id == conversation_id,
                Message.id.in_(message_ids),
            )
        )
        existing_message_ids = set(result.scalars().all())

        hidden_result = await session.execute(
            select(MessageVisibilityOverride.message_id).where(
                MessageVisibilityOverride.user_id == user_id,
                MessageVisibilityOverride.message_id.in_(message_ids),
            )
        )
        already_hidden = set(hidden_result.scalars().all())

        created_ids: list[int] = []
        for message_id in message_ids:
            if message_id in existing_message_ids and message_id not in already_hidden:
                session.add(
                    MessageVisibilityOverride(
                        message_id=message_id,
                        user_id=user_id,
                        reason=reason,
                    )
                )
                created_ids.append(message_id)

        await session.flush()
        return created_ids

    async def delete_global_messages(
        self,
        session: AsyncSession,
        *,
        conversation_id: int,
        actor_user_id: int,
        message_ids: list[int],
        deleted_at: datetime,
    ) -> list[Message]:
        result = await session.execute(
            select(Message).where(
                Message.conversation_id == conversation_id,
                Message.id.in_(message_ids),
                Message.sender_user_id == actor_user_id,
                Message.is_deleted_global.is_(False),
            )
        )
        messages = list(result.scalars().all())

        for message in messages:
            message.is_deleted_global = True
            message.deleted_global_at = deleted_at
            message.deleted_by_user_id = actor_user_id

        await session.flush()
        return messages

    async def clear_global_conversation(
        self,
        session: AsyncSession,
        *,
        conversation_id: int,
        actor_user_id: int,
        deleted_at: datetime,
    ) -> int:
        result = await session.execute(
            select(Message).where(
                Message.conversation_id == conversation_id,
                Message.is_deleted_global.is_(False),
            )
        )
        messages = list(result.scalars().all())

        for message in messages:
            message.is_deleted_global = True
            message.deleted_global_at = deleted_at
            message.deleted_by_user_id = actor_user_id

        await session.flush()
        return len(messages)

    async def get_by_id_in_conversation(
        self,
        session: AsyncSession,
        *,
        message_id: int,
        conversation_id: int,
    ) -> Message | None:
        result = await session.execute(
            select(Message).where(
                Message.id == message_id,
                Message.conversation_id == conversation_id,
                Message.is_deleted_global.is_(False),
            )
        )
        return result.scalar_one_or_none()
