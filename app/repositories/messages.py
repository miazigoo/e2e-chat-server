from datetime import datetime

from sqlalchemy import Text, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attachment import Attachment
from app.models.chat_enums import (
    DeliveryStatus,
    EncryptionMode,
    MessageType,
    VisibilityReason,
)
from app.models.message import (
    Message,
    MessageReaction,
    MessageRecipientState,
    MessageVisibilityOverride,
)


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
        message_uuid: str,
        reply_to_message_id: int | None,
        forward_from_message_id: int | None,
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
        message = Message(
            conversation_id=conversation_id,
            sender_user_id=sender_user_id,
            sender_device_id=sender_device_id,
            recipient_user_id=recipient_user_id,
            recipient_device_id=recipient_device_id,
            message_uuid=message_uuid,
            reply_to_message_id=reply_to_message_id,
            forward_from_message_id=forward_from_message_id,
            message_type=message_type,
            ciphertext=ciphertext,
            ciphertext_version=ciphertext_version,
            encryption_mode=encryption_mode,
            nonce=nonce,
            aad_hash=aad_hash,
            client_created_at=client_created_at,
            expires_at=expires_at,
            auto_delete_after_read_seconds=auto_delete_after_read_seconds,
            has_attachments=has_attachments,
        )
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
        message_uuid: str,
    ) -> Message | None:
        stmt = select(Message).where(
            Message.conversation_id == conversation_id,
            Message.sender_user_id == sender_user_id,
            Message.message_uuid == message_uuid,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_id(
        self,
        session: AsyncSession,
        *,
        message_id: int,
    ) -> Message | None:
        result = await session.execute(
            select(Message).where(
                Message.id == message_id,
                Message.is_deleted_global.is_(False),
            )
        )
        return result.scalar_one_or_none()

    async def is_hidden_for_user(
        self,
        session: AsyncSession,
        *,
        message_id: int,
        user_id: int,
    ) -> bool:
        result = await session.execute(
            select(MessageVisibilityOverride.id).where(
                MessageVisibilityOverride.message_id == message_id,
                MessageVisibilityOverride.user_id == user_id,
            )
        )
        return result.scalar_one_or_none() is not None

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

    async def list_reactions_for_messages(
        self,
        session: AsyncSession,
        *,
        message_ids: list[int],
    ) -> list[MessageReaction]:
        if not message_ids:
            return []

        result = await session.execute(
            select(MessageReaction).where(MessageReaction.message_id.in_(message_ids))
        )
        return list(result.scalars().all())

    async def list_by_ids(
        self,
        session: AsyncSession,
        *,
        message_ids: list[int],
    ) -> list[Message]:
        if not message_ids:
            return []

        result = await session.execute(
            select(Message).where(
                Message.id.in_(message_ids),
                Message.is_deleted_global.is_(False),
            )
        )
        return list(result.scalars().all())

    async def search_in_conversation_for_user(
        self,
        session: AsyncSession,
        *,
        conversation_id: int,
        user_id: int,
        query: str,
        limit: int,
        cleared_at: datetime | None,
    ) -> list[Message]:
        hidden_subquery = select(MessageVisibilityOverride.message_id).where(
            MessageVisibilityOverride.user_id == user_id
        )
        pattern = f"%{query}%"

        stmt = (
            select(Message)
            .outerjoin(Attachment, Attachment.message_id == Message.id)
            .where(
                Message.conversation_id == conversation_id,
                Message.is_deleted_global.is_(False),
                ~Message.id.in_(hidden_subquery),
                or_(
                    Message.ciphertext.ilike(pattern),
                    Attachment.encrypted_file_name.ilike(pattern),
                    Attachment.mime_hint.ilike(pattern),
                    cast(Attachment.encrypted_metadata, Text).ilike(pattern),
                    Attachment.storage_key.ilike(pattern),
                ),
            )
            .group_by(Message.id)
            .order_by(Message.id.desc())
            .limit(limit)
        )

        if cleared_at is not None:
            stmt = stmt.where(Message.created_at > cleared_at)

        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def list_shared_messages_for_user(
        self,
        session: AsyncSession,
        *,
        conversation_id: int,
        user_id: int,
        tab: str,
        before_message_id: int | None,
        limit: int,
        cleared_at: datetime | None,
    ) -> list[Message]:
        hidden_subquery = select(MessageVisibilityOverride.message_id).where(
            MessageVisibilityOverride.user_id == user_id
        )

        stmt = (
            select(Message)
            .join(Attachment, Attachment.message_id == Message.id)
            .where(
                Message.conversation_id == conversation_id,
                Message.is_deleted_global.is_(False),
                Attachment.deleted_at.is_(None),
                ~Message.id.in_(hidden_subquery),
            )
            .group_by(Message.id)
            .order_by(Message.id.desc())
            .limit(limit)
        )

        if before_message_id is not None:
            stmt = stmt.where(Message.id < before_message_id)

        if cleared_at is not None:
            stmt = stmt.where(Message.created_at > cleared_at)

        if tab == "media":
            stmt = stmt.where(
                or_(
                    Attachment.mime_hint.ilike("image/%"),
                    Attachment.mime_hint.ilike("video/%"),
                )
            )
        elif tab == "files":
            stmt = stmt.where(
                or_(
                    Attachment.mime_hint.is_(None),
                    ~Attachment.mime_hint.ilike("image/%")
                    & ~Attachment.mime_hint.ilike("video/%"),
                )
            )
        elif tab == "links":
            stmt = stmt.where(
                or_(
                    Message.ciphertext.ilike("%http://%"),
                    Message.ciphertext.ilike("%https://%"),
                    Message.ciphertext.ilike("%www.%"),
                    cast(Attachment.encrypted_metadata, Text).ilike("%http://%"),
                    cast(Attachment.encrypted_metadata, Text).ilike("%https://%"),
                    cast(Attachment.encrypted_metadata, Text).ilike("%www.%"),
                )
            )
        else:
            return []

        result = await session.execute(stmt)
        return list(result.scalars().all())

    async def get_shared_counts_for_user(
        self,
        session: AsyncSession,
        *,
        conversation_id: int,
        user_id: int,
        cleared_at: datetime | None,
    ) -> dict[str, int]:
        hidden_subquery = select(MessageVisibilityOverride.message_id).where(
            MessageVisibilityOverride.user_id == user_id
        )

        base_stmt = (
            select(Message.id)
            .join(Attachment, Attachment.message_id == Message.id)
            .where(
                Message.conversation_id == conversation_id,
                Message.is_deleted_global.is_(False),
                Attachment.deleted_at.is_(None),
                ~Message.id.in_(hidden_subquery),
            )
        )

        if cleared_at is not None:
            base_stmt = base_stmt.where(Message.created_at > cleared_at)

        media_stmt = (
            select(func.count(func.distinct(Message.id)))
            .select_from(Message)
            .join(Attachment, Attachment.message_id == Message.id)
            .where(
                Message.id.in_(base_stmt),
                or_(
                    Attachment.mime_hint.ilike("image/%"),
                    Attachment.mime_hint.ilike("video/%"),
                ),
            )
        )
        files_stmt = (
            select(func.count(func.distinct(Message.id)))
            .select_from(Message)
            .join(Attachment, Attachment.message_id == Message.id)
            .where(
                Message.id.in_(base_stmt),
                or_(
                    Attachment.mime_hint.is_(None),
                    ~Attachment.mime_hint.ilike("image/%")
                    & ~Attachment.mime_hint.ilike("video/%"),
                ),
            )
        )
        links_stmt = (
            select(func.count(func.distinct(Message.id)))
            .select_from(Message)
            .outerjoin(Attachment, Attachment.message_id == Message.id)
            .where(
                Message.conversation_id == conversation_id,
                Message.is_deleted_global.is_(False),
                ~Message.id.in_(hidden_subquery),
                or_(
                    Message.ciphertext.ilike("%http://%"),
                    Message.ciphertext.ilike("%https://%"),
                    Message.ciphertext.ilike("%www.%"),
                    cast(Attachment.encrypted_metadata, Text).ilike("%http://%"),
                    cast(Attachment.encrypted_metadata, Text).ilike("%https://%"),
                    cast(Attachment.encrypted_metadata, Text).ilike("%www.%"),
                ),
            )
        )
        if cleared_at is not None:
            links_stmt = links_stmt.where(Message.created_at > cleared_at)

        media = (await session.execute(media_stmt)).scalar_one() or 0
        files = (await session.execute(files_stmt)).scalar_one() or 0
        links = (await session.execute(links_stmt)).scalar_one() or 0

        return {
            "media": int(media),
            "files": int(files),
            "links": int(links),
        }

    async def upsert_reaction(
        self,
        session: AsyncSession,
        *,
        message_id: int,
        user_id: int,
        reaction: str,
    ) -> MessageReaction:
        result = await session.execute(
            select(MessageReaction).where(
                MessageReaction.message_id == message_id,
                MessageReaction.user_id == user_id,
            )
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            existing.reaction = reaction
            await session.flush()
            return existing

        message_reaction = MessageReaction(
            message_id=message_id,
            user_id=user_id,
            reaction=reaction,
        )
        session.add(message_reaction)
        await session.flush()
        return message_reaction

    async def delete_reaction(
        self,
        session: AsyncSession,
        *,
        message_id: int,
        user_id: int,
    ) -> bool:
        result = await session.execute(
            select(MessageReaction).where(
                MessageReaction.message_id == message_id,
                MessageReaction.user_id == user_id,
            )
        )
        message_reaction = result.scalar_one_or_none()
        if message_reaction is None:
            return False

        await session.delete(message_reaction)
        await session.flush()
        return True

    async def mark_delivered(
        self,
        session: AsyncSession,
        *,
        message: Message,
        state: MessageRecipientState | None,
        delivered_at: datetime,
    ) -> None:
        if message.delivered_at is None:
            message.delivered_at = delivered_at

        if state is not None:
            state.delivered_at = delivered_at
            state.delivery_status = DeliveryStatus.DELIVERED

        await session.flush()
