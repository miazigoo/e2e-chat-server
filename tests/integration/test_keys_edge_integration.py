import pytest
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.keys import RefillPreKeysRequest
from app.services.key_service import get_key_bundle_for_user, refill_prekeys
from tests.integration.helpers import create_device, create_user


async def test_get_key_bundle_for_self_forbidden(session: AsyncSession) -> None:
    user = await create_user(session, nickname="@u1")
    device = await create_device(session, user_id=user.id, device_uuid="device-1")
    await session.commit()

    with pytest.raises(HTTPException) as exc:
        await get_key_bundle_for_user(
            session,
            current_user=user,
            current_device=device,
            target_user_id=user.id,
        )

    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "SELF_BUNDLE_REQUEST_NOT_ALLOWED"


async def test_get_key_bundle_target_without_device(session: AsyncSession) -> None:
    requester = await create_user(session, nickname="@req")
    requester_device = await create_device(
        session,
        user_id=requester.id,
        device_uuid="req-device",
    )

    target = await create_user(session, nickname="@target")
    await session.commit()

    with pytest.raises(HTTPException) as exc:
        await get_key_bundle_for_user(
            session,
            current_user=requester,
            current_device=requester_device,
            target_user_id=target.id,
        )

    assert exc.value.status_code == 409
    assert exc.value.detail["code"] == "TARGET_DEVICE_NOT_READY"


async def test_refill_prekeys_with_duplicates_keeps_unique_count(
    session: AsyncSession,
) -> None:
    user = await create_user(session, nickname="@u1")
    device = await create_device(session, user_id=user.id, device_uuid="device-1")
    await session.commit()

    result = await refill_prekeys(
        session,
        current_device=device,
        payload=RefillPreKeysRequest(
            prekeys=[
                {"prekey_id": 1, "public_prekey": "pk1"},
                {"prekey_id": 1, "public_prekey": "pk1-duplicate"},
                {"prekey_id": 2, "public_prekey": "pk2"},
            ]
        ),
    )

    assert result["added"] == 2
    assert result["prekeys_count"] == 2
