from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError
from app.models.device import Device
from app.models.user import User
from app.repositories.auth_sessions import AuthSessionsRepository
from app.repositories.devices import DevicesRepository
from app.schemas.devices import (
    BootstrapDeviceRequest,
    DeviceHeartbeatResponseData,
    RevokeCurrentDeviceResponseData,
    UpdateFcmTokenRequest,
    UpdateFcmTokenResponseData,
)

devices_repo = DevicesRepository()
auth_sessions_repo = AuthSessionsRepository()


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def bootstrap_device(
    session: AsyncSession,
    *,
    current_user: User,
    payload: BootstrapDeviceRequest,
) -> dict:
    if payload.platform.lower() != "android":
        raise BadRequestError(
            code="UNSUPPORTED_PLATFORM",
            message="Only android platform is supported",
        )

    existing_device = await devices_repo.get_by_user_and_uuid(
        session,
        user_id=current_user.id,
        device_uuid=payload.device_uuid,
    )

    if existing_device is None:
        await devices_repo.deactivate_other_devices(
            session,
            user_id=current_user.id,
            keep_device_id=None,
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
        public_identity_key=payload.public_identity_key,
        public_signing_key=payload.public_signing_key,
        signed_prekey=payload.signed_prekey,
        signed_prekey_signature=payload.signed_prekey_signature,
    )

    if existing_device is not None:
        await devices_repo.deactivate_other_devices(
            session,
            user_id=current_user.id,
            keep_device_id=device.id,
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
