from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.attachment import Attachment, UploadSession
from app.models.chat_enums import AttachmentStatus, UploadSessionStatus


def _now() -> datetime:
    return datetime.now(timezone.utc)


class FilesRepository:
    async def create_upload_session(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        conversation_id: int,
        files_expected_count: int,
        expires_at: datetime,
    ) -> UploadSession:
        upload_session = UploadSession(
            user_id=user_id,
            conversation_id=conversation_id,
            files_expected_count=files_expected_count,
            files_uploaded_count=0,
            expires_at=expires_at,
            status=UploadSessionStatus.INIT,
        )
        session.add(upload_session)
        await session.flush()
        return upload_session

    async def get_upload_session_for_user(
        self,
        session: AsyncSession,
        *,
        session_id: int,
        user_id: int,
    ) -> UploadSession | None:
        result = await session.execute(
            select(UploadSession).where(
                UploadSession.id == session_id,
                UploadSession.user_id == user_id,
            )
        )
        return result.scalar_one_or_none()

    async def create_attachment(
        self,
        session: AsyncSession,
        *,
        upload_session_id: int,
        bucket_name: str,
        storage_key: str,
        encrypted_file_name: str | None,
        encrypted_metadata: dict | None,
        file_size: int,
        mime_hint: str | None,
        sha256_encrypted_blob: str,
        expires_at: datetime | None,
    ) -> Attachment:
        attachment = Attachment(
            upload_session_id=upload_session_id,
            bucket_name=bucket_name,
            storage_key=storage_key,
            encrypted_file_name=encrypted_file_name,
            encrypted_metadata=encrypted_metadata,
            file_size=file_size,
            mime_hint=mime_hint,
            sha256_encrypted_blob=sha256_encrypted_blob,
            upload_status=AttachmentStatus.INIT,
            expires_at=expires_at,
        )
        session.add(attachment)
        await session.flush()
        return attachment

    async def list_attachments_for_session(
        self,
        session: AsyncSession,
        *,
        upload_session_id: int,
    ) -> list[Attachment]:
        result = await session.execute(
            select(Attachment)
            .where(Attachment.upload_session_id == upload_session_id)
            .order_by(Attachment.id.asc())
        )
        return list(result.scalars().all())

    async def mark_attachments_uploaded(
        self,
        session: AsyncSession,
        *,
        upload_session_id: int,
        attachment_ids: list[int],
    ) -> list[Attachment]:
        result = await session.execute(
            select(Attachment).where(
                Attachment.upload_session_id == upload_session_id,
                Attachment.id.in_(attachment_ids),
            )
        )
        attachments = list(result.scalars().all())

        for attachment in attachments:
            attachment.upload_status = AttachmentStatus.UPLOADED

        await session.flush()
        return attachments

    async def complete_upload_session(
        self,
        session: AsyncSession,
        *,
        upload_session: UploadSession,
        files_uploaded_count: int,
        completed_at: datetime,
    ) -> UploadSession:
        upload_session.files_uploaded_count = files_uploaded_count
        upload_session.status = UploadSessionStatus.COMPLETED
        upload_session.completed_at = completed_at
        await session.flush()
        return upload_session

    async def build_storage_key(
        self,
        *,
        upload_session_uuid: str,
    ) -> str:
        return f"attachments/{upload_session_uuid}/{uuid4()}"

    async def get_attachments_for_user_linking(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        conversation_id: int,
        attachment_ids: list[int],
    ) -> list[Attachment]:
        result = await session.execute(
            select(Attachment)
            .join(
                UploadSession,
                UploadSession.id == Attachment.upload_session_id,
            )
            .where(
                Attachment.id.in_(attachment_ids),
                UploadSession.user_id == user_id,
                UploadSession.conversation_id == conversation_id,
                UploadSession.completed_at.is_not(None),
                Attachment.message_id.is_(None),
                Attachment.deleted_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def link_attachments_to_message(
        self,
        session: AsyncSession,
        *,
        attachments: list[Attachment],
        message_id: int,
    ) -> None:
        from app.models.chat_enums import AttachmentStatus

        for attachment in attachments:
            attachment.message_id = message_id
            attachment.upload_status = AttachmentStatus.LINKED

        await session.flush()

    async def list_message_attachments_for_user(
        self,
        session: AsyncSession,
        *,
        message_id: int,
        user_id: int,
    ) -> list[Attachment]:
        from app.models.message import Message

        result = await session.execute(
            select(Attachment)
            .join(Message, Message.id == Attachment.message_id)
            .where(
                Attachment.message_id == message_id,
                Message.is_deleted_global.is_(False),
                (
                    (Message.sender_user_id == user_id)
                    | (Message.recipient_user_id == user_id)
                ),
            )
            .order_by(Attachment.id.asc())
        )
        return list(result.scalars().all())

    async def list_message_attachments_for_user_batch(
        self,
        session: AsyncSession,
        *,
        message_ids: list[int],
        user_id: int,
    ) -> list[Attachment]:
        if not message_ids:
            return []

        from app.models.message import Message

        result = await session.execute(
            select(Attachment)
            .join(Message, Message.id == Attachment.message_id)
            .where(
                Attachment.message_id.in_(message_ids),
                Message.is_deleted_global.is_(False),
                (
                    (Message.sender_user_id == user_id)
                    | (Message.recipient_user_id == user_id)
                ),
            )
            .order_by(Attachment.message_id.asc(), Attachment.id.asc())
        )
        return list(result.scalars().all())

    async def get_attachment_for_user(
        self,
        session: AsyncSession,
        *,
        attachment_id: int,
        user_id: int,
    ) -> Attachment | None:
        from app.models.message import Message

        result = await session.execute(
            select(Attachment)
            .join(Message, Message.id == Attachment.message_id)
            .where(
                Attachment.id == attachment_id,
                Message.is_deleted_global.is_(False),
                (
                    (Message.sender_user_id == user_id)
                    | (Message.recipient_user_id == user_id)
                ),
            )
        )
        return result.scalar_one_or_none()

    async def list_by_message_ids(
        self,
        session: AsyncSession,
        *,
        message_ids: list[int],
    ) -> list[Attachment]:
        if not message_ids:
            return []

        result = await session.execute(
            select(Attachment).where(
                Attachment.message_id.in_(message_ids),
                Attachment.deleted_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def list_by_conversation_id(
        self,
        session: AsyncSession,
        *,
        conversation_id: int,
    ) -> list[Attachment]:
        from app.models.message import Message

        result = await session.execute(
            select(Attachment)
            .outerjoin(Message, Message.id == Attachment.message_id)
            .outerjoin(
                UploadSession,
                UploadSession.id == Attachment.upload_session_id,
            )
            .where(
                or_(
                    Message.conversation_id == conversation_id,
                    UploadSession.conversation_id == conversation_id,
                )
            )
        )
        return list(result.scalars().unique().all())

    async def list_by_message_id(
        self,
        session: AsyncSession,
        *,
        message_id: int,
    ) -> list[Attachment]:
        result = await session.execute(
            select(Attachment).where(
                Attachment.message_id == message_id,
                Attachment.deleted_at.is_(None),
            )
        )
        return list(result.scalars().all())

    async def delete_attachments(
        self,
        session: AsyncSession,
        *,
        attachment_ids: list[int],
    ) -> None:
        if not attachment_ids:
            return

        await session.execute(
            delete(Attachment).where(Attachment.id.in_(attachment_ids))
        )
        await session.flush()

    async def clone_attachment(
        self,
        session: AsyncSession,
        *,
        source_attachment: Attachment,
        message_id: int,
        storage_key: str,
    ) -> Attachment:
        cloned = Attachment(
            message_id=message_id,
            upload_session_id=None,
            storage_key=storage_key,
            bucket_name=source_attachment.bucket_name,
            encrypted_file_name=source_attachment.encrypted_file_name,
            encrypted_metadata=source_attachment.encrypted_metadata,
            file_size=source_attachment.file_size,
            mime_hint=source_attachment.mime_hint,
            sha256_encrypted_blob=source_attachment.sha256_encrypted_blob,
            upload_status=AttachmentStatus.LINKED,
            expires_at=source_attachment.expires_at,
            deleted_at=None,
        )
        session.add(cloned)
        await session.flush()
        return cloned

    async def mark_attachments_deleted(
        self,
        session: AsyncSession,
        *,
        attachments: list[Attachment],
        deleted_at: datetime,
    ) -> list[int]:
        ids: list[int] = []
        for attachment in attachments:
            if attachment.deleted_at is None:
                attachment.deleted_at = deleted_at
                attachment.upload_status = AttachmentStatus.DELETED
                ids.append(attachment.id)

        await session.flush()
        return ids
