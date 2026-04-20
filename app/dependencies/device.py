from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.exceptions import BadRequestError, ForbiddenError
from app.dependencies.auth import get_current_session, get_current_user
from app.models.auth_session import AuthSession
from app.models.device import Device
from app.models.user import User
from app.repositories.devices import DevicesRepository

devices_repo = DevicesRepository()


async def get_current_device(
    current_user: User = Depends(get_current_user),
    current_session: AuthSession = Depends(get_current_session),
    session: AsyncSession = Depends(get_db),
    x_device_uuid: str | None = Header(default=None, alias="X-Device-UUID"),
) -> Device:
    if not x_device_uuid:
        raise BadRequestError(
            code="DEVICE_UUID_REQUIRED",
            message="X-Device-UUID header is required",
        )

    device = await devices_repo.get_by_user_and_uuid(
        session,
        user_id=current_user.id,
        device_uuid=x_device_uuid,
    )

    if not device or not device.is_active or device.revoked_at is not None:
        raise ForbiddenError(
            code="DEVICE_NOT_REGISTERED",
            message="Device is not registered or inactive",
        )

    if device.id != current_session.device_id:
        raise ForbiddenError(
            code="DEVICE_SESSION_MISMATCH",
            message="Device does not match the active session",
        )

    return device
