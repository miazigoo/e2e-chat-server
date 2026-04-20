# coding=utf-8
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, ConflictError
from app.schemas.keys import RefillPreKeysRequest
from app.services.key_service import get_key_bundle_for_user, refill_prekeys
from tests.integration.helpers import create_device, create_user


async def test_get_key_bundle_for_self_forbidden(session: AsyncSession) -> None:
    user = await create_user(session, nickname="@u1")
    device = await create_device(session, user_id=user.id)
    await session.commit()

    with pytest.raises(BadRequestError) as exc:
        await get_key_bundle_for_user(
            session,
            current_user=user,
            current_device=device,
            target_user_id=user.id,
        )

    assert exc.value.status_code == 400
    assert exc.value.code == "SELF_BUNDLE_REQUEST_NOT_ALLOWED"
    assert exc.value.message == "Cannot request bundle for yourself"


async def test_get_key_bundle_target_without_device(session: AsyncSession) -> None:
    requester = await create_user(session, nickname="@u1")
    target = await create_user(session, nickname="@u2")
    requester_device = await create_device(session, user_id=requester.id)
    await session.commit()

    with pytest.raises(ConflictError) as exc:
        await get_key_bundle_for_user(
            session,
            current_user=requester,
            current_device=requester_device,
            target_user_id=target.id,
        )

    assert exc.value.status_code == 409
    assert exc.value.code == "TARGET_DEVICE_NOT_READY"
    assert exc.value.message == "Target user has no active device"


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
