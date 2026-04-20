import hashlib
import secrets
import string
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    LockedError,
    NotFoundError,
    UnauthorizedError,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.repositories.auth import AuthRepository
from app.repositories.auth_sessions import AuthSessionsRepository
from app.repositories.users import UsersRepository
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    VerifyEmailCodeRequest,
)

users_repo = UsersRepository()
auth_repo = AuthRepository()
auth_sessions_repo = AuthSessionsRepository()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _mask_email(email: str | None) -> str | None:
    if not email or "@" not in email:
        return None

    name, domain = email.split("@", 1)
    if len(name) <= 1:
        masked_name = "*"
    else:
        masked_name = f"{name[0]}***"
    return f"{masked_name}@{domain}"


def _generate_email_code() -> str:
    return "".join(secrets.choice(string.digits) for _ in range(6))


def _hash_email_code(login_challenge_id: str, code: str) -> str:
    raw = f"{settings.jwt_secret_key}:{login_challenge_id}:{code}".encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _get_lock_duration_for_stage(stage: int) -> timedelta | None:
    if stage == 0:
        return timedelta(hours=3)
    if stage == 1:
        return timedelta(hours=6)
    if stage == 2:
        return timedelta(hours=24)
    return None


async def _issue_session_tokens(
    session: AsyncSession,
    *,
    user_id: int,
    nickname: str,
    device_id: int,
    ip_address: str | None,
    user_agent: str | None,
) -> dict:
    session_id = str(uuid4())
    issued_at = _now()
    expires_at = issued_at + timedelta(days=settings.refresh_token_expire_days)

    access_token = create_access_token(
        subject=str(user_id),
        extra={
            "nickname": nickname,
            "sid": session_id,
            "device_id": device_id,
        },
    )
    refresh_token = create_refresh_token(
        subject=str(user_id),
        extra={
            "nickname": nickname,
            "sid": session_id,
            "device_id": device_id,
        },
    )

    await auth_sessions_repo.create(
        session,
        session_id=session_id,
        user_id=user_id,
        device_id=device_id,
        refresh_token_hash=hash_token(refresh_token),
        issued_at=issued_at,
        expires_at=expires_at,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": settings.access_token_expire_minutes * 60,
        "session_id": session_id,
    }


async def register_user(session: AsyncSession, payload: RegisterRequest) -> dict:
    existing_user = await users_repo.get_by_nickname(session, payload.nickname)
    if existing_user:
        raise ConflictError(
            code="NICKNAME_ALREADY_EXISTS",
            message="Nickname already exists",
        )

    if payload.email:
        existing_email = await users_repo.get_by_email(session, payload.email)
        if existing_email:
            raise ConflictError(
                code="EMAIL_ALREADY_EXISTS",
                message="Email already exists",
            )

    user = await users_repo.create_user(
        session,
        nickname=payload.nickname,
        password_hash=hash_password(payload.password),
        email=payload.email,
        email_2fa_enabled=payload.email_2fa_enabled,
    )

    await session.commit()

    return {
        "user_id": user.id,
        "nickname": user.nickname,
        "requires_device_registration": True,
    }


async def login_user(
    session: AsyncSession,
    payload: LoginRequest,
    *,
    ip_address: str | None = None,
    device_fingerprint: str | None = None,
) -> dict:
    user = await users_repo.get_by_nickname(session, payload.nickname)

    if not user:
        await auth_repo.create_login_attempt(
            session,
            nickname=payload.nickname,
            user_id=None,
            ip_address=ip_address,
            device_fingerprint=device_fingerprint,
            success=False,
            failure_reason="user_not_found",
        )
        await session.commit()

        raise UnauthorizedError(
            code="INVALID_CREDENTIALS",
            message="Invalid nickname or password",
        )

    if user.is_deleted or user.pending_deletion:
        raise ForbiddenError(
            code="ACCOUNT_PENDING_DELETION",
            message="Account is pending deletion",
        )

    if user.lock_until and user.lock_until > _now():
        raise LockedError(
            code="ACCOUNT_LOCKED",
            message=f"Account is locked until {user.lock_until.isoformat()}",
        )

    if not verify_password(payload.password, user.password_hash):
        await auth_repo.create_login_attempt(
            session,
            nickname=payload.nickname,
            user_id=user.id,
            ip_address=ip_address,
            device_fingerprint=device_fingerprint,
            success=False,
            failure_reason="invalid_password",
        )

        window_start = _now() - timedelta(minutes=settings.login_failure_window_minutes)
        failed_count = await auth_repo.count_recent_failed_attempts(
            session,
            user_id=user.id,
            since_dt=window_start,
        )

        if failed_count >= settings.login_max_failed_attempts:
            lock_duration = _get_lock_duration_for_stage(user.failed_login_stage)

            if lock_duration is None:
                user.pending_deletion = True
                user.is_frozen = True
            else:
                user.lock_until = _now() + lock_duration
                user.failed_login_stage += 1

        await session.commit()

        if user.pending_deletion:
            raise ForbiddenError(
                code="ACCOUNT_PENDING_DELETION",
                message="Account is pending deletion",
            )

        if user.lock_until and user.lock_until > _now():
            raise LockedError(
                code="ACCOUNT_LOCKED",
                message=f"Account is locked until {user.lock_until.isoformat()}",
            )

        raise UnauthorizedError(
            code="INVALID_CREDENTIALS",
            message="Invalid nickname or password",
        )

    await auth_repo.create_login_attempt(
        session,
        nickname=payload.nickname,
        user_id=user.id,
        ip_address=ip_address,
        device_fingerprint=device_fingerprint,
        success=True,
        failure_reason=None,
    )

    user.lock_until = None
    user.failed_login_stage = 0

    if user.email_2fa_enabled and user.email:
        login_challenge_id = str(uuid4())
        code = _generate_email_code()
        code_hash = _hash_email_code(login_challenge_id, code)
        expires_at = _now() + timedelta(minutes=settings.email_code_expire_minutes)

        await auth_repo.create_email_code(
            session,
            user_id=user.id,
            login_challenge_id=login_challenge_id,
            code_hash=code_hash,
            expires_at=expires_at,
        )

        await session.commit()

        response = {
            "requires_email_code": True,
            "login_challenge_id": login_challenge_id,
            "email_masked": _mask_email(user.email),
        }

        if settings.debug:
            response["debug_code"] = code

        return response

    await session.commit()

    access_token = create_access_token(
        subject=str(user.id),
        extra={"nickname": user.nickname},
    )
    refresh_token = create_refresh_token(
        subject=str(user.id),
        extra={"nickname": user.nickname},
    )

    return {
        "requires_email_code": False,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": settings.access_token_expire_minutes * 60,
    }


async def verify_email_code(
    session: AsyncSession,
    payload: VerifyEmailCodeRequest,
) -> dict:
    record = await auth_repo.get_email_code_by_challenge(
        session,
        login_challenge_id=payload.login_challenge_id,
    )

    if not record:
        raise NotFoundError(
            code="CHALLENGE_NOT_FOUND",
            message="Login challenge not found",
        )

    if record.consumed_at is not None:
        raise BadRequestError(
            code="CHALLENGE_ALREADY_USED",
            message="Login challenge already used",
        )

    if record.expires_at < _now():
        raise BadRequestError(
            code="CHALLENGE_EXPIRED",
            message="Login challenge expired",
        )

    expected_hash = _hash_email_code(payload.login_challenge_id, payload.code)
    if expected_hash != record.code_hash:
        record.attempts += 1
        await session.commit()

        raise BadRequestError(
            code="INVALID_EMAIL_CODE",
            message="Invalid verification code",
        )

    user = await users_repo.get_by_id(session, record.user_id)
    if not user or user.is_deleted or user.pending_deletion:
        raise ForbiddenError(
            code="ACCOUNT_UNAVAILABLE",
            message="Account unavailable",
        )

    record.consumed_at = _now()
    await session.commit()

    access_token = create_access_token(
        subject=str(user.id),
        extra={"nickname": user.nickname},
    )
    refresh_token = create_refresh_token(
        subject=str(user.id),
        extra={"nickname": user.nickname},
    )

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": settings.access_token_expire_minutes * 60,
    }


async def refresh_access_token(
    session: AsyncSession,
    payload: RefreshRequest,
) -> dict:
    try:
        token_data = decode_token(payload.refresh_token)
    except Exception as exc:
        raise UnauthorizedError(
            code="INVALID_REFRESH_TOKEN",
            message="Invalid refresh token",
        ) from exc

    if token_data.get("type") != "refresh":
        raise UnauthorizedError(
            code="INVALID_TOKEN_TYPE",
            message="Token is not a refresh token",
        )

    user_id = token_data.get("sub")
    if not user_id:
        raise UnauthorizedError(
            code="INVALID_REFRESH_TOKEN",
            message="Invalid refresh token payload",
        )

    user = await users_repo.get_by_id(session, int(user_id))
    if not user or user.is_deleted or user.pending_deletion:
        raise ForbiddenError(
            code="ACCOUNT_UNAVAILABLE",
            message="Account unavailable",
        )

    access_token = create_access_token(
        subject=str(user.id),
        extra={"nickname": user.nickname},
    )

    return {
        "access_token": access_token,
        "expires_in": settings.access_token_expire_minutes * 60,
    }
