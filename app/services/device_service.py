from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.repositories.devices import DevicesRepository
from app.schemas.devices import BootstrapDeviceRequest

devices_repo = DevicesRepository()


async def bootstrap_device(
    session: AsyncSession,
    *,
    current_user: User,
    payload: BootstrapDeviceRequest,
) -> dict:
    if payload.platform.lower() != "android":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "UNSUPPORTED_PLATFORM",
                "message": "Only android platform is supported",
            },
        )

    existing_device = await devices_repo.get_by_user_and_uuid(
        session,
        user_id=current_user.id,
        device_uuid=payload.device_uuid,
    )

    # Если это новое устройство — сначала деактивируем старое активное,
    # чтобы не упереться в unique partial index.
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

    # Если обновляем существующее устройство — оставляем только его активным.
    if existing_device is not None:
        await devices_repo.deactivate_other_devices(
            session,
            user_id=current_user.id,
            keep_device_id=device.id,
        )

    # Дедупликация prekeys на входе
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

    await session.commit()

    return {
        "device_id": device.id,
        "device_uuid": device.device_uuid,
        "is_active": device.is_active,
        "prekeys_count": prekeys_count,
    }
