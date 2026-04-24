from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.device import Device
from app.models.device_prekey import DevicePreKey


def _now() -> datetime:
    return datetime.now(timezone.utc)


class KeysRepository:
    async def claim_one_time_prekey(
        self,
        session: AsyncSession,
        *,
        device_id: int,
    ) -> DevicePreKey | None:
        result = await session.execute(
            select(DevicePreKey)
            .where(
                DevicePreKey.device_id == device_id,
                DevicePreKey.is_used.is_(False),
            )
            .order_by(DevicePreKey.id.asc())
            .with_for_update(skip_locked=True)
        )
        prekey = result.scalars().first()

        if prekey is None:
            return None

        prekey.is_used = True
        prekey.used_at = _now()
        await session.flush()
        return prekey

    async def count_available_prekeys(
        self,
        session: AsyncSession,
        *,
        device_id: int,
    ) -> int:
        result = await session.execute(
            select(func.count(DevicePreKey.id)).where(
                DevicePreKey.device_id == device_id,
                DevicePreKey.is_used.is_(False),
            )
        )
        return int(result.scalar_one() or 0)

    async def add_prekeys(
        self,
        session: AsyncSession,
        *,
        device_id: int,
        prekeys: list[dict[str, str | int]],
    ) -> int:
        result = await session.execute(
            select(DevicePreKey.prekey_id).where(DevicePreKey.device_id == device_id)
        )
        existing_ids = set(result.scalars().all())

        added = 0
        for prekey in prekeys:
            prekey_id = int(prekey["prekey_id"])
            if prekey_id in existing_ids:
                continue

            session.add(
                DevicePreKey(
                    device_id=device_id,
                    prekey_id=prekey_id,
                    public_prekey=str(prekey["public_prekey"]),
                )
            )
            existing_ids.add(prekey_id)
            added += 1

        await session.flush()
        return added

    async def rotate_signed_prekey(
        self,
        session: AsyncSession,
        *,
        device: Device,
        signed_prekey_id: int,
        signed_prekey: str,
        signed_prekey_signature: str,
    ) -> Device:
        device.signed_prekey_id = signed_prekey_id
        device.signed_prekey = signed_prekey
        device.signed_prekey_signature = signed_prekey_signature
        await session.flush()
        return device
