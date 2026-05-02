from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import NotFoundError
from app.core.storage import build_presigned_get_url
from app.models.attachment import Attachment
from app.models.user import User
from app.repositories.files import FilesRepository
from app.repositories.media_tags import MediaTagsRepository
from app.schemas.files import (
    AttachmentMetadataItemSchema,
    BatchMessageAttachmentsResponseData,
    GetAttachmentResponseData,
    ListMessageAttachmentsResponseData,
    MessageAttachmentsGroupSchema,
)
from app.schemas.media_tags import MediaTagSchema

files_repo = FilesRepository()
media_tags_repo = MediaTagsRepository()


def _attachment_to_schema(
    attachment: Attachment,
    *,
    media_tags: list[MediaTagSchema] | None = None,
) -> AttachmentMetadataItemSchema:
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
        media_tags=media_tags or [],
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
    tags_by_attachment_id = await media_tags_repo.list_tags_for_attachments(
        session,
        attachment_ids=[attachment.id for attachment in attachments],
    )

    return ListMessageAttachmentsResponseData(
        message_id=message_id,
        items=[
            _attachment_to_schema(
                att,
                media_tags=[
                    MediaTagSchema(
                        tag_id=tag.id,
                        conversation_id=tag.conversation_id,
                        name=tag.name,
                        color=tag.color,
                        created_by_user_id=tag.created_by_user_id,
                        created_at=tag.created_at,
                        updated_at=tag.updated_at,
                    )
                    for tag in tags_by_attachment_id.get(att.id, [])
                ],
            )
            for att in attachments
        ],
    )


async def list_attachments_for_messages(
    session: AsyncSession,
    *,
    current_user: User,
    message_ids: list[int],
) -> BatchMessageAttachmentsResponseData:
    attachments = await files_repo.list_message_attachments_for_user_batch(
        session,
        message_ids=message_ids,
        user_id=current_user.id,
    )
    tags_by_attachment_id = await media_tags_repo.list_tags_for_attachments(
        session,
        attachment_ids=[attachment.id for attachment in attachments],
    )

    attachments_by_message_id: dict[int, list[AttachmentMetadataItemSchema]] = {
        message_id: [] for message_id in message_ids
    }
    for attachment in attachments:
        message_id = attachment.message_id
        if message_id is None:
            continue
        attachments_by_message_id.setdefault(message_id, []).append(
            _attachment_to_schema(
                attachment,
                media_tags=[
                    MediaTagSchema(
                        tag_id=tag.id,
                        conversation_id=tag.conversation_id,
                        name=tag.name,
                        color=tag.color,
                        created_by_user_id=tag.created_by_user_id,
                        created_at=tag.created_at,
                        updated_at=tag.updated_at,
                    )
                    for tag in tags_by_attachment_id.get(attachment.id, [])
                ],
            )
        )

    return BatchMessageAttachmentsResponseData(
        items=[
            MessageAttachmentsGroupSchema(
                message_id=message_id,
                items=attachments_by_message_id.get(message_id, []),
            )
            for message_id in message_ids
        ]
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
    tags_by_attachment_id = await media_tags_repo.list_tags_for_attachments(
        session,
        attachment_ids=[attachment.id],
    )
    media_tags = [
        MediaTagSchema(
            tag_id=tag.id,
            conversation_id=tag.conversation_id,
            name=tag.name,
            color=tag.color,
            created_by_user_id=tag.created_by_user_id,
            created_at=tag.created_at,
            updated_at=tag.updated_at,
        )
        for tag in tags_by_attachment_id.get(attachment.id, [])
    ]

    return GetAttachmentResponseData(
        **_attachment_to_schema(attachment, media_tags=media_tags).model_dump(),
        can_download=can_download,
        download_url=download_url,
        download_url_expires_in=expires_in,
    )
