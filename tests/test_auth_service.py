from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, cast

import pytest

import app.services.auth_service as auth_service
from app.core.config import settings
from app.core.exceptions import (
    BadRequestError,
    ConflictError,
    ForbiddenError,
    LockedError,
    NotFoundError,
    ServiceUnavailableError,
    UnauthorizedError,
)
from app.schemas.auth import (
    Google2FAConfirmRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    VerifyEmailCodeRequest,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def make_user(**overrides: Any) -> SimpleNamespace:
    base = {
        "id": 1,
        "nickname": "@tester",
        "password_hash": "hash",
        "is_deleted": False,
        "pending_deletion": False,
        "is_active": True,
        "is_frozen": False,
        "lock_until": None,
        "failed_login_stage": 0,
        "email_2fa_enabled": False,
        "email": None,
        "google_2fa_enabled": False,
        "google_2fa_secret": None,
        "google_2fa_pending_secret": None,
        "google_2fa_confirmed_at": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_register_user_duplicate_nickname(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_by_nickname(session: Any, nickname: str) -> Any:
        return SimpleNamespace(id=1, nickname=nickname)

    monkeypatch.setattr(
        auth_service.users_repo, "get_by_nickname", fake_get_by_nickname
    )

    session = cast(Any, SimpleNamespace())

    with pytest.raises(ConflictError) as exc:
        await auth_service.register_user(
            session,
            RegisterRequest(
                nickname="@tester",
                password="supersecret123",
                email=None,
                email_2fa_enabled=False,
            ),
        )

    assert exc.value.status_code == 409
    assert exc.value.code == "NICKNAME_ALREADY_EXISTS"
    assert exc.value.message == "Nickname already exists"


@pytest.mark.asyncio
async def test_register_user_duplicate_email(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_by_nickname(session: Any, nickname: str) -> Any:
        return None

    async def fake_get_by_email(session: Any, email: str) -> Any:
        return SimpleNamespace(id=2, email=email)

    monkeypatch.setattr(
        auth_service.users_repo, "get_by_nickname", fake_get_by_nickname
    )
    monkeypatch.setattr(auth_service.users_repo, "get_by_email", fake_get_by_email)

    session = cast(Any, SimpleNamespace())

    with pytest.raises(ConflictError) as exc:
        await auth_service.register_user(
            session,
            RegisterRequest(
                nickname="@tester",
                password="supersecret123",
                email="tester@example.com",
                email_2fa_enabled=True,
            ),
        )

    assert exc.value.status_code == 409
    assert exc.value.code == "EMAIL_ALREADY_EXISTS"
    assert exc.value.message == "Email already exists"


@pytest.mark.asyncio
async def test_login_user_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_by_nickname(session: Any, nickname: str) -> Any:
        return None

    async def fake_create_login_attempt(session: Any, **kwargs: Any) -> Any:
        return None

    async def fake_commit() -> None:
        return None

    session = cast(Any, SimpleNamespace(commit=fake_commit))

    monkeypatch.setattr(
        auth_service.users_repo, "get_by_nickname", fake_get_by_nickname
    )
    monkeypatch.setattr(
        auth_service.auth_repo, "create_login_attempt", fake_create_login_attempt
    )

    with pytest.raises(UnauthorizedError) as exc:
        await auth_service.login_user(
            session,
            LoginRequest(nickname="@missing", password="badpass123"),
        )

    assert exc.value.status_code == 401
    assert exc.value.code == "INVALID_CREDENTIALS"


@pytest.mark.asyncio
async def test_login_user_pending_deletion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user(pending_deletion=True)

    async def fake_get_by_nickname(session: Any, nickname: str) -> Any:
        return user

    monkeypatch.setattr(
        auth_service.users_repo, "get_by_nickname", fake_get_by_nickname
    )

    session = cast(Any, SimpleNamespace())

    with pytest.raises(ForbiddenError) as exc:
        await auth_service.login_user(
            session,
            LoginRequest(nickname="@tester", password="supersecret123"),
        )

    assert exc.value.status_code == 403
    assert exc.value.code == "ACCOUNT_UNAVAILABLE"


@pytest.mark.asyncio
async def test_login_user_locked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user(lock_until=_now() + timedelta(hours=1))

    async def fake_get_by_nickname(session: Any, nickname: str) -> Any:
        return user

    monkeypatch.setattr(
        auth_service.users_repo, "get_by_nickname", fake_get_by_nickname
    )

    session = cast(Any, SimpleNamespace())

    with pytest.raises(LockedError) as exc:
        await auth_service.login_user(
            session,
            LoginRequest(nickname="@tester", password="supersecret123"),
        )

    assert exc.value.status_code == 423
    assert exc.value.code == "ACCOUNT_LOCKED"


@pytest.mark.asyncio
async def test_login_invalid_password_locks_account(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user(failed_login_stage=0)

    async def fake_get_by_nickname(session: Any, nickname: str) -> Any:
        return user

    async def fake_create_login_attempt(session: Any, **kwargs: Any) -> Any:
        return None

    async def fake_count_recent_failed_attempts(
        session: Any,
        user_id: int,
        since_dt: datetime,
    ) -> int:
        return 5

    async def fake_commit() -> None:
        return None

    monkeypatch.setattr(
        auth_service.users_repo, "get_by_nickname", fake_get_by_nickname
    )
    monkeypatch.setattr(
        auth_service.auth_repo, "create_login_attempt", fake_create_login_attempt
    )
    monkeypatch.setattr(
        auth_service.auth_repo,
        "count_recent_failed_attempts",
        fake_count_recent_failed_attempts,
    )
    monkeypatch.setattr(
        auth_service, "verify_password", lambda password, password_hash: False
    )

    session = cast(Any, SimpleNamespace(commit=fake_commit))

    with pytest.raises(LockedError) as exc:
        await auth_service.login_user(
            session,
            LoginRequest(nickname="@tester", password="wrongpassword"),
        )

    assert exc.value.status_code == 423
    assert exc.value.code == "ACCOUNT_LOCKED"
    assert user.lock_until is not None
    assert user.failed_login_stage == 1


@pytest.mark.asyncio
async def test_login_invalid_password_sets_pending_deletion_on_final_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user(failed_login_stage=3)

    async def fake_get_by_nickname(session: Any, nickname: str) -> Any:
        return user

    async def fake_create_login_attempt(session: Any, **kwargs: Any) -> Any:
        return None

    async def fake_count_recent_failed_attempts(
        session: Any,
        user_id: int,
        since_dt: datetime,
    ) -> int:
        return 5

    async def fake_commit() -> None:
        return None

    monkeypatch.setattr(
        auth_service.users_repo, "get_by_nickname", fake_get_by_nickname
    )
    monkeypatch.setattr(
        auth_service.auth_repo, "create_login_attempt", fake_create_login_attempt
    )
    monkeypatch.setattr(
        auth_service.auth_repo,
        "count_recent_failed_attempts",
        fake_count_recent_failed_attempts,
    )
    monkeypatch.setattr(
        auth_service, "verify_password", lambda password, password_hash: False
    )

    session = cast(Any, SimpleNamespace(commit=fake_commit))

    with pytest.raises(ForbiddenError) as exc:
        await auth_service.login_user(
            session,
            LoginRequest(nickname="@tester", password="wrongpassword"),
        )

    assert exc.value.status_code == 403
    assert exc.value.code == "ACCOUNT_PENDING_DELETION"
    assert user.pending_deletion is True
    assert user.is_frozen is True


@pytest.mark.asyncio
async def test_login_success_without_2fa(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user(failed_login_stage=2)

    async def fake_get_by_nickname(session: Any, nickname: str) -> Any:
        return user

    async def fake_create_login_attempt(session: Any, **kwargs: Any) -> Any:
        return None

    async def fake_commit() -> None:
        return None

    async def fake_resolve_device_for_auth(
        session: Any,
        *,
        user_id: int,
        nickname: str,
        device_uuid: str | None,
    ) -> tuple[Any, dict[str, Any] | None]:
        return SimpleNamespace(id=10), None

    monkeypatch.setattr(
        auth_service.users_repo, "get_by_nickname", fake_get_by_nickname
    )
    monkeypatch.setattr(
        auth_service.auth_repo, "create_login_attempt", fake_create_login_attempt
    )
    monkeypatch.setattr(
        auth_service, "_resolve_device_for_auth", fake_resolve_device_for_auth
    )
    monkeypatch.setattr(
        auth_service, "verify_password", lambda password, password_hash: True
    )
    monkeypatch.setattr(
        auth_service, "create_access_token", lambda subject, extra=None: "access"
    )
    monkeypatch.setattr(
        auth_service, "create_refresh_token", lambda subject, extra=None: "refresh"
    )

    async def fake_create_auth_session(*args, **kwargs) -> None:
        return None

    monkeypatch.setattr(
        auth_service.auth_sessions_repo,
        "create",
        fake_create_auth_session,
    )
    monkeypatch.setattr(auth_service, "hash_token", lambda token: "hashed-refresh")
    monkeypatch.setattr(auth_service, "uuid4", lambda: "session-uuid")

    session = cast(Any, SimpleNamespace(commit=fake_commit))

    result = await auth_service.login_user(
        session,
        LoginRequest(nickname="@tester", password="supersecret123"),
    )

    assert result["requires_email_code"] is False
    assert result["access_token"] == "access"
    assert result["refresh_token"] == "refresh"
    assert result["expires_in"] > 0
    assert user.lock_until is None
    assert user.failed_login_stage == 0


@pytest.mark.asyncio
async def test_login_with_google_2fa_requires_totp_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user(google_2fa_enabled=True, google_2fa_secret="SECRET")

    async def fake_get_by_nickname(session: Any, nickname: str) -> Any:
        return user

    async def fake_create_login_attempt(session: Any, **kwargs: Any) -> Any:
        return None

    async def fake_commit() -> None:
        return None

    monkeypatch.setattr(
        auth_service.users_repo, "get_by_nickname", fake_get_by_nickname
    )
    monkeypatch.setattr(
        auth_service.auth_repo, "create_login_attempt", fake_create_login_attempt
    )
    monkeypatch.setattr(
        auth_service, "verify_password", lambda password, password_hash: True
    )

    session = cast(Any, SimpleNamespace(commit=fake_commit))

    result = await auth_service.login_user(
        session,
        LoginRequest(nickname="@tester", password="supersecret123"),
    )

    assert result["requires_email_code"] is False
    assert result["requires_totp"] is True


@pytest.mark.asyncio
async def test_login_with_google_2fa_invalid_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user(google_2fa_enabled=True, google_2fa_secret="SECRET")

    async def fake_get_by_nickname(session: Any, nickname: str) -> Any:
        return user

    async def fake_create_login_attempt(session: Any, **kwargs: Any) -> Any:
        return None

    async def fake_commit() -> None:
        return None

    monkeypatch.setattr(
        auth_service.users_repo, "get_by_nickname", fake_get_by_nickname
    )
    monkeypatch.setattr(
        auth_service.auth_repo, "create_login_attempt", fake_create_login_attempt
    )
    monkeypatch.setattr(
        auth_service, "verify_password", lambda password, password_hash: True
    )
    monkeypatch.setattr(auth_service, "verify_totp_code", lambda secret, code: False)

    session = cast(Any, SimpleNamespace(commit=fake_commit))

    with pytest.raises(UnauthorizedError) as exc:
        await auth_service.login_user(
            session,
            LoginRequest(
                nickname="@tester",
                password="supersecret123",
                totp_code="123456",
            ),
        )

    assert exc.value.code == "INVALID_TOTP_CODE"


@pytest.mark.asyncio
async def test_login_success_with_2fa_returns_challenge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user(
        failed_login_stage=0,
        email_2fa_enabled=True,
        email="tester@example.com",
    )

    async def fake_get_by_nickname(session: Any, nickname: str) -> Any:
        return user

    async def fake_create_login_attempt(session: Any, **kwargs: Any) -> Any:
        return None

    async def fake_create_email_code(session: Any, **kwargs: Any) -> Any:
        return None

    async def fake_commit() -> None:
        return None

    async def fake_invalidate_active_email_codes(session: Any, user_id: int) -> int:
        return 0

    monkeypatch.setattr(
        auth_service.auth_repo,
        "invalidate_active_email_codes",
        fake_invalidate_active_email_codes,
    )

    monkeypatch.setattr(
        auth_service.users_repo, "get_by_nickname", fake_get_by_nickname
    )
    monkeypatch.setattr(
        auth_service.auth_repo, "create_login_attempt", fake_create_login_attempt
    )
    monkeypatch.setattr(
        auth_service.auth_repo, "create_email_code", fake_create_email_code
    )
    monkeypatch.setattr(
        auth_service, "verify_password", lambda password, password_hash: True
    )
    monkeypatch.setattr(auth_service, "_generate_email_code", lambda: "123456")
    sent_email: dict[str, str] = {}

    async def fake_send_login_code_email(
        *, recipient_email: str, recipient_nickname: str, code: str
    ) -> None:
        sent_email.update(
            {
                "recipient_email": recipient_email,
                "recipient_nickname": recipient_nickname,
                "code": code,
            }
        )

    monkeypatch.setattr(
        auth_service,
        "send_login_code_email",
        fake_send_login_code_email,
    )

    session = cast(Any, SimpleNamespace(commit=fake_commit))

    result = await auth_service.login_user(
        session,
        LoginRequest(nickname="@tester", password="supersecret123"),
    )

    assert result["requires_email_code"] is True
    assert "login_challenge_id" in result
    assert result["email_masked"] == "t***@example.com"
    assert "debug_code" not in result
    assert sent_email == {
        "recipient_email": "tester@example.com",
        "recipient_nickname": "@tester",
        "code": "123456",
    }


@pytest.mark.asyncio
async def test_login_success_with_2fa_returns_debug_code_when_explicitly_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user(
        failed_login_stage=0,
        email_2fa_enabled=True,
        email="tester@example.com",
    )

    async def fake_get_by_nickname(session: Any, nickname: str) -> Any:
        return user

    async def fake_create_login_attempt(session: Any, **kwargs: Any) -> Any:
        return None

    async def fake_create_email_code(session: Any, **kwargs: Any) -> Any:
        return None

    async def fake_commit() -> None:
        return None

    async def fake_invalidate_active_email_codes(session: Any, user_id: int) -> int:
        return 0

    monkeypatch.setattr(
        auth_service.auth_repo,
        "invalidate_active_email_codes",
        fake_invalidate_active_email_codes,
    )
    monkeypatch.setattr(
        auth_service.users_repo, "get_by_nickname", fake_get_by_nickname
    )
    monkeypatch.setattr(
        auth_service.auth_repo, "create_login_attempt", fake_create_login_attempt
    )
    monkeypatch.setattr(
        auth_service.auth_repo, "create_email_code", fake_create_email_code
    )
    monkeypatch.setattr(
        auth_service, "verify_password", lambda password, password_hash: True
    )
    monkeypatch.setattr(auth_service, "_generate_email_code", lambda: "123456")
    monkeypatch.setattr(settings, "allow_debug_email_codes", True)

    async def fake_send_login_code_email(
        *, recipient_email: str, recipient_nickname: str, code: str
    ) -> None:
        return None

    monkeypatch.setattr(
        auth_service,
        "send_login_code_email",
        fake_send_login_code_email,
    )

    session = cast(Any, SimpleNamespace(commit=fake_commit))

    result = await auth_service.login_user(
        session,
        LoginRequest(nickname="@tester", password="supersecret123"),
    )

    assert result["requires_email_code"] is True
    assert result["debug_code"] == "123456"


@pytest.mark.asyncio
async def test_login_email_2fa_send_failure_deletes_challenge(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user(
        failed_login_stage=0,
        email_2fa_enabled=True,
        email="tester@example.com",
    )
    deleted_challenge: dict[str, str] = {}
    commit_calls = 0

    async def fake_get_by_nickname(session: Any, nickname: str) -> Any:
        return user

    async def fake_create_login_attempt(session: Any, **kwargs: Any) -> Any:
        return None

    async def fake_create_email_code(session: Any, **kwargs: Any) -> Any:
        return None

    async def fake_invalidate_active_email_codes(session: Any, user_id: int) -> int:
        return 0

    async def fake_delete_email_code_by_challenge(
        session: Any, login_challenge_id: str
    ) -> bool:
        deleted_challenge["login_challenge_id"] = login_challenge_id
        return True

    async def fake_commit() -> None:
        nonlocal commit_calls
        commit_calls += 1

    async def fake_send_login_code_email(
        *, recipient_email: str, recipient_nickname: str, code: str
    ) -> None:
        raise ServiceUnavailableError(
            code="EMAIL_DELIVERY_FAILED",
            message="Could not deliver verification code",
        )

    monkeypatch.setattr(
        auth_service.auth_repo,
        "invalidate_active_email_codes",
        fake_invalidate_active_email_codes,
    )
    monkeypatch.setattr(
        auth_service.users_repo, "get_by_nickname", fake_get_by_nickname
    )
    monkeypatch.setattr(
        auth_service.auth_repo, "create_login_attempt", fake_create_login_attempt
    )
    monkeypatch.setattr(
        auth_service.auth_repo, "create_email_code", fake_create_email_code
    )
    monkeypatch.setattr(
        auth_service.auth_repo,
        "delete_email_code_by_challenge",
        fake_delete_email_code_by_challenge,
    )
    monkeypatch.setattr(
        auth_service, "verify_password", lambda password, password_hash: True
    )
    monkeypatch.setattr(auth_service, "_generate_email_code", lambda: "123456")
    monkeypatch.setattr(
        auth_service,
        "send_login_code_email",
        fake_send_login_code_email,
    )

    session = cast(Any, SimpleNamespace(commit=fake_commit))

    with pytest.raises(ServiceUnavailableError) as exc:
        await auth_service.login_user(
            session,
            LoginRequest(nickname="@tester", password="supersecret123"),
        )

    assert exc.value.code == "EMAIL_DELIVERY_FAILED"
    assert "login_challenge_id" in deleted_challenge
    assert commit_calls == 2


@pytest.mark.asyncio
async def test_verify_email_code_challenge_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_email_code_by_challenge(
        session: Any, login_challenge_id: str
    ) -> Any:
        return None

    monkeypatch.setattr(
        auth_service.auth_repo,
        "get_email_code_by_challenge",
        fake_get_email_code_by_challenge,
    )

    session = cast(Any, SimpleNamespace())

    with pytest.raises(NotFoundError) as exc:
        await auth_service.verify_email_code(
            session,
            VerifyEmailCodeRequest(
                login_challenge_id="challenge-id",
                code="123456",
            ),
        )

    assert exc.value.status_code == 404
    assert exc.value.code == "CHALLENGE_NOT_FOUND"


@pytest.mark.asyncio
async def test_verify_email_code_invalid_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = SimpleNamespace(
        user_id=1,
        consumed_at=None,
        expires_at=_now() + timedelta(minutes=10),
        code_hash="expected-hash",
        attempts=0,
    )

    async def fake_get_email_code_by_challenge(
        session: Any, login_challenge_id: str
    ) -> Any:
        return record

    async def fake_commit() -> None:
        return None

    monkeypatch.setattr(
        auth_service.auth_repo,
        "get_email_code_by_challenge",
        fake_get_email_code_by_challenge,
    )
    monkeypatch.setattr(
        auth_service, "_hash_email_code", lambda login_challenge_id, code: "wrong-hash"
    )

    session = cast(Any, SimpleNamespace(commit=fake_commit))

    with pytest.raises(BadRequestError) as exc:
        await auth_service.verify_email_code(
            session,
            VerifyEmailCodeRequest(
                login_challenge_id="challenge-id",
                code="654321",
            ),
        )

    assert exc.value.status_code == 400
    assert exc.value.code == "INVALID_EMAIL_CODE"
    assert record.attempts == 1


@pytest.mark.asyncio
async def test_begin_google_2fa_setup_returns_secret(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user()

    async def fake_get_by_id(session: Any, user_id: int) -> Any:
        return user

    async def fake_commit() -> None:
        return None

    monkeypatch.setattr(auth_service.users_repo, "get_by_id", fake_get_by_id)
    monkeypatch.setattr(auth_service, "generate_totp_secret", lambda: "SECRET")

    session = cast(Any, SimpleNamespace(commit=fake_commit))

    result = await auth_service.begin_google_2fa_setup(
        session,
        current_user=cast(Any, SimpleNamespace(id=1)),
    )

    assert result["secret"] == "SECRET"
    assert user.google_2fa_pending_secret == "SECRET"


@pytest.mark.asyncio
async def test_confirm_google_2fa_setup_invalid_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user(google_2fa_pending_secret="SECRET")

    async def fake_get_by_id(session: Any, user_id: int) -> Any:
        return user

    monkeypatch.setattr(auth_service.users_repo, "get_by_id", fake_get_by_id)
    monkeypatch.setattr(auth_service, "verify_totp_code", lambda secret, code: False)

    session = cast(Any, SimpleNamespace())

    with pytest.raises(BadRequestError) as exc:
        await auth_service.confirm_google_2fa_setup(
            session,
            current_user=cast(Any, SimpleNamespace(id=1)),
            payload=Google2FAConfirmRequest(code="123456"),
        )

    assert exc.value.code == "INVALID_TOTP_CODE"


@pytest.mark.asyncio
async def test_confirm_google_2fa_setup_enables_2fa(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user = make_user(google_2fa_pending_secret="SECRET")

    async def fake_get_by_id(session: Any, user_id: int) -> Any:
        return user

    async def fake_commit() -> None:
        return None

    monkeypatch.setattr(auth_service.users_repo, "get_by_id", fake_get_by_id)
    monkeypatch.setattr(auth_service, "verify_totp_code", lambda secret, code: True)

    session = cast(Any, SimpleNamespace(commit=fake_commit))

    result = await auth_service.confirm_google_2fa_setup(
        session,
        current_user=cast(Any, SimpleNamespace(id=1)),
        payload=Google2FAConfirmRequest(code="123456"),
    )

    assert result["enabled"] is True
    assert user.google_2fa_enabled is True
    assert user.google_2fa_secret == "SECRET"
    assert user.google_2fa_pending_secret is None


@pytest.mark.asyncio
async def test_refresh_access_token_invalid_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_decode_token(token: str) -> dict[str, Any]:
        raise ValueError("bad token")

    monkeypatch.setattr(auth_service, "decode_token", fake_decode_token)

    session = cast(Any, SimpleNamespace())

    with pytest.raises(UnauthorizedError) as exc:
        await auth_service.refresh_access_token(
            session,
            RefreshRequest(refresh_token="bad-token"),
        )

    assert exc.value.status_code == 401
    assert exc.value.code == "INVALID_REFRESH_TOKEN"


@pytest.mark.asyncio
async def test_refresh_access_token_wrong_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        auth_service,
        "decode_token",
        lambda token: {"sub": "1", "type": "access"},
    )

    session = cast(Any, SimpleNamespace())

    with pytest.raises(UnauthorizedError) as exc:
        await auth_service.refresh_access_token(
            session,
            RefreshRequest(refresh_token="not-refresh"),
        )

    assert exc.value.status_code == 401
    assert exc.value.code == "INVALID_TOKEN_TYPE"


@pytest.mark.asyncio
async def test_register_user_requires_email_for_2fa() -> None:
    session = cast(Any, SimpleNamespace())

    with pytest.raises(BadRequestError) as exc:
        await auth_service.register_user(
            session,
            RegisterRequest(
                nickname="@tester",
                password="supersecret123",
                email=None,
                email_2fa_enabled=True,
            ),
        )

    assert exc.value.status_code == 400
    assert exc.value.code == "EMAIL_REQUIRED_FOR_2FA"


@pytest.mark.asyncio
async def test_verify_email_code_locks_after_max_attempts(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = SimpleNamespace(
        user_id=1,
        consumed_at=None,
        expires_at=_now() + timedelta(minutes=10),
        code_hash="expected-hash",
        attempts=settings.email_code_max_attempts - 1,
    )

    async def fake_get_email_code_by_challenge(
        session: Any,
        login_challenge_id: str,
    ) -> Any:
        return record

    async def fake_commit() -> None:
        return None

    monkeypatch.setattr(
        auth_service.auth_repo,
        "get_email_code_by_challenge",
        fake_get_email_code_by_challenge,
    )
    monkeypatch.setattr(
        auth_service,
        "_hash_email_code",
        lambda login_challenge_id, code: "wrong-hash",
    )

    session = cast(Any, SimpleNamespace(commit=fake_commit))

    with pytest.raises(LockedError) as exc:
        await auth_service.verify_email_code(
            session,
            VerifyEmailCodeRequest(
                login_challenge_id="challenge-id",
                code="000000",
            ),
        )

    assert exc.value.status_code == 423
    assert exc.value.code == "EMAIL_CODE_ATTEMPTS_EXCEEDED"
    assert record.attempts == settings.email_code_max_attempts
    assert record.consumed_at is not None


@pytest.mark.asyncio
async def test_verify_email_code_exhausted_challenge_stays_locked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    record = SimpleNamespace(
        user_id=1,
        consumed_at=_now(),
        expires_at=_now() + timedelta(minutes=10),
        code_hash="expected-hash",
        attempts=settings.email_code_max_attempts,
    )

    async def fake_get_email_code_by_challenge(
        session: Any,
        login_challenge_id: str,
    ) -> Any:
        return record

    monkeypatch.setattr(
        auth_service.auth_repo,
        "get_email_code_by_challenge",
        fake_get_email_code_by_challenge,
    )

    session = cast(Any, SimpleNamespace())

    with pytest.raises(LockedError) as exc:
        await auth_service.verify_email_code(
            session,
            VerifyEmailCodeRequest(
                login_challenge_id="challenge-id",
                code="123456",
            ),
        )

    assert exc.value.status_code == 423
    assert exc.value.code == "EMAIL_CODE_ATTEMPTS_EXCEEDED"
