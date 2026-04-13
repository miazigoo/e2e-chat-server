from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.dependencies.auth import get_current_user
from app.models.device import Device
from app.models.user import User
from app.repositories.devices import DevicesRepository

devices_repo = DevicesRepository()


async def get_current_device(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
    x_device_uuid: str | None = Header(default=None, alias="X-Device-UUID"),
) -> Device:
    if not x_device_uuid:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "DEVICE_UUID_REQUIRED",
                "message": "X-Device-UUID header is required",
            },
        )

    device = await devices_repo.get_by_user_and_uuid(
        session,
        user_id=current_user.id,
        device_uuid=x_device_uuid,
    )

    if not device or not device.is_active or device.revoked_at is not None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "code": "DEVICE_NOT_REGISTERED",
                "message": "Device is not registered or inactive",
            },
        )

    return device
