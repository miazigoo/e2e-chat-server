from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.dependencies.auth import get_current_user
from app.dependencies.device import get_current_device
from app.main import app


async def override_current_user() -> Any:
    return SimpleNamespace(
        id=1,
        is_deleted=False,
        pending_deletion=False,
        is_active=True,
        is_frozen=False,
    )


async def override_current_device() -> Any:
    return SimpleNamespace(
        id=10,
        user_id=1,
        device_uuid="device-uuid-1",
        is_active=True,
        revoked_at=None,
    )


def test_get_key_bundle_success(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_key_bundle_for_user(
        session: Any,
        current_user: Any,
        current_device: Any,
        target_user_id: int,
    ) -> dict[str, Any]:
        return {
            "user_id": target_user_id,
            "device_id": 22,
            "requested_by_device_id": current_device.id,
            "public_identity_key": "identity-key",
            "public_signing_key": "signing-key",
            "signed_prekey": "signed-prekey",
            "signed_prekey_signature": "signature",
            "one_time_prekey": {
                "prekey_id": 100,
                "public_prekey": "otp-key",
            },
            "prekeys_remaining": 49,
        }

    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_current_device] = override_current_device
    monkeypatch.setattr(
        "app.api.v1.keys.get_key_bundle_for_user",
        fake_get_key_bundle_for_user,
    )

    response = client.get(
        "/api/v1/keys/bundle/2",
        headers={
            "Authorization": "Bearer token",
            "X-Device-UUID": "device-uuid-1",
        },
    )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["user_id"] == 2
    assert body["data"]["device_id"] == 22
    assert body["data"]["one_time_prekey"]["prekey_id"] == 100


def test_get_key_bundle_not_found(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_key_bundle_for_user(
        session: Any,
        current_user: Any,
        current_device: Any,
        target_user_id: int,
    ) -> dict[str, Any]:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "TARGET_USER_NOT_FOUND",
                "message": "Target user not found",
            },
        )

    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_current_device] = override_current_device
    monkeypatch.setattr(
        "app.api.v1.keys.get_key_bundle_for_user",
        fake_get_key_bundle_for_user,
    )

    response = client.get(
        "/api/v1/keys/bundle/999",
        headers={
            "Authorization": "Bearer token",
            "X-Device-UUID": "device-uuid-1",
        },
    )

    app.dependency_overrides.clear()

    assert response.status_code == 404
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "TARGET_USER_NOT_FOUND"
    assert body["error"]["message"] == "Target user not found"


def test_get_key_bundle_requires_auth(client: TestClient) -> None:
    response = client.get("/api/v1/keys/bundle/2")
    assert response.status_code == 401


def test_refill_prekeys_success(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_refill_prekeys(
        session: Any,
        current_device: Any,
        payload: Any,
    ) -> dict[str, Any]:
        return {
            "device_id": current_device.id,
            "added": len(payload.prekeys),
            "prekeys_count": len(payload.prekeys),
        }

    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_current_device] = override_current_device
    monkeypatch.setattr("app.api.v1.keys.refill_prekeys", fake_refill_prekeys)

    response = client.post(
        "/api/v1/keys/prekeys/refill",
        headers={
            "Authorization": "Bearer token",
            "X-Device-UUID": "device-uuid-1",
        },
        json={
            "prekeys": [
                {"prekey_id": 1, "public_prekey": "pk1"},
                {"prekey_id": 2, "public_prekey": "pk2"},
            ]
        },
    )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["added"] == 2
    assert body["data"]["prekeys_count"] == 2


def test_refill_prekeys_validation_error_empty_list(client: TestClient) -> None:
    response = client.post(
        "/api/v1/keys/prekeys/refill",
        json={"prekeys": []},
    )
    assert response.status_code == 401


def test_rotate_signed_prekey_success(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_rotate_signed_prekey(
        session: Any,
        current_device: Any,
        payload: Any,
    ) -> dict[str, Any]:
        return {
            "device_id": current_device.id,
            "rotated": True,
        }

    app.dependency_overrides[get_current_user] = override_current_user
    app.dependency_overrides[get_current_device] = override_current_device
    monkeypatch.setattr(
        "app.api.v1.keys.rotate_signed_prekey",
        fake_rotate_signed_prekey,
    )

    response = client.post(
        "/api/v1/keys/signed-prekey/rotate",
        headers={
            "Authorization": "Bearer token",
            "X-Device-UUID": "device-uuid-1",
        },
        json={
            "signed_prekey": "new-signed-prekey",
            "signed_prekey_signature": "new-signature",
        },
    )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["rotated"] is True


def test_rotate_signed_prekey_validation_error(client: TestClient) -> None:
    response = client.post(
        "/api/v1/keys/signed-prekey/rotate",
        headers={
            "Authorization": "Bearer token",
            "X-Device-UUID": "device-uuid-1",
        },
        json={
            "signed_prekey": "",
            "signed_prekey_signature": "",
        },
    )
    assert response.status_code in (401, 422)
