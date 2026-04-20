from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, NotFoundError
from app.models.user import User
from app.repositories.devices import DevicesRepository
from app.repositories.users import UsersRepository
from app.schemas.users import (
    UserSafetyResponseData,
    UserSearchItemSchema,
    UserSearchResponseData,
)

users_repo = UsersRepository()
devices_repo = DevicesRepository()


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
