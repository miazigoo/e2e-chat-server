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
    ListDeviceAuthorizationRequestsResponseData,
    ListDevicesResponseData,
    ResolveDeviceAuthorizationRequestResponseData,
    RevokeCurrentDeviceResponseData,
    RevokeDeviceResponseData,
    UpdateFcmTokenRequest,
    UpdateFcmTokenResponseData,
)
from app.services.device_service import (
    heartbeat,
    list_device_authorization_requests,
    list_devices,
    resolve_device_authorization_request,
    revoke_current_device,
    revoke_device,
    update_fcm_token,
)

router = APIRouter()


@router.get(
    "",
    response_model=ApiResponse[ListDevicesResponseData],
)
async def list_devices_endpoint(
    current_user: User = Depends(get_current_user),
    current_device: Device = Depends(get_current_device),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[ListDevicesResponseData]:
    data = await list_devices(
        session,
        current_user=current_user,
        current_device=current_device,
    )
    return ApiResponse(data=data)


@router.get(
    "/authorization-requests",
    response_model=ApiResponse[ListDeviceAuthorizationRequestsResponseData],
)
async def list_device_authorization_requests_endpoint(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[ListDeviceAuthorizationRequestsResponseData]:
    data = await list_device_authorization_requests(
        session,
        current_user=current_user,
    )
    return ApiResponse(data=data)


@router.post(
    "/authorization-requests/{request_id}/approve",
    response_model=ApiResponse[ResolveDeviceAuthorizationRequestResponseData],
)
async def approve_device_authorization_request_endpoint(
    request_id: str,
    current_user: User = Depends(get_current_user),
    current_device: Device = Depends(get_current_device),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[ResolveDeviceAuthorizationRequestResponseData]:
    data = await resolve_device_authorization_request(
        session,
        current_user=current_user,
        current_device=current_device,
        request_id=request_id,
        approved=True,
    )
    return ApiResponse(data=data)


@router.post(
    "/authorization-requests/{request_id}/deny",
    response_model=ApiResponse[ResolveDeviceAuthorizationRequestResponseData],
)
async def deny_device_authorization_request_endpoint(
    request_id: str,
    current_user: User = Depends(get_current_user),
    current_device: Device = Depends(get_current_device),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[ResolveDeviceAuthorizationRequestResponseData]:
    data = await resolve_device_authorization_request(
        session,
        current_user=current_user,
        current_device=current_device,
        request_id=request_id,
        approved=False,
    )
    return ApiResponse(data=data)


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
    "/{device_id}",
    response_model=ApiResponse[RevokeDeviceResponseData],
)
async def revoke_device_endpoint(
    device_id: int,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[RevokeDeviceResponseData]:
    data = await revoke_device(
        session,
        current_user=current_user,
        device_id=device_id,
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
