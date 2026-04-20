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
