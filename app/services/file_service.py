from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BadRequestError, ConflictError, GoneError, NotFoundError
from app.core.storage import build_presigned_put_url, object_exists
from app.models.chat_enums import UploadSessionStatus
from app.models.conversation import Conversation
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


def _attachments_bucket_name() -> str:
    return settings.minio_bucket_attachments


def _ensure_conversation_upload_available(conversation: Conversation) -> None:
    if conversation.is_purged:
        raise GoneError(
            code="CONVERSATION_PURGED",
            message="Conversation is purged",
        )

    if not conversation.is_active:
        raise ConflictError(
            code="CONVERSATION_INACTIVE",
            message="Conversation is inactive",
        )


async def _get_uploadable_conversation(
    session: AsyncSession,
    *,
    user_id: int,
    conversation_id: int,
) -> Conversation:
    conversation = await conversations_repo.get_for_user(
        session,
        conversation_id=conversation_id,
        user_id=user_id,
    )
    if conversation is None:
        raise NotFoundError(
            code="CONVERSATION_NOT_FOUND",
            message="Conversation not found",
        )

    _ensure_conversation_upload_available(conversation)
    return conversation


async def create_upload_session(
    session: AsyncSession,
    *,
    current_user: User,
    payload: CreateUploadSessionRequest,
) -> CreateUploadSessionResponseData:
    conversation = await _get_uploadable_conversation(
        session,
        user_id=current_user.id,
        conversation_id=payload.conversation_id,
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
        conversation_id=conversation.id,
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
        raise NotFoundError(
            code="UPLOAD_SESSION_NOT_FOUND",
            message="Upload session not found",
        )

    await _get_uploadable_conversation(
        session,
        user_id=current_user.id,
        conversation_id=upload_session.conversation_id,
    )

    if upload_session.completed_at is not None:
        raise ConflictError(
            code="UPLOAD_SESSION_ALREADY_COMPLETED",
            message="Upload session already completed",
        )

    if upload_session.expires_at <= _now():
        raise GoneError(
            code="UPLOAD_SESSION_EXPIRED",
            message="Upload session expired",
        )

    existing_attachments = await files_repo.list_attachments_for_session(
        session,
        upload_session_id=upload_session.id,
    )
    if (
        len(existing_attachments) + len(payload.items)
        > upload_session.files_expected_count
    ):
        raise BadRequestError(
            code="TOO_MANY_ATTACHMENTS",
            message="Too many attachments for this upload session",
        )

    created_items: list[AttachmentInitItemSchema] = []

    for item in payload.items:
        storage_key = await files_repo.build_storage_key(
            upload_session_uuid=upload_session.session_uuid
        )
        attachment = await files_repo.create_attachment(
            session,
            upload_session_id=upload_session.id,
            bucket_name=_attachments_bucket_name(),
            storage_key=storage_key,
            encrypted_file_name=item.encrypted_file_name,
            encrypted_metadata=item.encrypted_metadata,
            file_size=item.file_size,
            mime_hint=item.mime_hint,
            sha256_encrypted_blob=item.sha256_encrypted_blob,
            expires_at=upload_session.expires_at,
        )

        upload_url = await build_presigned_put_url(
            bucket_name=attachment.bucket_name,
            object_name=attachment.storage_key,
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
                upload_url=upload_url,
                upload_method="PUT",
                upload_headers={},
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
        raise NotFoundError(
            code="UPLOAD_SESSION_NOT_FOUND",
            message="Upload session not found",
        )

    await _get_uploadable_conversation(
        session,
        user_id=current_user.id,
        conversation_id=upload_session.conversation_id,
    )

    if upload_session.completed_at is not None:
        raise ConflictError(
            code="UPLOAD_SESSION_ALREADY_COMPLETED",
            message="Upload session already completed",
        )

    if upload_session.expires_at <= _now():
        raise GoneError(
            code="UPLOAD_SESSION_EXPIRED",
            message="Upload session expired",
        )

    session_attachments = await files_repo.list_attachments_for_session(
        session,
        upload_session_id=upload_session.id,
    )
    attachment_by_id = {attachment.id: attachment for attachment in session_attachments}

    if len(payload.attachment_ids) != len(set(payload.attachment_ids)):
        raise BadRequestError(
            code="DUPLICATE_ATTACHMENT_IDS",
            message="attachment_ids must be unique",
        )

    for attachment_id in payload.attachment_ids:
        attachment = attachment_by_id.get(attachment_id)
        if attachment is None:
            raise BadRequestError(
                code="INVALID_ATTACHMENT_IDS",
                message="One or more attachment ids are invalid for this session",
            )
        exists = await object_exists(
            bucket_name=attachment.bucket_name,
            object_name=attachment.storage_key,
        )
        if not exists:
            raise BadRequestError(
                code="UPLOAD_OBJECT_MISSING",
                message="One or more uploaded objects are missing in storage",
            )

    attachments = await files_repo.mark_attachments_uploaded(
        session,
        upload_session_id=upload_session.id,
        attachment_ids=payload.attachment_ids,
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
