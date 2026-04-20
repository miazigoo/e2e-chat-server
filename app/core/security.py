import hashlib
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, cast

import jwt
from passlib.context import CryptContext

from app.core.config import settings

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")


def hash_password(password: str) -> str:
    return cast(str, pwd_context.hash(password))


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def verify_password(password: str, password_hash: str) -> bool:
    return cast(bool, pwd_context.verify(password, password_hash))


def _create_token(
    *,
    subject: str,
    token_type: str,
    expires_delta: timedelta,
    extra: Dict[str, Any] | None = None,
) -> str:
    now = datetime.now(timezone.utc)
    payload: Dict[str, Any] = {
        "sub": subject,
        "type": token_type,
        "exp": now + expires_delta,
        "iat": now,
    }
    if extra:
        payload.update(extra)

    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def create_access_token(subject: str, extra: Dict[str, Any] | None = None) -> str:
    return _create_token(
        subject=subject,
        token_type="access",
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes),
        extra=extra,
    )


def create_refresh_token(subject: str, extra: Dict[str, Any] | None = None) -> str:
    return _create_token(
        subject=subject,
        token_type="refresh",
        expires_delta=timedelta(days=settings.refresh_token_expire_days),
        extra=extra,
    )


def create_bootstrap_token(subject: str, extra: Dict[str, Any] | None = None) -> str:
    return _create_token(
        subject=subject,
        token_type="bootstrap",
        expires_delta=timedelta(minutes=settings.bootstrap_token_expire_minutes),
        extra=extra,
    )


def decode_token(token: str) -> dict[str, Any]:
    return jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
    )
