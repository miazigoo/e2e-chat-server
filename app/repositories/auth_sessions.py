from __future__ import annotations

from datetime import datetime

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth_session import AuthSession


class AuthSessionsRepository:
    async def create(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        user_id: int,
        device_id: int,
        refresh_token_hash: str,
        issued_at: datetime,
        expires_at: datetime,
        ip_address: str | None,
        user_agent: str | None,
    ) -> AuthSession:
        auth_session = AuthSession(
            session_id=session_id,
            user_id=user_id,
            device_id=device_id,
            refresh_token_hash=refresh_token_hash,
            issued_at=issued_at,
            expires_at=expires_at,
            revoked_at=None,
            ip_address=ip_address,
            user_agent=user_agent,
        )
        session.add(auth_session)
        await session.flush()
        return auth_session

    async def get_by_session_id(
        self,
        session: AsyncSession,
        *,
        session_id: str,
    ) -> AuthSession | None:
        stmt = select(AuthSession).where(AuthSession.session_id == session_id)
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_by_session_id(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        now_dt: datetime,
    ) -> AuthSession | None:
        stmt = select(AuthSession).where(
            AuthSession.session_id == session_id,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now_dt,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_active_by_refresh_token_hash(
        self,
        session: AsyncSession,
        *,
        refresh_token_hash: str,
        now_dt: datetime,
    ) -> AuthSession | None:
        stmt = select(AuthSession).where(
            AuthSession.refresh_token_hash == refresh_token_hash,
            AuthSession.revoked_at.is_(None),
            AuthSession.expires_at > now_dt,
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none()

    async def update_refresh_token_hash(
        self,
        session: AsyncSession,
        *,
        auth_session_id: int,
        refresh_token_hash: str,
    ) -> None:
        stmt = (
            update(AuthSession)
            .where(AuthSession.id == auth_session_id)
            .values(refresh_token_hash=refresh_token_hash)
        )
        await session.execute(stmt)

    async def revoke_by_session_id(
        self,
        session: AsyncSession,
        *,
        session_id: str,
        revoked_at: datetime,
    ) -> int:
        stmt = (
            update(AuthSession)
            .where(
                AuthSession.session_id == session_id,
                AuthSession.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at)
            .returning(AuthSession.id)
        )
        result = await session.execute(stmt)
        return len(result.scalars().all())

    async def revoke_all_for_user(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        revoked_at: datetime,
    ) -> int:
        stmt = (
            update(AuthSession)
            .where(
                AuthSession.user_id == user_id,
                AuthSession.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at)
            .returning(AuthSession.id)
        )
        result = await session.execute(stmt)
        return len(result.scalars().all())

    async def revoke_all_for_user_except_session(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        keep_session_id: str,
        revoked_at: datetime,
    ) -> int:
        stmt = (
            update(AuthSession)
            .where(
                AuthSession.user_id == user_id,
                AuthSession.session_id != keep_session_id,
                AuthSession.revoked_at.is_(None),
            )
            .values(revoked_at=revoked_at)
            .returning(AuthSession.id)
        )
        result = await session.execute(stmt)
        return len(result.scalars().all())

    async def delete_expired(
        self,
        session: AsyncSession,
        *,
        now_dt: datetime,
    ) -> int:
        stmt = (
            delete(AuthSession)
            .where(AuthSession.expires_at <= now_dt)
            .returning(AuthSession.id)
        )
        result = await session.execute(stmt)
        return len(result.scalars().all())
