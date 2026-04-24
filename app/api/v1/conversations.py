from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import COMMON_ERROR_RESPONSES
from app.core.db import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.common import ApiResponse
from app.schemas.conversations import (
    ClearConversationRequest,
    ClearConversationResponseData,
    ConversationSettingsResponseData,
    CreateConversationRequest,
    CreateConversationResponseData,
    GetConversationResponseData,
    ListConversationsResponseData,
    UpdateConversationRequest,
    UpdateConversationResponseData,
    UpdateConversationSettingsRequest,
)
from app.schemas.messages import ListMessagesResponseData
from app.services.conversation_service import (
    clear_global,
    clear_local,
    create_conversation,
    get_conversation,
    list_conversations,
    update_conversation,
    update_conversation_settings,
)
from app.services.message_service import list_messages

router = APIRouter()


@router.post(
    "",
    response_model=ApiResponse[CreateConversationResponseData],
    responses=COMMON_ERROR_RESPONSES,
)
async def create_conversation_endpoint(
    payload: CreateConversationRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[CreateConversationResponseData]:
    data = await create_conversation(
        session,
        current_user=current_user,
        payload=payload,
    )
    return ApiResponse(data=CreateConversationResponseData(**data))


@router.get(
    "",
    response_model=ApiResponse[ListConversationsResponseData],
    responses=COMMON_ERROR_RESPONSES,
)
async def list_conversations_endpoint(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[ListConversationsResponseData]:
    data = await list_conversations(session, current_user=current_user)
    return ApiResponse(data=data)


@router.get(
    "/{conversation_id}",
    response_model=ApiResponse[GetConversationResponseData],
    responses=COMMON_ERROR_RESPONSES,
)
async def get_conversation_endpoint(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[GetConversationResponseData]:
    data = await get_conversation(
        session,
        current_user=current_user,
        conversation_id=conversation_id,
    )
    return ApiResponse(data=GetConversationResponseData(**data))


@router.get(
    "/{conversation_id}/messages",
    response_model=ApiResponse[ListMessagesResponseData],
    responses=COMMON_ERROR_RESPONSES,
)
async def list_conversation_messages_endpoint(
    conversation_id: int,
    before_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[ListMessagesResponseData]:
    data = await list_messages(
        session,
        current_user=current_user,
        conversation_id=conversation_id,
        before_id=before_id,
        limit=limit,
    )
    return ApiResponse(data=ListMessagesResponseData(**data))


@router.patch(
    "/{conversation_id}",
    response_model=ApiResponse[UpdateConversationResponseData],
    responses=COMMON_ERROR_RESPONSES,
)
async def update_conversation_endpoint(
    conversation_id: int,
    payload: UpdateConversationRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[UpdateConversationResponseData]:
    data = await update_conversation(
        session,
        current_user=current_user,
        conversation_id=conversation_id,
        payload=payload,
    )
    return ApiResponse(data=UpdateConversationResponseData(**data))


@router.patch(
    "/{conversation_id}/settings",
    response_model=ApiResponse[ConversationSettingsResponseData],
    responses=COMMON_ERROR_RESPONSES,
)
async def update_conversation_settings_endpoint(
    conversation_id: int,
    payload: UpdateConversationSettingsRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[ConversationSettingsResponseData]:
    data = await update_conversation_settings(
        session,
        current_user=current_user,
        conversation_id=conversation_id,
        payload=payload,
    )
    return ApiResponse(data=ConversationSettingsResponseData(**data))


@router.post(
    "/{conversation_id}/clear-local",
    response_model=ApiResponse[ClearConversationResponseData],
    responses=COMMON_ERROR_RESPONSES,
)
async def clear_local_endpoint(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[ClearConversationResponseData]:
    data = await clear_local(
        session,
        current_user=current_user,
        conversation_id=conversation_id,
    )
    return ApiResponse(data=ClearConversationResponseData(**data))


@router.post(
    "/{conversation_id}/clear-global",
    response_model=ApiResponse[ClearConversationResponseData],
    responses=COMMON_ERROR_RESPONSES,
)
async def clear_global_endpoint(
    conversation_id: int,
    payload: ClearConversationRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[ClearConversationResponseData]:
    data = await clear_global(
        session,
        current_user=current_user,
        conversation_id=conversation_id,
        payload=payload,
    )
    return ApiResponse(data=ClearConversationResponseData(**data))
