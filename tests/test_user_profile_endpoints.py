from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.dependencies.auth import get_current_user
from app.main import app


def _mock_user() -> Any:
    return SimpleNamespace(id=1, nickname="@tester")


def _profile_payload() -> dict[str, Any]:
    return {
        "user_id": 1,
        "public_id": "public-1",
        "nickname": "@tester",
        "full_name": "Test User",
        "bio": "Bio",
        "avatar_url": "https://example.com/avatar.png",
        "avatar_updated_at": datetime.now(timezone.utc),
        "created_at": datetime.now(timezone.utc),
        "settings": {
            "language_code": "ru",
            "theme": "system",
            "push_notifications_enabled": True,
            "apk_update_notifications_enabled": True,
            "google_2fa_enabled": False,
        },
    }


@pytest.fixture(autouse=True)
def override_current_user() -> None:
    async def _current_user_override() -> Any:
        return _mock_user()

    app.dependency_overrides[get_current_user] = _current_user_override
    yield
    app.dependency_overrides.clear()


def test_get_my_profile_endpoint(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_my_profile(session: Any, *, current_user: Any) -> dict[str, Any]:
        assert current_user.id == 1
        return _profile_payload()

    monkeypatch.setattr("app.api.v1.users.get_my_profile", fake_get_my_profile)

    response = client.get("/api/v1/users/me")

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["nickname"] == "@tester"
    assert body["data"]["settings"]["theme"] == "system"


def test_update_my_profile_endpoint(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_update_my_profile(
        session: Any,
        *,
        current_user: Any,
        payload: Any,
    ) -> dict[str, Any]:
        assert current_user.id == 1
        assert payload.full_name == "Updated User"
        data = _profile_payload()
        data["full_name"] = payload.full_name
        return data

    monkeypatch.setattr(
        "app.api.v1.users.update_my_profile",
        fake_update_my_profile,
    )

    response = client.patch(
        "/api/v1/users/me",
        json={"full_name": "Updated User", "theme": "dark"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["data"]["full_name"] == "Updated User"


def test_upload_avatar_endpoint(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_upload_my_avatar(
        session: Any,
        *,
        current_user: Any,
        file: Any,
    ) -> dict[str, Any]:
        assert current_user.id == 1
        assert file.filename == "avatar.png"
        return _profile_payload()

    monkeypatch.setattr("app.api.v1.users.upload_my_avatar", fake_upload_my_avatar)

    response = client.post(
        "/api/v1/users/me/avatar",
        files={"file": ("avatar.png", b"image-bytes", "image/png")},
    )

    assert response.status_code == 200
    assert response.json()["data"]["avatar_url"] == "https://example.com/avatar.png"
