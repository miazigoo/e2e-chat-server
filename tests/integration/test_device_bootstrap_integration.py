from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.device import Device
from app.schemas.devices import BootstrapDeviceRequest
from app.services.device_service import bootstrap_device
from tests.integration.helpers import create_device, create_user


async def test_bootstrap_device_creates_new_device(session: AsyncSession) -> None:
    user = await create_user(session, nickname="@u1")

    payload = BootstrapDeviceRequest(
        device_uuid="device-1",
        device_name="Pixel 8",
        platform="android",
        app_version="1.0.0",
        fcm_token="fcm-1",
        registration_id=101,
        public_identity_key="identity-1",
        public_signing_key="signing-1",
        signed_prekey_id=1,
        signed_prekey="signed-1",
        signed_prekey_signature="signature-1",
        one_time_prekeys=[
            {"prekey_id": 1, "public_prekey": "pk1"},
            {"prekey_id": 2, "public_prekey": "pk2"},
        ],
    )

    result = await bootstrap_device(
        session,
        current_user=user,
        payload=payload,
    )

    assert result["device_uuid"] == "device-1"
    assert result["prekeys_count"] == 2

    query = await session.execute(select(Device).where(Device.user_id == user.id))
    devices = list(query.scalars().all())

    assert len(devices) == 1
    assert devices[0].is_active is True
    assert devices[0].fcm_token == "fcm-1"


async def test_bootstrap_device_keeps_previous_device_active(
    session: AsyncSession,
) -> None:
    user = await create_user(session, nickname="@u1")
    old_device = await create_device(
        session,
        user_id=user.id,
        device_uuid="old-device",
        is_active=True,
    )
    await session.commit()

    payload = BootstrapDeviceRequest(
        device_uuid="new-device",
        device_name="Pixel 9",
        platform="android",
        app_version="2.0.0",
        fcm_token="new-fcm",
        registration_id=202,
        public_identity_key="identity-2",
        public_signing_key="signing-2",
        signed_prekey_id=2,
        signed_prekey="signed-2",
        signed_prekey_signature="signature-2",
        one_time_prekeys=[],
    )

    result = await bootstrap_device(
        session,
        current_user=user,
        payload=payload,
    )

    assert result["device_uuid"] == "new-device"

    old_device_check = await session.get(Device, old_device.id)
    assert old_device_check is not None
    assert old_device_check.is_active is True

    query = await session.execute(
        select(Device).where(Device.user_id == user.id, Device.is_active.is_(True))
    )
    active_devices = list(query.scalars().all())
    assert len(active_devices) == 2
    assert {device.device_uuid for device in active_devices} == {
        "old-device",
        "new-device",
    }
