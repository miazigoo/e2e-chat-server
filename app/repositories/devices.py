from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.device import Device
from app.models.device_prekey import DevicePreKey


class DevicesRepository:
    async def get_by_user_and_uuid(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        device_uuid: str,
    ) -> Device | None:
        result = await session.execute(
            select(Device).where(
                Device.user_id == user_id,
                Device.device_uuid == device_uuid,
            )
        )
        return result.scalar_one_or_none()

    async def get_active_by_user_id(
        self,
        session: AsyncSession,
        *,
        user_id: int,
    ) -> Device | None:
        result = await session.execute(
            select(Device).where(
                Device.user_id == user_id,
                Device.is_active.is_(True),
                Device.revoked_at.is_(None),
            )
        )
        return result.scalar_one_or_none()

    async def deactivate_other_devices(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        keep_device_id: int | None,
    ) -> None:
        result = await session.execute(
            select(Device).where(
                Device.user_id == user_id,
                Device.is_active.is_(True),
                Device.revoked_at.is_(None),
            )
        )
        devices = list(result.scalars().all())

        for device in devices:
            if keep_device_id is not None and device.id == keep_device_id:
                continue
            device.is_active = False

        await session.flush()

    async def create_or_update_device(
        self,
        session: AsyncSession,
        *,
        existing_device: Device | None,
        user_id: int,
        device_uuid: str,
        device_name: str,
        platform: str,
        app_version: str,
        fcm_token: str | None,
        public_identity_key: str,
        public_signing_key: str,
        signed_prekey: str,
        signed_prekey_signature: str,
    ) -> Device:
        if existing_device is not None:
            existing_device.device_name = device_name
            existing_device.platform = platform
            existing_device.app_version = app_version
            existing_device.fcm_token = fcm_token
            existing_device.public_identity_key = public_identity_key
            existing_device.public_signing_key = public_signing_key
            existing_device.signed_prekey = signed_prekey
            existing_device.signed_prekey_signature = signed_prekey_signature
            existing_device.is_active = True
            existing_device.revoked_at = None
            await session.flush()
            return existing_device

        device = Device(
            user_id=user_id,
            device_uuid=device_uuid,
            device_name=device_name,
            platform=platform,
            app_version=app_version,
            fcm_token=fcm_token,
            public_identity_key=public_identity_key,
            public_signing_key=public_signing_key,
            signed_prekey=signed_prekey,
            signed_prekey_signature=signed_prekey_signature,
            is_active=True,
        )
        session.add(device)
        await session.flush()
        return device

    async def replace_prekeys(
        self,
        session: AsyncSession,
        *,
        device_id: int,
        prekeys: list[dict[str, str | int]],
    ) -> int:
        await session.execute(
            delete(DevicePreKey).where(DevicePreKey.device_id == device_id)
        )

        for prekey in prekeys:
            session.add(
                DevicePreKey(
                    device_id=device_id,
                    prekey_id=int(prekey["prekey_id"]),
                    public_prekey=str(prekey["public_prekey"]),
                )
            )

        await session.flush()
        return len(prekeys)

    async def touch_last_seen(
        self,
        session: AsyncSession,
        *,
        device: Device,
        seen_at: datetime,
    ) -> Device:
        device.last_seen_at = seen_at
        await session.flush()
        return device

    async def update_fcm_token(
        self,
        session: AsyncSession,
        *,
        device: Device,
        fcm_token: str | None,
    ) -> Device:
        device.fcm_token = fcm_token
        await session.flush()
        return device

    async def revoke_device(
        self,
        session: AsyncSession,
        *,
        device: Device,
        revoked_at: datetime,
    ) -> Device:
        device.is_active = False
        if device.revoked_at is None:
            device.revoked_at = revoked_at
        await session.flush()
        return device
