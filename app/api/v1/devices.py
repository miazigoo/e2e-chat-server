from typing import Any

from fastapi import APIRouter

router = APIRouter()


@router.post("/register")
async def register_device() -> dict[str, Any]:
    return {
        "ok": True,
        "data": {
            "device_id": 1,
            "is_active_device": True,
        },
        "meta": {},
    }


@router.post("/heartbeat")
async def heartbeat() -> dict[str, Any]:
    return {
        "ok": True,
        "data": {
            "status": "heartbeat_received",
        },
        "meta": {},
    }


@router.post("/fcm-token")
async def update_fcm_token() -> dict[str, Any]:
    return {
        "ok": True,
        "data": {
            "updated": True,
        },
        "meta": {},
    }


@router.delete("/current")
async def revoke_current_device() -> dict[str, Any]:
    return {
        "ok": True,
        "data": {
            "revoked": True,
        },
        "meta": {},
    }
