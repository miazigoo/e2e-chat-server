from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.device import get_current_device
from app.models.device import Device
from app.models.user import User
from app.schemas.messages import (
    DeleteMessagesRequest,
    MarkReadRequest,
    SendMessageRequest,
)
from app.services.message_service import (
    delete_global,
    delete_local,
    mark_read,
    send_message,
)

router = APIRouter()


@router.post("/send")
async def send_message_endpoint(
    payload: SendMessageRequest,
    current_user: User = Depends(get_current_user),
    current_device: Device = Depends(get_current_device),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    data = await send_message(
        session,
        current_user=current_user,
        current_device=current_device,
        payload=payload,
    )
    return {"ok": True, "data": data, "meta": {}}


@router.post("/{message_id}/read")
async def mark_read_endpoint(
    message_id: int,
    payload: MarkReadRequest,
    current_user: User = Depends(get_current_user),
    current_device: Device = Depends(get_current_device),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    data = await mark_read(
        session,
        current_user=current_user,
        current_device=current_device,
        message_id=message_id,
        payload=payload,
    )
    return {"ok": True, "data": data, "meta": {}}


@router.post("/delete-local")
async def delete_local_endpoint(
    payload: DeleteMessagesRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    data = await delete_local(
        session,
        current_user=current_user,
        payload=payload,
    )
    return {"ok": True, "data": data, "meta": {}}


@router.post("/delete-global")
async def delete_global_endpoint(
    payload: DeleteMessagesRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    data = await delete_global(
        session,
        current_user=current_user,
        payload=payload,
    )
    return {"ok": True, "data": data, "meta": {}}
