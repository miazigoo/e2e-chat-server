from fastapi import APIRouter, Depends, File, Query, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.common import ApiResponse
from app.schemas.users import (
    UpdateUserProfileRequest,
    UserProfileResponseData,
    UserPublicProfileResponseData,
    UserSafetyResponseData,
    UserSearchResponseData,
)
from app.services.user_service import (
    delete_my_avatar,
    get_my_profile,
    get_user_profile,
    get_user_safety,
    search_users,
    update_my_profile,
    upload_my_avatar,
)

router = APIRouter()


@router.get(
    "/me",
    response_model=ApiResponse[UserProfileResponseData],
    summary="Get my profile",
    description="Return the authenticated user's full profile and private settings.",
)
async def get_my_profile_endpoint(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[UserProfileResponseData]:
    """Fetch the authenticated user's profile, avatar and settings."""
    data = await get_my_profile(session, current_user=current_user)
    return ApiResponse(data=data)


@router.patch(
    "/me",
    response_model=ApiResponse[UserProfileResponseData],
    summary="Update my profile",
    description="Update editable profile fields and notification preferences.",
)
async def update_my_profile_endpoint(
    payload: UpdateUserProfileRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[UserProfileResponseData]:
    """Update editable profile fields for the authenticated user."""
    data = await update_my_profile(
        session,
        current_user=current_user,
        payload=payload,
    )
    return ApiResponse(data=data)


@router.post(
    "/me/avatar",
    response_model=ApiResponse[UserProfileResponseData],
    summary="Upload my avatar",
    description="Upload or replace the authenticated user's avatar image.",
)
async def upload_my_avatar_endpoint(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[UserProfileResponseData]:
    """Upload a new avatar image for the authenticated user."""
    data = await upload_my_avatar(
        session,
        current_user=current_user,
        file=file,
    )
    return ApiResponse(data=data)


@router.delete(
    "/me/avatar",
    response_model=ApiResponse[UserProfileResponseData],
    summary="Delete my avatar",
    description="Remove the authenticated user's current avatar.",
)
async def delete_my_avatar_endpoint(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[UserProfileResponseData]:
    """Delete the current avatar for the authenticated user."""
    data = await delete_my_avatar(
        session,
        current_user=current_user,
    )
    return ApiResponse(data=data)


@router.get(
    "/search",
    response_model=ApiResponse[UserSearchResponseData],
    summary="Search users",
    description="Search users by nickname prefix excluding the authenticated user.",
)
async def search_users_endpoint(
    q: str = Query(min_length=1, max_length=255),
    limit: int = Query(default=20, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[UserSearchResponseData]:
    """Search users by nickname prefix."""
    data = await search_users(
        session,
        current_user=current_user,
        query=q,
        limit=limit,
    )
    return ApiResponse(data=data)


@router.get(
    "/{user_id}/safety",
    response_model=ApiResponse[UserSafetyResponseData],
    summary="Get user safety state",
    description=(
        "Return whether a secure conversation can be started with the target user."
    ),
)
async def get_user_safety_endpoint(
    user_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[UserSafetyResponseData]:
    """Inspect the target user's conversation readiness and encryption status."""
    data = await get_user_safety(
        session,
        current_user=current_user,
        target_user_id=user_id,
    )
    return ApiResponse(data=data)


@router.get(
    "/{user_id}/profile",
    response_model=ApiResponse[UserPublicProfileResponseData],
    summary="Get public user profile",
    description=("Return the target user's public profile without private settings."),
)
async def get_user_profile_endpoint(
    user_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[UserPublicProfileResponseData]:
    """Fetch the public profile for another user."""
    data = await get_user_profile(
        session,
        current_user=current_user,
        target_user_id=user_id,
    )
    return ApiResponse(data=data)
