from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.device import get_current_device
from app.models.device import Device
from app.models.user import User
from app.schemas.common import ApiResponse
from app.schemas.messages import (
    DeleteMessageReactionResponseData,
    DeleteMessagesRequest,
    DeleteMessagesResponseData,
    ForwardMessagesRequest,
    ForwardMessagesResponseData,
    ListMessagesResponseData,
    MarkDeliveredRequest,
    MarkDeliveredResponseData,
    MarkReadRequest,
    MarkReadResponseData,
    PinMessageResponseData,
    SearchMessagesResponseData,
    SendMessageRequest,
    SendMessageResponseData,
    SetMessageReactionRequest,
    SetMessageReactionResponseData,
    SharedMessagesResponseData,
)
from app.services.message_service import (
    delete_global,
    delete_local,
    delete_message_reaction,
    forward_messages,
    list_messages,
    list_shared_messages,
    mark_delivered,
    mark_read,
    pin_message,
    search_messages,
    send_message,
    set_message_reaction,
    unpin_message,
)

router = APIRouter()


@router.get(
    "/conversations/{conversation_id}",
    response_model=ApiResponse[ListMessagesResponseData],
    summary="List conversation messages",
    description=(
        "Return message history for a conversation visible to the current user."
    ),
)
async def list_messages_endpoint(
    conversation_id: int,
    before_id: int | None = Query(default=None, ge=1),
    after_id: int | None = Query(default=None, ge=1),
    anchor_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    current_device: Device = Depends(get_current_device),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[ListMessagesResponseData]:
    """List messages for one conversation with cursor or anchor pagination."""
    result = await list_messages(
        session,
        current_user=current_user,
        current_device=current_device,
        conversation_id=conversation_id,
        before_id=before_id,
        after_id=after_id,
        anchor_id=anchor_id,
        limit=limit,
    )
    return ApiResponse(data=ListMessagesResponseData(**result))


@router.post(
    "/send",
    response_model=ApiResponse[SendMessageResponseData],
    summary="Send message",
    description="Create a new message in a conversation from the current device.",
)
async def send_message_endpoint(
    payload: SendMessageRequest,
    current_user: User = Depends(get_current_user),
    current_device: Device = Depends(get_current_device),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[SendMessageResponseData]:
    """Send a new encrypted message to the peer in the target conversation."""
    result = await send_message(
        session,
        current_user=current_user,
        current_device=current_device,
        payload=payload,
    )
    return ApiResponse(data=SendMessageResponseData(**result))


@router.post(
    "/forward",
    response_model=ApiResponse[ForwardMessagesResponseData],
    summary="Forward messages",
    description="Forward one or more existing messages into another conversation.",
)
async def forward_messages_endpoint(
    payload: ForwardMessagesRequest,
    current_user: User = Depends(get_current_user),
    current_device: Device = Depends(get_current_device),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[ForwardMessagesResponseData]:
    """Clone existing messages and deliver them as forwarded messages."""
    result = await forward_messages(
        session,
        current_user=current_user,
        current_device=current_device,
        payload=payload,
    )
    return ApiResponse(data=ForwardMessagesResponseData(**result))


@router.post(
    "/{message_id}/delivered",
    response_model=ApiResponse[MarkDeliveredResponseData],
    summary="Mark delivered",
    description="Acknowledge that the current device received the message.",
)
async def mark_delivered_endpoint(
    message_id: int,
    payload: MarkDeliveredRequest,
    current_user: User = Depends(get_current_user),
    current_device: Device = Depends(get_current_device),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[MarkDeliveredResponseData]:
    """Mark a message as delivered for the current recipient device."""
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
    summary="Mark read",
    description="Acknowledge that the current device has read the message.",
)
async def mark_read_endpoint(
    message_id: int,
    payload: MarkReadRequest,
    current_user: User = Depends(get_current_user),
    current_device: Device = Depends(get_current_device),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[MarkReadResponseData]:
    """Mark a message as read for the current recipient device."""
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
    summary="Delete messages locally",
    description="Hide selected messages only for the current user.",
)
async def delete_local_endpoint(
    payload: DeleteMessagesRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[DeleteMessagesResponseData]:
    """Delete selected messages locally for the current user."""
    result = await delete_local(
        session,
        current_user=current_user,
        payload=payload,
    )
    return ApiResponse(data=DeleteMessagesResponseData(**result))


@router.post(
    "/delete-global",
    response_model=ApiResponse[DeleteMessagesResponseData],
    summary="Delete messages globally",
    description="Delete selected messages globally for both conversation participants.",
)
async def delete_global_endpoint(
    payload: DeleteMessagesRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[DeleteMessagesResponseData]:
    """Delete selected messages globally for the whole conversation."""
    result = await delete_global(
        session,
        current_user=current_user,
        payload=payload,
    )
    return ApiResponse(data=DeleteMessagesResponseData(**result))


@router.post(
    "/{message_id}/reaction",
    response_model=ApiResponse[SetMessageReactionResponseData],
    summary="Set reaction",
    description="Set or replace the current user's reaction on a message.",
)
async def set_message_reaction_endpoint(
    message_id: int,
    payload: SetMessageReactionRequest,
    current_user: User = Depends(get_current_user),
    current_device: Device = Depends(get_current_device),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[SetMessageReactionResponseData]:
    """Set or replace a reaction for the selected message."""
    result = await set_message_reaction(
        session,
        current_user=current_user,
        current_device=current_device,
        message_id=message_id,
        payload=payload,
    )
    return ApiResponse(data=SetMessageReactionResponseData(**result))


@router.delete(
    "/{message_id}/reaction",
    response_model=ApiResponse[DeleteMessageReactionResponseData],
    summary="Delete reaction",
    description="Remove the current user's reaction from a message.",
)
async def delete_message_reaction_endpoint(
    message_id: int,
    current_user: User = Depends(get_current_user),
    current_device: Device = Depends(get_current_device),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[DeleteMessageReactionResponseData]:
    """Remove the current user's reaction from the selected message."""
    result = await delete_message_reaction(
        session,
        current_user=current_user,
        current_device=current_device,
        message_id=message_id,
    )
    return ApiResponse(data=DeleteMessageReactionResponseData(**result))


@router.get(
    "/conversations/{conversation_id}/search",
    response_model=ApiResponse[SearchMessagesResponseData],
    summary="Search in conversation",
    description=(
        "Search messages inside one conversation using server-visible fields "
        "such as ciphertext and attachment metadata."
    ),
)
async def search_messages_endpoint(
    conversation_id: int,
    q: str = Query(min_length=1, max_length=255),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    current_device: Device = Depends(get_current_device),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[SearchMessagesResponseData]:
    """Search messages inside a single conversation."""
    data = await search_messages(
        session,
        current_user=current_user,
        current_device=current_device,
        conversation_id=conversation_id,
        query=q,
        limit=limit,
    )
    return ApiResponse(data=data)


@router.get(
    "/conversations/{conversation_id}/shared",
    response_model=ApiResponse[SharedMessagesResponseData],
    summary="List shared media",
    description=(
        "Return items for the selected shared-content tab: media, links or files, "
        "together with counts for all tabs."
    ),
)
async def list_shared_messages_endpoint(
    conversation_id: int,
    tab: str = Query(..., pattern="^(media|links|files)$"),
    before_message_id: int | None = Query(default=None, ge=1),
    tag_id: int | None = Query(default=None, ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    current_user: User = Depends(get_current_user),
    current_device: Device = Depends(get_current_device),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[SharedMessagesResponseData]:
    """List conversation items for Telegram-like media, links and files tabs."""
    data = await list_shared_messages(
        session,
        current_user=current_user,
        current_device=current_device,
        conversation_id=conversation_id,
        tab=tab,
        before_message_id=before_message_id,
        tag_id=tag_id,
        limit=limit,
    )
    return ApiResponse(data=data)


@router.post(
    "/conversations/{conversation_id}/pin/{message_id}",
    response_model=ApiResponse[PinMessageResponseData],
    summary="Pin message",
    description="Pin a message at conversation level for both participants.",
)
async def pin_message_endpoint(
    conversation_id: int,
    message_id: int,
    current_user: User = Depends(get_current_user),
    current_device: Device = Depends(get_current_device),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[PinMessageResponseData]:
    """Pin one message for the whole conversation."""
    data = await pin_message(
        session,
        current_user=current_user,
        current_device=current_device,
        conversation_id=conversation_id,
        message_id=message_id,
    )
    return ApiResponse(data=data)


@router.delete(
    "/conversations/{conversation_id}/pin",
    response_model=ApiResponse[PinMessageResponseData],
    summary="Unpin message",
    description="Remove the currently pinned message from the conversation.",
)
async def unpin_message_endpoint(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    current_device: Device = Depends(get_current_device),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[PinMessageResponseData]:
    """Remove the current pinned message from the conversation."""
    data = await unpin_message(
        session,
        current_user=current_user,
        current_device=current_device,
        conversation_id=conversation_id,
    )
    return ApiResponse(data=data)
