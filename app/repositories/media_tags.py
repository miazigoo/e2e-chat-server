from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attachment import AttachmentMediaTag, ConversationMediaTag


class MediaTagsRepository:
    async def list_for_conversation(
        self,
        session: AsyncSession,
        *,
        conversation_id: int,
    ) -> list[ConversationMediaTag]:
        result = await session.execute(
            select(ConversationMediaTag)
            .where(ConversationMediaTag.conversation_id == conversation_id)
            .order_by(ConversationMediaTag.name.asc(), ConversationMediaTag.id.asc())
        )
        return list(result.scalars().all())

    async def get_for_conversation(
        self,
        session: AsyncSession,
        *,
        conversation_id: int,
        tag_id: int,
    ) -> ConversationMediaTag | None:
        result = await session.execute(
            select(ConversationMediaTag).where(
                ConversationMediaTag.id == tag_id,
                ConversationMediaTag.conversation_id == conversation_id,
            )
        )
        return result.scalar_one_or_none()

    async def list_by_ids_for_conversation(
        self,
        session: AsyncSession,
        *,
        conversation_id: int,
        tag_ids: list[int],
    ) -> list[ConversationMediaTag]:
        if not tag_ids:
            return []
        result = await session.execute(
            select(ConversationMediaTag).where(
                ConversationMediaTag.conversation_id == conversation_id,
                ConversationMediaTag.id.in_(tag_ids),
            )
        )
        return list(result.scalars().all())

    async def create(
        self,
        session: AsyncSession,
        *,
        conversation_id: int,
        name: str,
        normalized_name: str,
        color: str | None,
        created_by_user_id: int,
    ) -> ConversationMediaTag:
        tag = ConversationMediaTag(
            conversation_id=conversation_id,
            name=name,
            normalized_name=normalized_name,
            color=color,
            created_by_user_id=created_by_user_id,
        )
        session.add(tag)
        await session.flush()
        return tag

    async def update(
        self,
        session: AsyncSession,
        *,
        tag: ConversationMediaTag,
        name: str | None,
        normalized_name: str | None,
        color: str | None,
        updated_at: datetime,
    ) -> ConversationMediaTag:
        if name is not None and normalized_name is not None:
            tag.name = name
            tag.normalized_name = normalized_name
        tag.color = color
        tag.updated_at = updated_at
        await session.flush()
        return tag

    async def delete(self, session: AsyncSession, *, tag: ConversationMediaTag) -> None:
        await session.delete(tag)
        await session.flush()

    async def add_tags_to_attachments(
        self,
        session: AsyncSession,
        *,
        attachment_ids: list[int],
        tag_ids: list[int],
        tagged_by_user_id: int,
    ) -> None:
        if not attachment_ids or not tag_ids:
            return

        existing_result = await session.execute(
            select(AttachmentMediaTag.attachment_id, AttachmentMediaTag.tag_id).where(
                AttachmentMediaTag.attachment_id.in_(attachment_ids),
                AttachmentMediaTag.tag_id.in_(tag_ids),
            )
        )
        existing = set(existing_result.all())

        for attachment_id in attachment_ids:
            for tag_id in tag_ids:
                if (attachment_id, tag_id) in existing:
                    continue
                session.add(
                    AttachmentMediaTag(
                        attachment_id=attachment_id,
                        tag_id=tag_id,
                        tagged_by_user_id=tagged_by_user_id,
                    )
                )
        await session.flush()

    async def remove_tag_from_attachment(
        self,
        session: AsyncSession,
        *,
        attachment_id: int,
        tag_id: int,
    ) -> None:
        await session.execute(
            delete(AttachmentMediaTag).where(
                AttachmentMediaTag.attachment_id == attachment_id,
                AttachmentMediaTag.tag_id == tag_id,
            )
        )
        await session.flush()

    async def list_tags_for_attachments(
        self,
        session: AsyncSession,
        *,
        attachment_ids: list[int],
    ) -> dict[int, list[ConversationMediaTag]]:
        if not attachment_ids:
            return {}

        result = await session.execute(
            select(AttachmentMediaTag.attachment_id, ConversationMediaTag)
            .join(
                ConversationMediaTag,
                ConversationMediaTag.id == AttachmentMediaTag.tag_id,
            )
            .where(AttachmentMediaTag.attachment_id.in_(attachment_ids))
            .order_by(ConversationMediaTag.name.asc(), ConversationMediaTag.id.asc())
        )
        tags_by_attachment_id: dict[int, list[ConversationMediaTag]] = {}
        for attachment_id, tag in result.all():
            tags_by_attachment_id.setdefault(int(attachment_id), []).append(tag)
        return tags_by_attachment_id

    async def set_tags_for_attachment(
        self,
        session: AsyncSession,
        *,
        attachment_id: int,
        tag_ids: list[int],
        tagged_by_user_id: int,
    ) -> None:
        normalized_tag_ids = list(dict.fromkeys(tag_ids))
        if normalized_tag_ids:
            await session.execute(
                delete(AttachmentMediaTag).where(
                    AttachmentMediaTag.attachment_id == attachment_id,
                    AttachmentMediaTag.tag_id.not_in(normalized_tag_ids),
                )
            )
        else:
            await session.execute(
                delete(AttachmentMediaTag).where(
                    AttachmentMediaTag.attachment_id == attachment_id,
                )
            )

        await self.add_tags_to_attachments(
            session,
            attachment_ids=[attachment_id],
            tag_ids=normalized_tag_ids,
            tagged_by_user_id=tagged_by_user_id,
        )
