from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.core.exceptions import ForbiddenError, UnauthorizedError
from app.core.security import decode_token
from app.models.auth_session import AuthSession
from app.models.user import User
from app.repositories.auth_sessions import AuthSessionsRepository
from app.repositories.users import UsersRepository

bearer_scheme = HTTPBearer(auto_error=False)

users_repo = UsersRepository()
auth_sessions_repo = AuthSessionsRepository()


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def resolve_access_session(
    session: AsyncSession,
    token: str,
) -> tuple[AuthSession, dict[str, Any]]:
    try:
        payload = decode_token(token)
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

    user_id_raw = payload.get("sub")
    session_id = payload.get("sid")
    device_id_raw = payload.get("device_id")

    if not user_id_raw or not session_id or not device_id_raw:
        raise UnauthorizedError(
            code="INVALID_ACCESS_TOKEN",
            message="Invalid access token payload",
        )

    auth_session = await auth_sessions_repo.get_active_by_session_id(
        session,
        session_id=str(session_id),
        now_dt=_now(),
    )
    if auth_session is None:
        raise UnauthorizedError(
            code="SESSION_NOT_FOUND",
            message="Session is invalid or expired",
        )

    user_id = int(user_id_raw)
    device_id = int(device_id_raw)

    if auth_session.user_id != user_id or auth_session.device_id != device_id:
        raise UnauthorizedError(
            code="SESSION_TOKEN_MISMATCH",
            message="Token does not match the active session",
        )

    return auth_session, payload


async def get_current_session(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    session: AsyncSession = Depends(get_db),
) -> AuthSession:
    if credentials is None:
        raise UnauthorizedError(
            code="AUTH_REQUIRED",
            message="Authorization required",
        )

    auth_session, _ = await resolve_access_session(session, credentials.credentials)
    return auth_session


async def get_current_user(
    current_session: AuthSession = Depends(get_current_session),
    session: AsyncSession = Depends(get_db),
) -> User:
    user = await users_repo.get_by_id(session, current_session.user_id)
    if (
        user is None
        or user.is_deleted
        or user.pending_deletion
        or not user.is_active
        or user.is_frozen
    ):
        raise ForbiddenError(
            code="ACCOUNT_UNAVAILABLE",
            message="Account unavailable",
        )

    return user


async def get_bootstrap_user(
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
            code="INVALID_TOKEN",
            message="Invalid token",
        ) from exc

    token_type = payload.get("type")
    user_id_raw = payload.get("sub")
    if not user_id_raw:
        raise UnauthorizedError(
            code="INVALID_TOKEN",
            message="Invalid token payload",
        )

    if token_type == "access":
        auth_session, _ = await resolve_access_session(session, credentials.credentials)
        user_id = auth_session.user_id
    elif token_type == "bootstrap":
        user_id = int(user_id_raw)
    else:
        raise UnauthorizedError(
            code="INVALID_TOKEN_TYPE",
            message="Unsupported token type",
        )

    user = await users_repo.get_by_id(session, user_id)
    if (
        user is None
        or user.is_deleted
        or user.pending_deletion
        or not user.is_active
        or user.is_frozen
    ):
        raise ForbiddenError(
            code="ACCOUNT_UNAVAILABLE",
            message="Account unavailable",
        )

    return user
