from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.dependencies.auth import get_current_user
from app.dependencies.device import get_current_device
from app.models.device import Device
from app.models.user import User
from app.schemas.keys import RefillPreKeysRequest, RotateSignedPreKeyRequest
from app.services.key_service import (
    get_key_bundle_for_user,
    refill_prekeys,
    rotate_signed_prekey,
)

router = APIRouter()


@router.get("/bundle/{user_id}")
async def get_key_bundle(
    user_id: int,
    current_user: User = Depends(get_current_user),
    current_device: Device = Depends(get_current_device),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    data = await get_key_bundle_for_user(
        session,
        current_user=current_user,
        current_device=current_device,
        target_user_id=user_id,
    )
    return {
        "ok": True,
        "data": data,
        "meta": {},
    }


@router.post("/prekeys/refill")
async def refill_prekeys_endpoint(
    payload: RefillPreKeysRequest,
    current_user: User = Depends(get_current_user),
    current_device: Device = Depends(get_current_device),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _ = current_user
    data = await refill_prekeys(
        session,
        current_device=current_device,
        payload=payload,
    )
    return {
        "ok": True,
        "data": data,
        "meta": {},
    }


@router.post("/signed-prekey/rotate")
async def rotate_signed_prekey_endpoint(
    payload: RotateSignedPreKeyRequest,
    current_user: User = Depends(get_current_user),
    current_device: Device = Depends(get_current_device),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    _ = current_user
    data = await rotate_signed_prekey(
        session,
        current_device=current_device,
        payload=payload,
    )
    return {
        "ok": True,
        "data": data,
        "meta": {},
    }
