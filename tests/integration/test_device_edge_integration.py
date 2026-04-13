import pytest
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.device import Device
from app.schemas.devices import BootstrapDeviceRequest
from app.services.device_service import bootstrap_device
from tests.integration.helpers import create_device, create_user


async def test_bootstrap_rejects_non_android(session: AsyncSession) -> None:
    user = await create_user(session, nickname="@u1")
    await session.commit()

    with pytest.raises(HTTPException) as exc:
        await bootstrap_device(
            session,
            current_user=user,
            payload=BootstrapDeviceRequest(
                device_uuid="ios-device",
                device_name="iPhone",
                platform="ios",
                app_version="1.0.0",
                public_identity_key="identity",
                public_signing_key="signing",
                signed_prekey="signed",
                signed_prekey_signature="signature",
                one_time_prekeys=[],
            ),
        )

    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "UNSUPPORTED_PLATFORM"


async def test_bootstrap_existing_device_updates_it(session: AsyncSession) -> None:
    user = await create_user(session, nickname="@u1")
    device = await create_device(
        session,
        user_id=user.id,
        device_uuid="device-1",
        device_name="Old name",
        fcm_token="old-token",
    )
    await session.commit()

    result = await bootstrap_device(
        session,
        current_user=user,
        payload=BootstrapDeviceRequest(
            device_uuid="device-1",
            device_name="New name",
            platform="android",
            app_version="2.0.0",
            fcm_token="new-token",
            public_identity_key="identity-new",
            public_signing_key="signing-new",
            signed_prekey="signed-new",
            signed_prekey_signature="signature-new",
            one_time_prekeys=[],
        ),
    )

    assert result["device_id"] == device.id

    refreshed = await session.get(Device, device.id)
    assert refreshed is not None
    assert refreshed.device_name == "New name"
    assert refreshed.fcm_token == "new-token"
    assert refreshed.signed_prekey == "signed-new"


async def test_bootstrap_replaces_prekeys_with_unique_values(
    session: AsyncSession,
) -> None:
    user = await create_user(session, nickname="@u1")
    await session.commit()

    result = await bootstrap_device(
        session,
        current_user=user,
        payload=BootstrapDeviceRequest(
            device_uuid="device-1",
            device_name="Pixel",
            platform="android",
            app_version="1.0.0",
            public_identity_key="identity",
            public_signing_key="signing",
            signed_prekey="signed",
            signed_prekey_signature="signature",
            one_time_prekeys=[
                {"prekey_id": 1, "public_prekey": "pk1"},
                {"prekey_id": 1, "public_prekey": "pk1-dup"},
                {"prekey_id": 2, "public_prekey": "pk2"},
            ],
        ),
    )

    assert result["prekeys_count"] == 2

    query = await session.execute(select(Device).where(Device.user_id == user.id))
    device = query.scalar_one()
    assert device.prekeys_count == 2
