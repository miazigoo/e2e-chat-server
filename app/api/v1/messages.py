from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.device import get_current_device
from app.models.device import Device
from app.models.user import User
from app.schemas.common import ApiResponse
from app.schemas.messages import (
    DeleteMessagesRequest,
    DeleteMessagesResponseData,
    ListMessagesResponseData,
    MarkDeliveredRequest,
    MarkDeliveredResponseData,
    MarkReadRequest,
    MarkReadResponseData,
    SendMessageRequest,
    SendMessageResponseData,
)
from app.services.message_service import (
    delete_global,
    delete_local,
    list_messages,
    mark_delivered,
    mark_read,
    send_message,
)

router = APIRouter()


@router.get(
    "/conversations/{conversation_id}",
    response_model=ApiResponse[ListMessagesResponseData],
)
async def list_messages_endpoint(
    conversation_id: int,
    before_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[ListMessagesResponseData]:
    result = await list_messages(
        session,
        current_user=current_user,
        conversation_id=conversation_id,
        before_id=before_id,
        limit=limit,
    )
    return ApiResponse(data=ListMessagesResponseData(**result))


@router.post(
    "/send",
    response_model=ApiResponse[SendMessageResponseData],
)
async def send_message_endpoint(
    payload: SendMessageRequest,
    current_user: User = Depends(get_current_user),
    current_device: Device = Depends(get_current_device),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[SendMessageResponseData]:
    result = await send_message(
        session,
        current_user=current_user,
        current_device=current_device,
        payload=payload,
    )
    return ApiResponse(data=SendMessageResponseData(**result))


@router.post(
    "/{message_id}/delivered",
    response_model=ApiResponse[MarkDeliveredResponseData],
)
async def mark_delivered_endpoint(
    message_id: int,
    payload: MarkDeliveredRequest,
    current_user: User = Depends(get_current_user),
    current_device: Device = Depends(get_current_device),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[MarkDeliveredResponseData]:
    result = await mark_delivered(
        session,
        current_user=current_user,
        current_device=current_device,
        message_id=message_id,
        payload=payload,
    )
    return ApiResponse(data=MarkDeliveredResponseData(**result))


@router.post(
    "/{message_id}/read",
    response_model=ApiResponse[MarkReadResponseData],
)
async def mark_read_endpoint(
    message_id: int,
    payload: MarkReadRequest,
    current_user: User = Depends(get_current_user),
    current_device: Device = Depends(get_current_device),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[MarkReadResponseData]:
    result = await mark_read(
        session,
        current_user=current_user,
        current_device=current_device,
        message_id=message_id,
        payload=payload,
    )
    return ApiResponse(data=MarkReadResponseData(**result))


@router.post(
    "/delete-local",
    response_model=ApiResponse[DeleteMessagesResponseData],
)
async def delete_local_endpoint(
    payload: DeleteMessagesRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[DeleteMessagesResponseData]:
    result = await delete_local(
        session,
        current_user=current_user,
        payload=payload,
    )
    return ApiResponse(data=DeleteMessagesResponseData(**result))


@router.post(
    "/delete-global",
    response_model=ApiResponse[DeleteMessagesResponseData],
)
async def delete_global_endpoint(
    payload: DeleteMessagesRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[DeleteMessagesResponseData]:
    result = await delete_global(
        session,
        current_user=current_user,
        payload=payload,
    )
    return ApiResponse(data=DeleteMessagesResponseData(**result))
