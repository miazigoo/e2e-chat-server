from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import decode_token
from app.models.user import User
from app.repositories.users import UsersRepository

bearer_scheme = HTTPBearer(auto_error=False)
users_repo = UsersRepository()


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_db),
) -> User:
    if credentials is None:
        raise UnauthorizedError(
            code="AUTH_REQUIRED",
            message="Authorization required",
        )

    try:
        payload = decode_token(credentials.credentials)
    except Exception as exc:
        raise UnauthorizedError(
            code="INVALID_ACCESS_TOKEN",
            message="Invalid access token",
        ) from exc

    if payload.get("type") != "access":
        raise UnauthorizedError(
            code="INVALID_TOKEN_TYPE",
            message="Token is not an access token",
        )

    user_id = payload.get("sub")
    if not user_id:
        raise UnauthorizedError(
            code="INVALID_ACCESS_TOKEN",
            message="Invalid access token payload",
        )

    user = await users_repo.get_by_id(session, int(user_id))
    if not user or user.is_deleted or user.pending_deletion:
        raise ForbiddenError(
            code="ACCOUNT_UNAVAILABLE",
            message="Account unavailable",
        )

    return user
