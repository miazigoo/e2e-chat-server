from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.models.attachment import ConversationMediaTag
from app.models.user import User
from app.repositories.conversations import ConversationsRepository
from app.repositories.files import FilesRepository
from app.repositories.media_tags import MediaTagsRepository
from app.schemas.media_tags import (
    AssignAttachmentTagsRequest,
    AttachmentTagsResponseData,
    CreateMediaTagRequest,
    ListMediaTagsResponseData,
    MediaTagSchema,
    UpdateMediaTagRequest,
)

conversations_repo = ConversationsRepository()
files_repo = FilesRepository()
media_tags_repo = MediaTagsRepository()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_name(name: str) -> str:
    return " ".join(name.strip().lower().split())


def _tag_schema(tag: ConversationMediaTag) -> MediaTagSchema:
    return MediaTagSchema(
        tag_id=tag.id,
        conversation_id=tag.conversation_id,
        name=tag.name,
        color=tag.color,
        created_by_user_id=tag.created_by_user_id,
        created_at=tag.created_at,
        updated_at=tag.updated_at,
    )


async def _ensure_conversation_access(
    session: AsyncSession,
    *,
    conversation_id: int,
    user_id: int,
) -> None:
    participant = await conversations_repo.get_participant(
        session,
        conversation_id=conversation_id,
        user_id=user_id,
    )
    if participant is None:
        raise NotFoundError(
            code="CONVERSATION_NOT_FOUND",
            message="Conversation not found",
        )


async def list_media_tags(
    session: AsyncSession,
    *,
    current_user: User,
    conversation_id: int,
) -> ListMediaTagsResponseData:
    await _ensure_conversation_access(
        session,
        conversation_id=conversation_id,
        user_id=current_user.id,
    )
    tags = await media_tags_repo.list_for_conversation(
        session,
        conversation_id=conversation_id,
    )
    return ListMediaTagsResponseData(items=[_tag_schema(tag) for tag in tags])


async def create_media_tag(
    session: AsyncSession,
    *,
    current_user: User,
    conversation_id: int,
    payload: CreateMediaTagRequest,
) -> MediaTagSchema:
    await _ensure_conversation_access(
        session,
        conversation_id=conversation_id,
        user_id=current_user.id,
    )
    normalized_name = _normalize_name(payload.name)
    if not normalized_name:
        raise BadRequestError(code="INVALID_MEDIA_TAG", message="Invalid tag name")

    try:
        tag = await media_tags_repo.create(
            session,
            conversation_id=conversation_id,
            name=payload.name.strip(),
            normalized_name=normalized_name,
            color=payload.color,
            created_by_user_id=current_user.id,
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError(
            code="MEDIA_TAG_ALREADY_EXISTS",
            message="Media tag already exists",
        ) from exc

    return _tag_schema(tag)


async def update_media_tag(
    session: AsyncSession,
    *,
    current_user: User,
    conversation_id: int,
    tag_id: int,
    payload: UpdateMediaTagRequest,
) -> MediaTagSchema:
    await _ensure_conversation_access(
        session,
        conversation_id=conversation_id,
        user_id=current_user.id,
    )
    tag = await media_tags_repo.get_for_conversation(
        session,
        conversation_id=conversation_id,
        tag_id=tag_id,
    )
    if tag is None:
        raise NotFoundError(code="MEDIA_TAG_NOT_FOUND", message="Media tag not found")

    normalized_name = (
        _normalize_name(payload.name) if payload.name is not None else None
    )
    color = payload.color if "color" in payload.model_fields_set else tag.color
    try:
        tag = await media_tags_repo.update(
            session,
            tag=tag,
            name=payload.name.strip() if payload.name is not None else None,
            normalized_name=normalized_name,
            color=color,
            updated_at=_now(),
        )
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        raise ConflictError(
            code="MEDIA_TAG_ALREADY_EXISTS",
            message="Media tag already exists",
        ) from exc

    return _tag_schema(tag)


async def delete_media_tag(
    session: AsyncSession,
    *,
    current_user: User,
    conversation_id: int,
    tag_id: int,
) -> dict:
    await _ensure_conversation_access(
        session,
        conversation_id=conversation_id,
        user_id=current_user.id,
    )
    tag = await media_tags_repo.get_for_conversation(
        session,
        conversation_id=conversation_id,
        tag_id=tag_id,
    )
    if tag is None:
        raise NotFoundError(code="MEDIA_TAG_NOT_FOUND", message="Media tag not found")

    await media_tags_repo.delete(session, tag=tag)
    await session.commit()
    return {"tag_id": tag_id, "deleted": True}


async def validate_tags_for_conversation(
    session: AsyncSession,
    *,
    conversation_id: int,
    tag_ids: list[int],
) -> list[ConversationMediaTag]:
    tags = await media_tags_repo.list_by_ids_for_conversation(
        session,
        conversation_id=conversation_id,
        tag_ids=tag_ids,
    )
    if len(tags) != len(set(tag_ids)):
        raise BadRequestError(
            code="INVALID_MEDIA_TAGS",
            message="One or more media tags are invalid for this conversation",
        )
    return tags


async def assign_tags_to_attachments(
    session: AsyncSession,
    *,
    current_user: User,
    attachment_id: int,
    payload: AssignAttachmentTagsRequest,
) -> AttachmentTagsResponseData:
    attachment = await files_repo.get_attachment_for_user(
        session,
        attachment_id=attachment_id,
        user_id=current_user.id,
    )
    if attachment is None or attachment.message_id is None:
        raise NotFoundError(code="ATTACHMENT_NOT_FOUND", message="Attachment not found")

    from app.repositories.messages import MessagesRepository

    message = await MessagesRepository().get_by_id(
        session,
        message_id=attachment.message_id,
    )
    if message is None:
        raise NotFoundError(code="ATTACHMENT_NOT_FOUND", message="Attachment not found")

    await validate_tags_for_conversation(
        session,
        conversation_id=message.conversation_id,
        tag_ids=payload.tag_ids,
    )
    await media_tags_repo.add_tags_to_attachments(
        session,
        attachment_ids=[attachment_id],
        tag_ids=payload.tag_ids,
        tagged_by_user_id=current_user.id,
    )
    await session.commit()

    tags_by_attachment_id = await media_tags_repo.list_tags_for_attachments(
        session,
        attachment_ids=[attachment_id],
    )
    return AttachmentTagsResponseData(
        attachment_id=attachment_id,
        items=[
            _tag_schema(tag) for tag in tags_by_attachment_id.get(attachment_id, [])
        ],
    )


async def remove_tag_from_attachment(
    session: AsyncSession,
    *,
    current_user: User,
    attachment_id: int,
    tag_id: int,
) -> AttachmentTagsResponseData:
    attachment = await files_repo.get_attachment_for_user(
        session,
        attachment_id=attachment_id,
        user_id=current_user.id,
    )
    if attachment is None:
        raise NotFoundError(code="ATTACHMENT_NOT_FOUND", message="Attachment not found")

    await media_tags_repo.remove_tag_from_attachment(
        session,
        attachment_id=attachment_id,
        tag_id=tag_id,
    )
    await session.commit()

    tags_by_attachment_id = await media_tags_repo.list_tags_for_attachments(
        session,
        attachment_ids=[attachment_id],
    )
    return AttachmentTagsResponseData(
        attachment_id=attachment_id,
        items=[
            _tag_schema(tag) for tag in tags_by_attachment_id.get(attachment_id, [])
        ],
    )
