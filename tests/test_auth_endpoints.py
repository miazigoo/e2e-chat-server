from typing import Any

import pytest
from fastapi.testclient import TestClient


def test_register_endpoint(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_register_user(session: Any, payload: Any) -> dict[str, Any]:
        return {
            "user_id": 1,
            "nickname": payload.nickname,
            "requires_device_registration": False,
        }

    monkeypatch.setattr("app.api.v1.auth.register_user", fake_register_user)

    response = client.post(
        "/api/v1/auth/register",
        json={
            "nickname": "@tester",
            "password": "supersecret123",
            "email": "tester@example.com",
            "email_2fa_enabled": True,
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["nickname"] == "@tester"


def test_register_validation_error(client: TestClient) -> None:
    response = client.post(
        "/api/v1/auth/register",
        json={
            "nickname": "@te",
            "password": "123",
        },
    )

    assert response.status_code == 422
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "VALIDATION_ERROR"


def test_login_endpoint(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_login_user(
        session: Any,
        payload: Any,
        ip_address: str | None = None,
        device_fingerprint: str | None = None,
        user_agent: str | None = None,
    ) -> dict[str, Any]:
        return {
            "requires_email_code": False,
            "requires_totp": False,
            "access_token": "access",
            "refresh_token": "refresh",
            "expires_in": 900,
        }

    monkeypatch.setattr("app.api.v1.auth.login_user", fake_login_user)

    response = client.post(
        "/api/v1/auth/login",
        json={
            "nickname": "@tester",
            "password": "supersecret123",
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["access_token"] == "access"


def test_begin_google_2fa_setup_endpoint(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_begin_google_2fa_setup(
        session: Any, *, current_user: Any
    ) -> dict[str, Any]:
        assert current_user.id == 1
        return {
            "secret": "BASE32SECRET",
            "issuer": "secure-chat-backend",
            "account_name": "@tester",
            "provisioning_uri": "otpauth://totp/test",
        }

    async def current_user_override() -> Any:
        return type("User", (), {"id": 1, "nickname": "@tester"})()

    monkeypatch.setattr(
        "app.api.v1.auth.begin_google_2fa_setup",
        fake_begin_google_2fa_setup,
    )
    from app.dependencies.auth import get_current_user
    from app.main import app

    app.dependency_overrides[get_current_user] = current_user_override
    try:
        response = client.post("/api/v1/auth/2fa/google/setup")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["data"]["secret"] == "BASE32SECRET"


def test_get_google_2fa_qr_endpoint(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_google_2fa_qr_png(session: Any, *, current_user: Any) -> bytes:
        assert current_user.id == 1
        return b"\x89PNG\r\n\x1a\nfake"

    async def current_user_override() -> Any:
        return type("User", (), {"id": 1, "nickname": "@tester"})()

    monkeypatch.setattr(
        "app.api.v1.auth.get_google_2fa_qr_png",
        fake_get_google_2fa_qr_png,
    )
    from app.dependencies.auth import get_current_user
    from app.main import app

    app.dependency_overrides[get_current_user] = current_user_override
    try:
        response = client.get("/api/v1/auth/2fa/google/qr")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.content.startswith(b"\x89PNG")
