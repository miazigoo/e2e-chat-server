from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User


class UsersRepository:
    async def get_by_id(self, session: AsyncSession, user_id: int) -> User | None:
        result = await session.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_by_nickname(
        self, session: AsyncSession, nickname: str
    ) -> User | None:
        result = await session.execute(select(User).where(User.nickname == nickname))
        return result.scalar_one_or_none()

    async def get_by_email(self, session: AsyncSession, email: str) -> User | None:
        result = await session.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def create_user(
        self,
        session: AsyncSession,
        *,
        nickname: str,
        password_hash: str,
        email: str | None,
        email_2fa_enabled: bool,
    ) -> User:
        user = User(
            nickname=nickname,
            password_hash=password_hash,
            email=email,
            email_2fa_enabled=email_2fa_enabled,
        )
        session.add(user)
        await session.flush()
        return user
