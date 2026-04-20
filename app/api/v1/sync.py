from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.common import ApiResponse
from app.schemas.sync import ConversationEventsResponseData
from app.services.sync_service import get_conversation_events

router = APIRouter()


@router.get(
    "/conversations/{conversation_id}/events",
    response_model=ApiResponse[ConversationEventsResponseData],
)
async def get_events(
    conversation_id: int,
    after_event_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=100, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[ConversationEventsResponseData]:
    data = await get_conversation_events(
        session,
        current_user=current_user,
        conversation_id=conversation_id,
        after_event_id=after_event_id,
        limit=limit,
    )
    return ApiResponse(data=data)
