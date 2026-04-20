from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.common import ApiResponse
from app.schemas.users import UserSafetyResponseData, UserSearchResponseData
from app.services.user_service import get_user_safety, search_users

router = APIRouter()


@router.get(
    "/search",
    response_model=ApiResponse[UserSearchResponseData],
)
async def search_users_endpoint(
    q: str = Query(min_length=1, max_length=255),
    limit: int = Query(default=20, ge=1, le=50),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[UserSearchResponseData]:
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
)
async def get_user_safety_endpoint(
    user_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[UserSafetyResponseData]:
    data = await get_user_safety(
        session,
        current_user=current_user,
        target_user_id=user_id,
    )
    return ApiResponse(data=data)
