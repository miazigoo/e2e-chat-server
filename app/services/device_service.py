from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError
from app.models.device import Device
from app.models.user import User
from app.repositories.auth_sessions import AuthSessionsRepository
from app.repositories.device_authorization_requests import (
    DeviceAuthorizationRequestsRepository,
)
from app.repositories.devices import DevicesRepository
from app.schemas.devices import (
    BootstrapDeviceRequest,
    DeviceAuthorizationRequestSchema,
    DeviceHeartbeatResponseData,
    DeviceListItemSchema,
    ListDeviceAuthorizationRequestsResponseData,
    ListDevicesResponseData,
    ResolveDeviceAuthorizationRequestResponseData,
    RevokeCurrentDeviceResponseData,
    RevokeDeviceResponseData,
    UpdateFcmTokenRequest,
    UpdateFcmTokenResponseData,
)

devices_repo = DevicesRepository()
auth_sessions_repo = AuthSessionsRepository()
device_auth_requests_repo = DeviceAuthorizationRequestsRepository()


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def bootstrap_device(
    session: AsyncSession,
    *,
    current_user: User,
    payload: BootstrapDeviceRequest,
) -> dict:
    if payload.platform.lower() not in {"android", "desktop"}:
        raise BadRequestError(
            code="UNSUPPORTED_PLATFORM",
            message="Only android and desktop platforms are supported",
        )

    existing_device = await devices_repo.get_by_user_and_uuid(
        session,
        user_id=current_user.id,
        device_uuid=payload.device_uuid,
    )

    device = await devices_repo.create_or_update_device(
        session,
        existing_device=existing_device,
        user_id=current_user.id,
        device_uuid=payload.device_uuid,
        device_name=payload.device_name,
        platform=payload.platform,
        app_version=payload.app_version,
        fcm_token=payload.fcm_token,
        registration_id=payload.registration_id,
        public_identity_key=payload.public_identity_key,
        public_signing_key=payload.public_signing_key,
        signed_prekey_id=payload.signed_prekey_id,
        signed_prekey=payload.signed_prekey,
        signed_prekey_signature=payload.signed_prekey_signature,
    )

    seen_ids: set[int] = set()
    normalized_prekeys: list[dict[str, str | int]] = []
    for item in payload.one_time_prekeys:
        if item.prekey_id in seen_ids:
            continue
        seen_ids.add(item.prekey_id)
        normalized_prekeys.append(
            {
                "prekey_id": item.prekey_id,
                "public_prekey": item.public_prekey,
            }
        )

    prekeys_count = await devices_repo.replace_prekeys(
        session,
        device_id=device.id,
        prekeys=normalized_prekeys,
    )

    device.prekeys_count = prekeys_count
    device.last_seen_at = _now()

    await session.commit()

    return {
        "device_id": device.id,
        "device_uuid": device.device_uuid,
        "is_active": device.is_active,
        "prekeys_count": prekeys_count,
        "last_seen_at": (
            device.last_seen_at.isoformat() if device.last_seen_at else None
        ),
    }


async def list_devices(
    session: AsyncSession,
    *,
    current_user: User,
    current_device: Device,
) -> ListDevicesResponseData:
    devices = await devices_repo.list_active_by_user_id(
        session,
        user_id=current_user.id,
    )
    return ListDevicesResponseData(
        items=[
            DeviceListItemSchema(
                device_id=device.id,
                device_uuid=device.device_uuid,
                device_name=device.device_name,
                platform=device.platform,
                app_version=device.app_version,
                is_current=device.id == current_device.id,
                fcm_token_present=device.fcm_token is not None,
                registered_at=device.registered_at,
                last_seen_at=device.last_seen_at,
            )
            for device in devices
        ]
    )


async def revoke_device(
    session: AsyncSession,
    *,
    current_user: User,
    device_id: int,
) -> RevokeDeviceResponseData:
    device = await devices_repo.get_active_by_id_for_user(
        session,
        user_id=current_user.id,
        device_id=device_id,
    )
    if device is None:
        raise BadRequestError(
            code="DEVICE_NOT_FOUND",
            message="Device not found or already revoked",
        )

    revoked_at = _now()
    await devices_repo.revoke_device(
        session,
        device=device,
        revoked_at=revoked_at,
    )
    revoked_sessions = await auth_sessions_repo.revoke_all_for_device(
        session,
        device_id=device.id,
        revoked_at=revoked_at,
    )
    await session.commit()

    return RevokeDeviceResponseData(
        device_id=device.id,
        revoked=True,
        revoked_sessions=revoked_sessions,
        revoked_at=revoked_at,
    )


async def list_device_authorization_requests(
    session: AsyncSession,
    *,
    current_user: User,
) -> ListDeviceAuthorizationRequestsResponseData:
    now_dt = _now()
    requests = await device_auth_requests_repo.list_pending_for_user(
        session,
        user_id=current_user.id,
        now_dt=now_dt,
    )
    return ListDeviceAuthorizationRequestsResponseData(
        items=[
            DeviceAuthorizationRequestSchema(
                request_id=request.request_id,
                device_uuid=request.device_uuid,
                device_name=request.device_name,
                platform=request.platform,
                app_version=request.app_version,
                ip_address=(
                    str(request.ip_address) if request.ip_address is not None else None
                ),
                user_agent=request.user_agent,
                requested_at=request.requested_at,
                expires_at=request.expires_at,
            )
            for request in requests
        ]
    )


async def resolve_device_authorization_request(
    session: AsyncSession,
    *,
    current_user: User,
    current_device: Device,
    request_id: str,
    approved: bool,
) -> ResolveDeviceAuthorizationRequestResponseData:
    request = await device_auth_requests_repo.get_by_request_id(
        session,
        request_id=request_id,
    )
    if request is None or request.user_id != current_user.id:
        raise BadRequestError(
            code="DEVICE_APPROVAL_REQUEST_NOT_FOUND",
            message="Device approval request not found",
        )

    if request.status != "pending" or request.expires_at <= _now():
        raise BadRequestError(
            code="DEVICE_APPROVAL_REQUEST_NOT_PENDING",
            message="Device approval request is not pending",
        )

    status = "approved" if approved else "denied"
    await device_auth_requests_repo.resolve(
        session,
        request=request,
        status=status,
        resolved_at=_now(),
        resolved_by_device_id=current_device.id,
    )
    await session.commit()

    return ResolveDeviceAuthorizationRequestResponseData(
        request_id=request.request_id,
        status=status,
        bootstrap_available=approved,
    )


async def heartbeat(
    session: AsyncSession,
    *,
    current_user: User,
    current_device: Device,
) -> DeviceHeartbeatResponseData:
    _ = current_user

    seen_at = _now()
    await devices_repo.touch_last_seen(
        session,
        device=current_device,
        seen_at=seen_at,
    )
    await session.commit()

    return DeviceHeartbeatResponseData(
        device_id=current_device.id,
        device_uuid=current_device.device_uuid,
        status="online",
        last_seen_at=seen_at,
    )


async def update_fcm_token(
    session: AsyncSession,
    *,
    current_user: User,
    current_device: Device,
    payload: UpdateFcmTokenRequest,
) -> UpdateFcmTokenResponseData:
    _ = current_user

    await devices_repo.update_fcm_token(
        session,
        device=current_device,
        fcm_token=payload.fcm_token,
    )
    await devices_repo.touch_last_seen(
        session,
        device=current_device,
        seen_at=_now(),
    )
    await session.commit()

    return UpdateFcmTokenResponseData(
        device_id=current_device.id,
        updated=True,
        fcm_token_present=payload.fcm_token is not None,
        last_seen_at=current_device.last_seen_at,
    )


async def revoke_current_device(
    session: AsyncSession,
    *,
    current_user: User,
    current_device: Device,
) -> RevokeCurrentDeviceResponseData:
    _ = current_user

    revoked_at = _now()

    await devices_repo.revoke_device(
        session,
        device=current_device,
        revoked_at=revoked_at,
    )
    revoked_sessions = await auth_sessions_repo.revoke_all_for_device(
        session,
        device_id=current_device.id,
        revoked_at=revoked_at,
    )

    await session.commit()

    return RevokeCurrentDeviceResponseData(
        device_id=current_device.id,
        revoked=True,
        revoked_sessions=revoked_sessions,
        revoked_at=revoked_at,
    )
