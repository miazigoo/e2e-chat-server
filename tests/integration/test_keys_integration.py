from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.device_prekey import DevicePreKey
from app.repositories.keys import KeysRepository
from app.schemas.keys import RefillPreKeysRequest, RotateSignedPreKeyRequest
from app.services.key_service import (
    get_key_bundle_for_user,
    refill_prekeys,
    rotate_signed_prekey,
)
from tests.integration.helpers import create_device, create_prekey, create_user


async def test_claim_one_time_prekey_marks_it_used(session: AsyncSession) -> None:
    user = await create_user(session, nickname="@u1")
    device = await create_device(session, user_id=user.id, device_uuid="device-1")
    await create_prekey(session, device_id=device.id, prekey_id=1, public_prekey="pk1")
    await create_prekey(session, device_id=device.id, prekey_id=2, public_prekey="pk2")
    await session.commit()

    repo = KeysRepository()
    claimed = await repo.claim_one_time_prekey(session, device_id=device.id)
    await session.commit()

    assert claimed is not None
    assert claimed.prekey_id == 1

    query = await session.execute(
        select(DevicePreKey)
        .where(DevicePreKey.device_id == device.id)
        .order_by(DevicePreKey.prekey_id)
    )
    prekeys = list(query.scalars().all())

    assert prekeys[0].is_used is True
    assert prekeys[0].used_at is not None
    assert prekeys[1].is_used is False


async def test_get_key_bundle_consumes_one_prekey(session: AsyncSession) -> None:
    requester = await create_user(session, nickname="@req")
    requester_device = await create_device(
        session,
        user_id=requester.id,
        device_uuid="req-device",
    )

    target = await create_user(session, nickname="@target")
    target_device = await create_device(
        session,
        user_id=target.id,
        device_uuid="target-device",
    )
    await create_prekey(
        session, device_id=target_device.id, prekey_id=11, public_prekey="pk11"
    )
    await create_prekey(
        session, device_id=target_device.id, prekey_id=12, public_prekey="pk12"
    )
    await session.commit()

    data = await get_key_bundle_for_user(
        session,
        current_user=requester,
        current_device=requester_device,
        target_user_id=target.id,
    )

    assert data["user_id"] == target.id
    assert data["device_id"] == target_device.id
    assert data["one_time_prekey"] is not None
    assert data["prekeys_remaining"] == 1

    query = await session.execute(
        select(DevicePreKey).where(DevicePreKey.device_id == target_device.id)
    )
    prekeys = list(query.scalars().all())
    used_count = sum(1 for item in prekeys if item.is_used)
    assert used_count == 1


async def test_refill_prekeys_adds_only_unique_ids(session: AsyncSession) -> None:
    user = await create_user(session, nickname="@u1")
    device = await create_device(session, user_id=user.id, device_uuid="device-1")
    await create_prekey(session, device_id=device.id, prekey_id=1, public_prekey="pk1")
    await session.commit()

    payload = RefillPreKeysRequest(
        prekeys=[
            {"prekey_id": 1, "public_prekey": "pk1-dup"},
            {"prekey_id": 2, "public_prekey": "pk2"},
            {"prekey_id": 3, "public_prekey": "pk3"},
        ]
    )

    result = await refill_prekeys(
        session,
        current_device=device,
        payload=payload,
    )

    assert result["added"] == 2
    assert result["prekeys_count"] == 3


async def test_rotate_signed_prekey_updates_device(session: AsyncSession) -> None:
    user = await create_user(session, nickname="@u1")
    device = await create_device(session, user_id=user.id, device_uuid="device-1")
    await session.commit()

    payload = RotateSignedPreKeyRequest(
        signed_prekey="new-signed-prekey",
        signed_prekey_signature="new-signature",
    )

    result = await rotate_signed_prekey(
        session,
        current_device=device,
        payload=payload,
    )

    assert result["rotated"] is True

    refreshed = await session.get(type(device), device.id)
    assert refreshed is not None
    assert refreshed.signed_prekey == "new-signed-prekey"
    assert refreshed.signed_prekey_signature == "new-signature"
