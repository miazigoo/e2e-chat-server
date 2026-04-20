from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.chat_enums import UploadSessionStatus
from app.models.user import User
from app.repositories.conversations import ConversationsRepository
from app.repositories.files import FilesRepository
from app.schemas.files import (
    AttachmentInitItemSchema,
    CompleteUploadSessionRequest,
    CompleteUploadSessionResponseData,
    CreateUploadSessionRequest,
    CreateUploadSessionResponseData,
    InitAttachmentsRequest,
    InitAttachmentsResponseData,
)

files_repo = FilesRepository()
conversations_repo = ConversationsRepository()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _session_expires_at() -> datetime:
    return _now() + timedelta(hours=1)


def _temp_bucket_name() -> str:
    # Совместимость с разными вариантами naming в Settings.
    if hasattr(settings, "MINIO_BUCKET_TEMP"):
        return str(settings.MINIO_BUCKET_TEMP)
    if hasattr(settings, "minio_bucket_temp"):
        return str(settings.minio_bucket_temp)
    raise RuntimeError("MINIO temp bucket setting is not configured")


async def create_upload_session(
    session: AsyncSession,
    *,
    current_user: User,
    payload: CreateUploadSessionRequest,
) -> CreateUploadSessionResponseData:
    conversation = await conversations_repo.get_for_user(
        session,
        conversation_id=payload.conversation_id,
        user_id=current_user.id,
    )
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "CONVERSATION_NOT_FOUND",
                "message": "Conversation not found",
            },
        )

    upload_session = await files_repo.create_upload_session(
        session,
        user_id=current_user.id,
        conversation_id=payload.conversation_id,
        files_expected_count=payload.files_expected_count,
        expires_at=_session_expires_at(),
    )

    await session.commit()

    return CreateUploadSessionResponseData(
        session_id=upload_session.id,
        session_uuid=upload_session.session_uuid,
        conversation_id=upload_session.conversation_id,
        files_expected_count=upload_session.files_expected_count,
        files_uploaded_count=upload_session.files_uploaded_count,
        status=(
            upload_session.status.value
            if hasattr(upload_session.status, "value")
            else str(upload_session.status)
        ),
        expires_at=upload_session.expires_at,
    )


async def init_attachments(
    session: AsyncSession,
    *,
    current_user: User,
    session_id: int,
    payload: InitAttachmentsRequest,
) -> InitAttachmentsResponseData:
    upload_session = await files_repo.get_upload_session_for_user(
        session,
        session_id=session_id,
        user_id=current_user.id,
    )
    if upload_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "UPLOAD_SESSION_NOT_FOUND",
                "message": "Upload session not found",
            },
        )

    if upload_session.completed_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "UPLOAD_SESSION_ALREADY_COMPLETED",
                "message": "Upload session already completed",
            },
        )

    if upload_session.expires_at <= _now():
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={
                "code": "UPLOAD_SESSION_EXPIRED",
                "message": "Upload session expired",
            },
        )

    existing_attachments = await files_repo.list_attachments_for_session(
        session,
        upload_session_id=upload_session.id,
    )
    if (
        len(existing_attachments) + len(payload.items)
        > upload_session.files_expected_count
    ):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "TOO_MANY_ATTACHMENTS",
                "message": "Too many attachments for this upload session",
            },
        )

    created_items: list[AttachmentInitItemSchema] = []

    for item in payload.items:
        storage_key = await files_repo.build_storage_key(
            upload_session_uuid=upload_session.session_uuid
        )
        attachment = await files_repo.create_attachment(
            session,
            upload_session_id=upload_session.id,
            bucket_name=_temp_bucket_name(),
            storage_key=storage_key,
            encrypted_file_name=item.encrypted_file_name,
            encrypted_metadata=item.encrypted_metadata,
            file_size=item.file_size,
            mime_hint=item.mime_hint,
            sha256_encrypted_blob=item.sha256_encrypted_blob,
            expires_at=upload_session.expires_at,
        )
        created_items.append(
            AttachmentInitItemSchema(
                attachment_id=attachment.id,
                attachment_uuid=attachment.attachment_uuid,
                storage_key=attachment.storage_key,
                bucket_name=attachment.bucket_name,
                upload_status=(
                    attachment.upload_status.value
                    if hasattr(attachment.upload_status, "value")
                    else str(attachment.upload_status)
                ),
                expires_at=attachment.expires_at,
            )
        )

    upload_session.status = UploadSessionStatus.UPLOADING

    await session.commit()

    return InitAttachmentsResponseData(
        session_id=upload_session.id,
        session_uuid=upload_session.session_uuid,
        items=created_items,
    )


async def complete_upload_session(
    session: AsyncSession,
    *,
    current_user: User,
    session_id: int,
    payload: CompleteUploadSessionRequest,
) -> CompleteUploadSessionResponseData:
    upload_session = await files_repo.get_upload_session_for_user(
        session,
        session_id=session_id,
        user_id=current_user.id,
    )
    if upload_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={
                "code": "UPLOAD_SESSION_NOT_FOUND",
                "message": "Upload session not found",
            },
        )

    if upload_session.completed_at is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "UPLOAD_SESSION_ALREADY_COMPLETED",
                "message": "Upload session already completed",
            },
        )

    if upload_session.expires_at <= _now():
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail={
                "code": "UPLOAD_SESSION_EXPIRED",
                "message": "Upload session expired",
            },
        )

    attachments = await files_repo.mark_attachments_uploaded(
        session,
        upload_session_id=upload_session.id,
        attachment_ids=payload.attachment_ids,
    )

    if len(attachments) != len(payload.attachment_ids):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "INVALID_ATTACHMENT_IDS",
                "message": "One or more attachment ids are invalid for this session",
            },
        )

    completed_at = _now()
    upload_session = await files_repo.complete_upload_session(
        session,
        upload_session=upload_session,
        files_uploaded_count=len(attachments),
        completed_at=completed_at,
    )

    await session.commit()

    return CompleteUploadSessionResponseData(
        session_id=upload_session.id,
        session_uuid=upload_session.session_uuid,
        status=(
            upload_session.status.value
            if hasattr(upload_session.status, "value")
            else str(upload_session.status)
        ),
        files_expected_count=upload_session.files_expected_count,
        files_uploaded_count=upload_session.files_uploaded_count,
        completed_at=completed_at,
    )
