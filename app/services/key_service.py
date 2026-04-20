from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.models.device import Device
from app.models.user import User
from app.repositories.devices import DevicesRepository
from app.repositories.keys import KeysRepository
from app.repositories.users import UsersRepository
from app.schemas.keys import RefillPreKeysRequest, RotateSignedPreKeyRequest

users_repo = UsersRepository()
devices_repo = DevicesRepository()
keys_repo = KeysRepository()


async def get_key_bundle_for_user(
    session: AsyncSession,
    *,
    current_user: User,
    current_device: Device,
    target_user_id: int,
) -> dict:
    if target_user_id == current_user.id:
        raise BadRequestError(
            code="SELF_BUNDLE_REQUEST_NOT_ALLOWED",
            message="Cannot request bundle for yourself",
        )

    target_user = await users_repo.get_by_id(session, target_user_id)
    if not target_user or target_user.is_deleted or target_user.pending_deletion:
        raise NotFoundError(
            code="TARGET_USER_NOT_FOUND",
            message="Target user not found",
        )

    target_device = await devices_repo.get_active_by_user_id(
        session,
        user_id=target_user_id,
    )
    if not target_device:
        raise ConflictError(
            code="TARGET_DEVICE_NOT_READY",
            message="Target user has no active device",
        )

    claimed_prekey = await keys_repo.claim_one_time_prekey(
        session,
        device_id=target_device.id,
    )
    remaining_prekeys = await keys_repo.count_available_prekeys(
        session,
        device_id=target_device.id,
    )
    target_device.prekeys_count = remaining_prekeys

    await session.commit()

    return {
        "user_id": target_user.id,
        "device_id": target_device.id,
        "requested_by_device_id": current_device.id,
        "public_identity_key": target_device.public_identity_key,
        "public_signing_key": target_device.public_signing_key,
        "signed_prekey": target_device.signed_prekey,
        "signed_prekey_signature": target_device.signed_prekey_signature,
        "one_time_prekey": (
            {
                "prekey_id": claimed_prekey.prekey_id,
                "public_prekey": claimed_prekey.public_prekey,
            }
            if claimed_prekey is not None
            else None
        ),
        "prekeys_remaining": remaining_prekeys,
    }


async def refill_prekeys(
    session: AsyncSession,
    *,
    current_device: Device,
    payload: RefillPreKeysRequest,
) -> dict:
    seen_ids: set[int] = set()
    normalized_prekeys: list[dict[str, str | int]] = []

    for item in payload.prekeys:
        if item.prekey_id in seen_ids:
            continue
        seen_ids.add(item.prekey_id)
        normalized_prekeys.append(
            {
                "prekey_id": item.prekey_id,
                "public_prekey": item.public_prekey,
            }
        )

    added = await keys_repo.add_prekeys(
        session,
        device_id=current_device.id,
        prekeys=normalized_prekeys,
    )
    available_count = await keys_repo.count_available_prekeys(
        session,
        device_id=current_device.id,
    )
    current_device.prekeys_count = available_count

    await session.commit()

    return {
        "device_id": current_device.id,
        "added": added,
        "prekeys_count": available_count,
    }


async def rotate_signed_prekey(
    session: AsyncSession,
    *,
    current_device: Device,
    payload: RotateSignedPreKeyRequest,
) -> dict:
    await keys_repo.rotate_signed_prekey(
        session,
        device=current_device,
        signed_prekey=payload.signed_prekey,
        signed_prekey_signature=payload.signed_prekey_signature,
    )
    await session.commit()

    return {
        "device_id": current_device.id,
        "rotated": True,
    }
