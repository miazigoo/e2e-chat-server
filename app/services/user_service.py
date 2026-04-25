from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from fastapi import UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.core.storage import (
    build_presigned_get_url,
    delete_object_if_exists,
    upload_bytes,
)
from app.models.user import User
from app.repositories.devices import DevicesRepository
from app.repositories.users import UsersRepository
from app.schemas.users import (
    UpdateUserProfileRequest,
    UserProfileResponseData,
    UserProfileSettingsSchema,
    UserPublicProfileResponseData,
    UserSafetyResponseData,
    UserSearchItemSchema,
    UserSearchResponseData,
)

users_repo = UsersRepository()
devices_repo = DevicesRepository()

ALLOWED_PROFILE_THEMES = {"light", "dark", "system"}


def _normalize_nickname(nickname: str) -> str:
    normalized = nickname.strip()
    if not normalized:
        raise BadRequestError(
            code="INVALID_NICKNAME",
            message="nickname cannot be blank",
        )
    return normalized


def _is_nickname_integrity_error(exc: IntegrityError) -> bool:
    details = str(exc.orig).lower()
    return "nickname" in details


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _build_avatar_url(user: User) -> str | None:
    if not user.avatar_bucket_name or not user.avatar_storage_key:
        return None
    return await build_presigned_get_url(
        bucket_name=user.avatar_bucket_name,
        object_name=user.avatar_storage_key,
    )


async def _build_profile_response(user: User) -> UserProfileResponseData:
    return UserProfileResponseData(
        user_id=user.id,
        public_id=user.public_id,
        nickname=user.nickname,
        full_name=user.full_name,
        bio=user.bio,
        avatar_url=await _build_avatar_url(user),
        avatar_updated_at=user.avatar_updated_at,
        created_at=user.created_at,
        settings=UserProfileSettingsSchema(
            language_code=user.language_code,
            theme=user.theme,
            push_notifications_enabled=user.push_notifications_enabled,
            apk_update_notifications_enabled=user.apk_update_notifications_enabled,
            google_2fa_enabled=user.google_2fa_enabled,
        ),
    )


async def _build_public_profile_response(user: User) -> UserPublicProfileResponseData:
    return UserPublicProfileResponseData(
        user_id=user.id,
        public_id=user.public_id,
        nickname=user.nickname,
        full_name=user.full_name,
        bio=user.bio,
        avatar_url=await _build_avatar_url(user),
        avatar_updated_at=user.avatar_updated_at,
        created_at=user.created_at,
    )


async def search_users(
    session: AsyncSession,
    *,
    current_user: User,
    query: str,
    limit: int,
) -> UserSearchResponseData:
    normalized_query = query.strip()
    if not normalized_query:
        return UserSearchResponseData(items=[])

    users = await users_repo.search_by_nickname_prefix(
        session,
        query=normalized_query,
        limit=limit,
        exclude_user_id=current_user.id,
    )

    items = [
        UserSearchItemSchema(
            user_id=user.id,
            nickname=user.nickname,
        )
        for user in users
        if not user.pending_deletion
    ]

    return UserSearchResponseData(items=items)


async def get_user_safety(
    session: AsyncSession,
    *,
    current_user: User,
    target_user_id: int,
) -> UserSafetyResponseData:
    if target_user_id == current_user.id:
        raise BadRequestError(
            code="SELF_TARGET_NOT_ALLOWED",
            message="Cannot inspect yourself as target user",
        )

    user = await users_repo.get_by_id(session, target_user_id)
    if user is None or user.is_deleted:
        raise NotFoundError(
            code="USER_NOT_FOUND",
            message="User not found",
        )

    active_device = await devices_repo.get_active_by_user_id(
        session,
        user_id=user.id,
    )

    has_active_device = active_device is not None

    return UserSafetyResponseData(
        user_id=user.id,
        nickname=user.nickname,
        can_start_conversation=(not user.pending_deletion and has_active_device),
        is_deleted=user.is_deleted,
        pending_deletion=user.pending_deletion,
        has_active_device=has_active_device,
        supports_encrypted_chat=has_active_device,
        safety_code_available=has_active_device,
    )


async def get_my_profile(
    session: AsyncSession,
    *,
    current_user: User,
) -> UserProfileResponseData:
    db_user = await users_repo.get_by_id(session, current_user.id)
    if db_user is None or db_user.is_deleted:
        raise NotFoundError(code="USER_NOT_FOUND", message="User not found")
    return await _build_profile_response(db_user)


async def get_user_profile(
    session: AsyncSession,
    *,
    current_user: User,
    target_user_id: int,
) -> UserPublicProfileResponseData:
    _ = current_user
    user = await users_repo.get_by_id(session, target_user_id)
    if user is None or user.is_deleted:
        raise NotFoundError(code="USER_NOT_FOUND", message="User not found")
    return await _build_public_profile_response(user)


async def update_my_profile(
    session: AsyncSession,
    *,
    current_user: User,
    payload: UpdateUserProfileRequest,
) -> UserProfileResponseData:
    user = await users_repo.get_by_id(session, current_user.id)
    if user is None or user.is_deleted:
        raise NotFoundError(code="USER_NOT_FOUND", message="User not found")

    if payload.nickname is not None:
        nickname = _normalize_nickname(payload.nickname)
        if nickname != user.nickname:
            existing = await users_repo.get_by_nickname(session, nickname)
            if existing is not None and existing.id != user.id:
                raise BadRequestError(
                    code="NICKNAME_ALREADY_TAKEN",
                    message="Nickname is already taken",
                )
            user.nickname = nickname

    if payload.full_name is not None:
        user.full_name = payload.full_name.strip() or None

    if payload.bio is not None:
        user.bio = payload.bio.strip() or None

    if payload.language_code is not None:
        language_code = payload.language_code.strip().lower()
        if len(language_code) < 2:
            raise BadRequestError(
                code="INVALID_LANGUAGE_CODE",
                message="language_code is invalid",
            )
        user.language_code = language_code

    if payload.theme is not None:
        theme = payload.theme.strip().lower()
        if theme not in ALLOWED_PROFILE_THEMES:
            raise BadRequestError(
                code="INVALID_THEME",
                message="theme must be one of: light, dark, system",
            )
        user.theme = theme

    if payload.push_notifications_enabled is not None:
        user.push_notifications_enabled = payload.push_notifications_enabled

    if payload.apk_update_notifications_enabled is not None:
        user.apk_update_notifications_enabled = payload.apk_update_notifications_enabled

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if not _is_nickname_integrity_error(exc):
            raise
        raise ConflictError(
            code="NICKNAME_ALREADY_TAKEN",
            message="Nickname is already taken",
        ) from exc
    await session.refresh(user)
    return await _build_profile_response(user)


async def upload_my_avatar(
    session: AsyncSession,
    *,
    current_user: User,
    file: UploadFile,
) -> UserProfileResponseData:
    user = await users_repo.get_by_id(session, current_user.id)
    if user is None or user.is_deleted:
        raise NotFoundError(code="USER_NOT_FOUND", message="User not found")

    content_type = (file.content_type or "").lower()
    if not content_type.startswith("image/"):
        raise BadRequestError(
            code="INVALID_AVATAR_TYPE",
            message="Avatar must be an image",
        )

    data = await file.read()
    if not data:
        raise BadRequestError(
            code="EMPTY_AVATAR",
            message="Avatar file is empty",
        )
    if len(data) > settings.avatar_max_bytes:
        raise BadRequestError(
            code="AVATAR_TOO_LARGE",
            message="Avatar exceeds configured size limit",
        )

    suffix = Path(file.filename or "").suffix.lower()
    safe_suffix = suffix[:10] if suffix.startswith(".") else ""
    storage_key = f"avatars/{user.public_id}/{uuid4().hex}{safe_suffix}"

    await upload_bytes(
        bucket_name=settings.minio_bucket_assets,
        object_name=storage_key,
        data=data,
        content_type=content_type,
    )

    old_bucket_name = user.avatar_bucket_name
    old_storage_key = user.avatar_storage_key

    user.avatar_bucket_name = settings.minio_bucket_assets
    user.avatar_storage_key = storage_key
    user.avatar_content_type = content_type
    user.avatar_updated_at = _now()

    await session.commit()
    await session.refresh(user)

    if old_bucket_name and old_storage_key and old_storage_key != storage_key:
        await delete_object_if_exists(
            bucket_name=old_bucket_name,
            object_name=old_storage_key,
        )

    return await _build_profile_response(user)


async def delete_my_avatar(
    session: AsyncSession,
    *,
    current_user: User,
) -> UserProfileResponseData:
    user = await users_repo.get_by_id(session, current_user.id)
    if user is None or user.is_deleted:
        raise NotFoundError(code="USER_NOT_FOUND", message="User not found")

    old_bucket_name = user.avatar_bucket_name
    old_storage_key = user.avatar_storage_key

    user.avatar_bucket_name = None
    user.avatar_storage_key = None
    user.avatar_content_type = None
    user.avatar_updated_at = None

    await session.commit()
    await session.refresh(user)

    if old_bucket_name and old_storage_key:
        await delete_object_if_exists(
            bucket_name=old_bucket_name,
            object_name=old_storage_key,
        )

    return await _build_profile_response(user)
