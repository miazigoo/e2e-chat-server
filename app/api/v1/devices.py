from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.rate_limit import rate_limit_dependency
from app.dependencies.auth import get_current_user
from app.dependencies.device import get_current_device
from app.models.device import Device
from app.models.user import User
from app.schemas.common import ApiResponse
from app.schemas.devices import (
    DeviceHeartbeatResponseData,
    RevokeCurrentDeviceResponseData,
    UpdateFcmTokenRequest,
    UpdateFcmTokenResponseData,
)
from app.services.device_service import (
    heartbeat,
    revoke_current_device,
    update_fcm_token,
)

router = APIRouter()


@router.post(
    "/heartbeat",
    response_model=ApiResponse[DeviceHeartbeatResponseData],
    dependencies=[
        Depends(
            rate_limit_dependency(
                prefix="devices:heartbeat",
                limit=180,
                window_seconds=60,
            )
        )
    ],
)
async def heartbeat_endpoint(
    current_user: User = Depends(get_current_user),
    current_device: Device = Depends(get_current_device),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[DeviceHeartbeatResponseData]:
    data = await heartbeat(
        session,
        current_user=current_user,
        current_device=current_device,
    )
    return ApiResponse(data=data)


@router.post(
    "/fcm-token",
    response_model=ApiResponse[UpdateFcmTokenResponseData],
    dependencies=[
        Depends(
            rate_limit_dependency(
                prefix="devices:fcm-token",
                limit=30,
                window_seconds=60,
            )
        )
    ],
)
async def update_fcm_token_endpoint(
    payload: UpdateFcmTokenRequest,
    current_user: User = Depends(get_current_user),
    current_device: Device = Depends(get_current_device),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[UpdateFcmTokenResponseData]:
    data = await update_fcm_token(
        session,
        current_user=current_user,
        current_device=current_device,
        payload=payload,
    )
    return ApiResponse(data=data)


@router.delete(
    "/current",
    response_model=ApiResponse[RevokeCurrentDeviceResponseData],
    dependencies=[
        Depends(
            rate_limit_dependency(
                prefix="devices:revoke-current",
                limit=10,
                window_seconds=60,
            )
        )
    ],
)
async def revoke_current_device_endpoint(
    current_user: User = Depends(get_current_user),
    current_device: Device = Depends(get_current_device),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[RevokeCurrentDeviceResponseData]:
    data = await revoke_current_device(
        session,
        current_user=current_user,
        current_device=current_device,
    )
    return ApiResponse(data=data)
