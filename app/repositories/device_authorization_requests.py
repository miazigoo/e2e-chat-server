from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.device_authorization_request import DeviceAuthorizationRequest


class DeviceAuthorizationRequestsRepository:
    async def get_by_request_id(
        self,
        session: AsyncSession,
        *,
        request_id: str,
    ) -> DeviceAuthorizationRequest | None:
        result = await session.execute(
            select(DeviceAuthorizationRequest).where(
                DeviceAuthorizationRequest.request_id == request_id
            )
        )
        return result.scalar_one_or_none()

    async def get_latest_for_device(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        device_uuid: str,
    ) -> DeviceAuthorizationRequest | None:
        result = await session.execute(
            select(DeviceAuthorizationRequest)
            .where(
                DeviceAuthorizationRequest.user_id == user_id,
                DeviceAuthorizationRequest.device_uuid == device_uuid,
            )
            .order_by(DeviceAuthorizationRequest.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        session: AsyncSession,
        *,
        request_id: str,
        user_id: int,
        device_uuid: str,
        device_name: str | None,
        platform: str | None,
        app_version: str | None,
        ip_address: str | None,
        user_agent: str | None,
        expires_at: datetime,
    ) -> DeviceAuthorizationRequest:
        request = DeviceAuthorizationRequest(
            request_id=request_id,
            user_id=user_id,
            device_uuid=device_uuid,
            device_name=device_name,
            platform=platform,
            app_version=app_version,
            ip_address=ip_address,
            user_agent=user_agent,
            status="pending",
            expires_at=expires_at,
        )
        session.add(request)
        await session.flush()
        return request

    async def list_pending_for_user(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        now_dt: datetime,
    ) -> list[DeviceAuthorizationRequest]:
        result = await session.execute(
            select(DeviceAuthorizationRequest)
            .where(
                DeviceAuthorizationRequest.user_id == user_id,
                DeviceAuthorizationRequest.status == "pending",
                DeviceAuthorizationRequest.expires_at > now_dt,
            )
            .order_by(DeviceAuthorizationRequest.requested_at.desc())
        )
        return list(result.scalars().all())

    async def resolve(
        self,
        session: AsyncSession,
        *,
        request: DeviceAuthorizationRequest,
        status: str,
        resolved_at: datetime,
        resolved_by_device_id: int,
    ) -> DeviceAuthorizationRequest:
        request.status = status
        request.resolved_at = resolved_at
        request.resolved_by_device_id = resolved_by_device_id
        await session.flush()
        return request
