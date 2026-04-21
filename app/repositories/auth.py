from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.auth_email_code import AuthEmailCode
from app.models.login_attempt import LoginAttempt


class AuthRepository:
    async def create_login_attempt(
        self,
        session: AsyncSession,
        *,
        nickname: str,
        user_id: int | None,
        ip_address: str | None,
        device_fingerprint: str | None,
        success: bool,
        failure_reason: str | None = None,
    ) -> LoginAttempt:
        attempt = LoginAttempt(
            nickname=nickname,
            user_id=user_id,
            ip_address=ip_address,
            device_fingerprint=device_fingerprint,
            success=success,
            failure_reason=failure_reason,
        )
        session.add(attempt)
        await session.flush()
        return attempt

    async def count_recent_failed_attempts(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        since_dt: datetime,
    ) -> int:
        result = await session.execute(
            select(func.count(LoginAttempt.id)).where(
                LoginAttempt.user_id == user_id,
                LoginAttempt.success.is_(False),
                LoginAttempt.created_at >= since_dt,
            )
        )
        return int(result.scalar_one() or 0)

    async def invalidate_active_email_codes(
        self,
        session: AsyncSession,
        *,
        user_id: int,
    ) -> int:
        result = await session.execute(
            delete(AuthEmailCode)
            .where(
                AuthEmailCode.user_id == user_id,
                AuthEmailCode.consumed_at.is_(None),
            )
            .returning(AuthEmailCode.id)
        )
        return len(result.scalars().all())

    async def create_email_code(
        self,
        session: AsyncSession,
        *,
        user_id: int,
        login_challenge_id: str,
        code_hash: str,
        expires_at: datetime,
    ) -> AuthEmailCode:
        email_code = AuthEmailCode(
            user_id=user_id,
            login_challenge_id=login_challenge_id,
            code_hash=code_hash,
            expires_at=expires_at,
        )
        session.add(email_code)
        await session.flush()
        return email_code

    async def get_email_code_by_challenge(
        self,
        session: AsyncSession,
        *,
        login_challenge_id: str,
    ) -> AuthEmailCode | None:
        result = await session.execute(
            select(AuthEmailCode).where(
                AuthEmailCode.login_challenge_id == login_challenge_id
            )
        )
        return result.scalar_one_or_none()
