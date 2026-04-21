from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.storage import build_presigned_get_url
from app.models.attachment import Attachment
from app.models.user import User
from app.repositories.files import FilesRepository
from app.schemas.files import (
    AttachmentMetadataItemSchema,
    GetAttachmentResponseData,
    ListMessageAttachmentsResponseData,
)

files_repo = FilesRepository()


def _attachment_to_schema(attachment: Attachment) -> AttachmentMetadataItemSchema:
    return AttachmentMetadataItemSchema(
        attachment_id=attachment.id,
        attachment_uuid=attachment.attachment_uuid,
        message_id=attachment.message_id,
        encrypted_file_name=attachment.encrypted_file_name,
        encrypted_metadata=attachment.encrypted_metadata,
        file_size=attachment.file_size,
        mime_hint=attachment.mime_hint,
        sha256_encrypted_blob=attachment.sha256_encrypted_blob,
        bucket_name=attachment.bucket_name,
        storage_key=attachment.storage_key,
        upload_status=(
            attachment.upload_status.value
            if hasattr(attachment.upload_status, "value")
            else str(attachment.upload_status)
        ),
        created_at=attachment.created_at,
        expires_at=attachment.expires_at,
        deleted_at=attachment.deleted_at,
    )


async def list_message_attachments(
    session: AsyncSession,
    *,
    current_user: User,
    message_id: int,
) -> ListMessageAttachmentsResponseData:
    attachments = await files_repo.list_message_attachments_for_user(
        session,
        message_id=message_id,
        user_id=current_user.id,
    )

    return ListMessageAttachmentsResponseData(
        message_id=message_id,
        items=[_attachment_to_schema(att) for att in attachments],
    )


async def get_attachment_metadata(
    session: AsyncSession,
    *,
    current_user: User,
    attachment_id: int,
) -> GetAttachmentResponseData:
    attachment = await files_repo.get_attachment_for_user(
        session,
        attachment_id=attachment_id,
        user_id=current_user.id,
    )
    if attachment is None:
        raise NotFoundError(
            code="ATTACHMENT_NOT_FOUND",
            message="Attachment not found",
        )

    can_download = attachment.deleted_at is None
    download_url = None
    expires_in = None

    if can_download:
        expires_in = settings.presigned_download_expire_seconds
        download_url = await build_presigned_get_url(
            bucket_name=attachment.bucket_name,
            object_name=attachment.storage_key,
        )

    return GetAttachmentResponseData(
        **_attachment_to_schema(attachment).model_dump(),
        can_download=can_download,
        download_url=download_url,
        download_url_expires_in=expires_in,
    )
