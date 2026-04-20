from datetime import timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import (
    BadRequestError,
    ConflictError,
    LockedError,
    UnauthorizedError,
)
from app.core.security import hash_password
from app.models.auth_email_code import AuthEmailCode
from app.models.login_attempt import LoginAttempt
from app.schemas.auth import LoginRequest, RegisterRequest, VerifyEmailCodeRequest
from app.services.auth_service import login_user, register_user, verify_email_code
from tests.integration.helpers import create_user


async def test_register_user_persists_user(session: AsyncSession) -> None:
    result = await register_user(
        session,
        RegisterRequest(
            nickname="@newuser",
            password="supersecret123",
            email="newuser@example.com",
            email_2fa_enabled=True,
        ),
    )

    assert result["nickname"] == "@newuser"
    assert result["requires_device_registration"] is True


async def test_register_user_duplicate_nickname(session: AsyncSession) -> None:
    await create_user(session, nickname="@dup")
    await session.commit()

    with pytest.raises(ConflictError) as exc:
        await register_user(
            session,
            RegisterRequest(
                nickname="@dup",
                password="supersecret123",
                email=None,
                email_2fa_enabled=False,
            ),
        )

    assert exc.value.status_code == 409
    assert exc.value.code == "NICKNAME_ALREADY_EXISTS"
    assert exc.value.message == "Nickname already exists"


async def test_register_user_duplicate_email(session: AsyncSession) -> None:
    await create_user(session, nickname="@u1", email="same@example.com")
    await session.commit()

    with pytest.raises(ConflictError) as exc:
        await register_user(
            session,
            RegisterRequest(
                nickname="@u2",
                password="supersecret123",
                email="same@example.com",
                email_2fa_enabled=True,
            ),
        )

    assert exc.value.status_code == 409
    assert exc.value.code == "EMAIL_ALREADY_EXISTS"
    assert exc.value.message == "Email already exists"


async def test_login_wrong_password_creates_failed_attempt(
    session: AsyncSession,
) -> None:
    await create_user(
        session,
        nickname="@u1",
        password_hash=hash_password("correct-password"),
    )
    await session.commit()

    with pytest.raises(UnauthorizedError) as exc:
        await login_user(
            session,
            LoginRequest(nickname="@u1", password="wrong-password"),
        )

    assert exc.value.status_code == 401
    assert exc.value.code == "INVALID_CREDENTIALS"
    assert exc.value.message == "Invalid nickname or password"

    result = await session.execute(select(LoginAttempt))
    attempts = list(result.scalars().all())

    assert len(attempts) == 1
    assert attempts[0].success is False
    assert attempts[0].failure_reason == "invalid_password"


async def test_login_locks_after_threshold(session: AsyncSession) -> None:
    user = await create_user(
        session,
        nickname="@u1",
        password_hash=hash_password("correct-password"),
    )
    await session.commit()

    for _ in range(4):
        with pytest.raises(UnauthorizedError) as exc:
            await login_user(
                session,
                LoginRequest(nickname="@u1", password="wrong-password"),
            )

        assert exc.value.status_code == 401
        assert exc.value.code == "INVALID_CREDENTIALS"

    with pytest.raises(LockedError) as exc:
        await login_user(
            session,
            LoginRequest(nickname="@u1", password="wrong-password"),
        )

    assert exc.value.status_code == 423
    assert exc.value.code == "ACCOUNT_LOCKED"

    refreshed = await session.get(type(user), user.id)
    assert refreshed is not None
    assert refreshed.lock_until is not None
    assert refreshed.failed_login_stage == 1

    with pytest.raises(LockedError) as exc:
        await login_user(
            session,
            LoginRequest(nickname="@u1", password="wrong-password"),
        )

    assert exc.value.status_code == 423
    assert exc.value.code == "ACCOUNT_LOCKED"


async def test_login_success_with_email_2fa_creates_code(session: AsyncSession) -> None:
    user = await create_user(
        session,
        nickname="@u1",
        password_hash=hash_password("correct-password"),
        email="u1@example.com",
        email_2fa_enabled=True,
    )
    await session.commit()

    result = await login_user(
        session,
        LoginRequest(nickname="@u1", password="correct-password"),
    )

    assert result["requires_email_code"] is True
    assert "login_challenge_id" in result

    query = await session.execute(
        select(AuthEmailCode).where(AuthEmailCode.user_id == user.id)
    )
    codes = list(query.scalars().all())

    assert len(codes) == 1
    assert codes[0].consumed_at is None


async def test_verify_email_code_success(session: AsyncSession) -> None:
    await create_user(
        session,
        nickname="@u1",
        password_hash=hash_password("correct-password"),
        email="u1@example.com",
        email_2fa_enabled=True,
    )
    await session.commit()

    login_result = await login_user(
        session,
        LoginRequest(nickname="@u1", password="correct-password"),
    )

    challenge_id = login_result["login_challenge_id"]
    debug_code = login_result["debug_code"]

    verify_result = await verify_email_code(
        session,
        VerifyEmailCodeRequest(
            login_challenge_id=challenge_id,
            code=debug_code,
        ),
    )

    assert "bootstrap_token" in verify_result
    assert "bootstrap_expires_in" in verify_result
    assert verify_result["bootstrap_expires_in"] > 0

    query = await session.execute(
        select(AuthEmailCode).where(AuthEmailCode.login_challenge_id == challenge_id)
    )
    record = query.scalar_one()

    assert record.consumed_at is not None


async def test_verify_email_code_reuse_fails(session: AsyncSession) -> None:
    await create_user(
        session,
        nickname="@u1",
        password_hash=hash_password("correct-password"),
        email="u1@example.com",
        email_2fa_enabled=True,
    )
    await session.commit()

    login_result = await login_user(
        session,
        LoginRequest(nickname="@u1", password="correct-password"),
    )

    challenge_id = login_result["login_challenge_id"]
    debug_code = login_result["debug_code"]

    await verify_email_code(
        session,
        VerifyEmailCodeRequest(
            login_challenge_id=challenge_id,
            code=debug_code,
        ),
    )

    with pytest.raises(BadRequestError) as exc:
        await verify_email_code(
            session,
            VerifyEmailCodeRequest(
                login_challenge_id=challenge_id,
                code=debug_code,
            ),
        )

    assert exc.value.status_code == 400
    assert exc.value.code == "CHALLENGE_ALREADY_USED"
    assert exc.value.message == "Login challenge already used"


async def test_verify_email_code_expired_fails(session: AsyncSession) -> None:
    await create_user(
        session,
        nickname="@u1",
        password_hash=hash_password("correct-password"),
        email="u1@example.com",
        email_2fa_enabled=True,
    )
    await session.commit()

    login_result = await login_user(
        session,
        LoginRequest(nickname="@u1", password="correct-password"),
    )

    challenge_id = login_result["login_challenge_id"]

    query = await session.execute(
        select(AuthEmailCode).where(AuthEmailCode.login_challenge_id == challenge_id)
    )
    record = query.scalar_one()
    record.expires_at = record.expires_at - timedelta(hours=1)
    await session.commit()

    with pytest.raises(BadRequestError) as exc:
        await verify_email_code(
            session,
            VerifyEmailCodeRequest(
                login_challenge_id=challenge_id,
                code=login_result["debug_code"],
            ),
        )

    assert exc.value.status_code == 400
    assert exc.value.code == "CHALLENGE_EXPIRED"
    assert exc.value.message == "Login challenge expired"
