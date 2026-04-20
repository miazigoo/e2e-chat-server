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
    create_bootstrap_token,
    create_refresh_token,
    decode_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.models.auth_session import AuthSession
from app.models.device import Device
from app.repositories.auth import AuthRepository
from app.repositories.auth_sessions import AuthSessionsRepository
from app.repositories.devices import DevicesRepository
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
devices_repo = DevicesRepository()


def _enqueue_purge_account(user_id: int, reason: str) -> None:
    try:
        from app.worker.tasks import purge_account_task

        purge_account_task.delay(user_id, reason)
    except Exception:
        # fail-safe: account already gets frozen/pending_deletion
        return


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


def _bootstrap_response(*, user_id: int, nickname: str) -> dict:
    bootstrap_token = create_bootstrap_token(
        subject=str(user_id),
        extra={"nickname": nickname},
    )
    return {
        "requires_bootstrap": True,
        "bootstrap_token": bootstrap_token,
        "bootstrap_expires_in": settings.bootstrap_token_expire_minutes * 60,
    }


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


async def _resolve_device_for_auth(
    session: AsyncSession,
    *,
    user_id: int,
    nickname: str,
    device_uuid: str | None,
) -> tuple[Device | None, dict | None]:
    if device_uuid:
        device = await devices_repo.get_by_user_and_uuid(
            session,
            user_id=user_id,
            device_uuid=device_uuid,
        )
        if device and device.is_active and device.revoked_at is None:
            return device, None

        active_device = await devices_repo.get_active_by_user_id(
            session,
            user_id=user_id,
        )
        if active_device is None:
            return None, _bootstrap_response(user_id=user_id, nickname=nickname)

        raise ForbiddenError(
            code="DEVICE_NOT_REGISTERED",
            message="Device is not registered for this account",
        )

    active_device = await devices_repo.get_active_by_user_id(
        session,
        user_id=user_id,
    )
    if active_device is None:
        return None, _bootstrap_response(user_id=user_id, nickname=nickname)

    raise BadRequestError(
        code="DEVICE_UUID_REQUIRED",
        message="device_uuid is required for login on an existing device",
    )


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
        **_bootstrap_response(user_id=user.id, nickname=user.nickname),
    }


async def login_user(
    session: AsyncSession,
    payload: LoginRequest,
    *,
    ip_address: str | None = None,
    device_fingerprint: str | None = None,
    user_agent: str | None = None,
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

    if user.is_deleted or user.pending_deletion or not user.is_active or user.is_frozen:
        raise ForbiddenError(
            code="ACCOUNT_UNAVAILABLE",
            message="Account unavailable",
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
                _enqueue_purge_account(user.id, "too_many_failed_attempts")
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
            "requires_bootstrap": False,
            "login_challenge_id": login_challenge_id,
            "email_masked": _mask_email(user.email),
        }

        if settings.debug:
            response["debug_code"] = code

        return response

    device, bootstrap_data = await _resolve_device_for_auth(
        session,
        user_id=user.id,
        nickname=user.nickname,
        device_uuid=payload.device_uuid,
    )

    if bootstrap_data is not None:
        await session.commit()
        return {
            "requires_email_code": False,
            **bootstrap_data,
        }

    assert device is not None

    tokens = await _issue_session_tokens(
        session,
        user_id=user.id,
        nickname=user.nickname,
        device_id=device.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    await session.commit()

    return {
        "requires_email_code": False,
        "requires_bootstrap": False,
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "expires_in": tokens["expires_in"],
    }


async def verify_email_code(
    session: AsyncSession,
    payload: VerifyEmailCodeRequest,
    *,
    ip_address: str | None = None,
    user_agent: str | None = None,
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
    if (
        not user
        or user.is_deleted
        or user.pending_deletion
        or not user.is_active
        or user.is_frozen
    ):
        raise ForbiddenError(
            code="ACCOUNT_UNAVAILABLE",
            message="Account unavailable",
        )

    record.consumed_at = _now()

    device, bootstrap_data = await _resolve_device_for_auth(
        session,
        user_id=user.id,
        nickname=user.nickname,
        device_uuid=payload.device_uuid,
    )

    if bootstrap_data is not None:
        await session.commit()
        return bootstrap_data

    assert device is not None

    tokens = await _issue_session_tokens(
        session,
        user_id=user.id,
        nickname=user.nickname,
        device_id=device.id,
        ip_address=ip_address,
        user_agent=user_agent,
    )

    await session.commit()

    return {
        "requires_bootstrap": False,
        "access_token": tokens["access_token"],
        "refresh_token": tokens["refresh_token"],
        "expires_in": tokens["expires_in"],
    }


async def refresh_access_token(
    session: AsyncSession,
    payload: RefreshRequest,
    *,
    ip_address: str | None = None,
    user_agent: str | None = None,
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

    user_id_raw = token_data.get("sub")
    session_id = token_data.get("sid")
    device_id_raw = token_data.get("device_id")

    if not user_id_raw or not session_id or not device_id_raw:
        raise UnauthorizedError(
            code="INVALID_REFRESH_TOKEN",
            message="Invalid refresh token payload",
        )

    user_id = int(user_id_raw)
    device_id = int(device_id_raw)

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

    if auth_session.user_id != user_id or auth_session.device_id != device_id:
        raise UnauthorizedError(
            code="SESSION_TOKEN_MISMATCH",
            message="Refresh token does not match the active session",
        )

    if auth_session.refresh_token_hash != hash_token(payload.refresh_token):
        raise UnauthorizedError(
            code="REFRESH_TOKEN_REVOKED",
            message="Refresh token is no longer valid",
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

    access_token = create_access_token(
        subject=str(user.id),
        extra={
            "nickname": user.nickname,
            "sid": auth_session.session_id,
            "device_id": auth_session.device_id,
        },
    )
    refresh_token = create_refresh_token(
        subject=str(user.id),
        extra={
            "nickname": user.nickname,
            "sid": auth_session.session_id,
            "device_id": auth_session.device_id,
        },
    )

    await auth_sessions_repo.update_refresh_token_hash(
        session,
        auth_session_id=auth_session.id,
        refresh_token_hash=hash_token(refresh_token),
    )
    await session.commit()

    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_in": settings.access_token_expire_minutes * 60,
    }


async def logout_current_session(
    session: AsyncSession,
    *,
    current_session: AuthSession,
) -> dict:
    revoked = await auth_sessions_repo.revoke_by_session_id(
        session,
        session_id=current_session.session_id,
        revoked_at=_now(),
    )
    await session.commit()

    return {
        "message": "Logged out",
        "revoked_sessions": revoked,
    }


async def logout_all_sessions(
    session: AsyncSession,
    *,
    user_id: int,
) -> dict:
    revoked = await auth_sessions_repo.revoke_all_for_user(
        session,
        user_id=user_id,
        revoked_at=_now(),
    )
    await session.commit()

    return {
        "message": "All sessions revoked",
        "revoked_sessions": revoked,
    }
