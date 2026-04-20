from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.common import ApiResponse
from app.schemas.conversations import (
    ClearConversationRequest,
    CreateConversationRequest,
    ListConversationsResponseData,
    UpdateConversationRequest,
)
from app.services.conversation_service import (
    clear_global,
    clear_local,
    create_conversation,
    get_conversation,
    list_conversations,
    update_conversation,
)
from app.services.message_service import list_messages

router = APIRouter()


@router.post("")
async def create_conversation_endpoint(
    payload: CreateConversationRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    data = await create_conversation(
        session,
        current_user=current_user,
        payload=payload,
    )
    return {"ok": True, "data": data, "meta": {}}


@router.get(
    "",
    response_model=ApiResponse[ListConversationsResponseData],
)
async def list_conversations_endpoint(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[ListConversationsResponseData]:
    data = await list_conversations(session, current_user=current_user)
    return ApiResponse(data=data)


@router.get("/{conversation_id}")
async def get_conversation_endpoint(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    data = await get_conversation(
        session,
        current_user=current_user,
        conversation_id=conversation_id,
    )
    return {"ok": True, "data": data, "meta": {}}


@router.get("/{conversation_id}/messages")
async def list_conversation_messages_endpoint(
    conversation_id: int,
    before_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    data = await list_messages(
        session,
        current_user=current_user,
        conversation_id=conversation_id,
        before_id=before_id,
        limit=limit,
    )
    return {"ok": True, "data": data, "meta": {}}


@router.patch("/{conversation_id}")
async def update_conversation_endpoint(
    conversation_id: int,
    payload: UpdateConversationRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    data = await update_conversation(
        session,
        current_user=current_user,
        conversation_id=conversation_id,
        payload=payload,
    )
    return {"ok": True, "data": data, "meta": {}}


@router.post("/{conversation_id}/clear-local")
async def clear_local_endpoint(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    data = await clear_local(
        session,
        current_user=current_user,
        conversation_id=conversation_id,
    )
    return {"ok": True, "data": data, "meta": {}}


@router.post("/{conversation_id}/clear-global")
async def clear_global_endpoint(
    conversation_id: int,
    payload: ClearConversationRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    data = await clear_global(
        session,
        current_user=current_user,
        conversation_id=conversation_id,
        payload=payload,
    )
    return {"ok": True, "data": data, "meta": {}}
