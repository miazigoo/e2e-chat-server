from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.dependencies.auth import get_bootstrap_user
from app.main import app


async def override_bootstrap_user() -> Any:
    return SimpleNamespace(
        id=1,
        nickname="@tester",
        is_deleted=False,
        pending_deletion=False,
        is_active=True,
        is_frozen=False,
    )


def test_bootstrap_endpoint(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_bootstrap_device(
        session: Any,
        current_user: Any,
        payload: Any,
    ) -> dict[str, Any]:
        return {
            "device_id": 10,
            "device_uuid": payload.device_uuid,
            "is_active": True,
            "prekeys_count": len(payload.one_time_prekeys),
        }

    app.dependency_overrides[get_bootstrap_user] = override_bootstrap_user
    monkeypatch.setattr("app.api.v1.auth.bootstrap_device", fake_bootstrap_device)

    response = client.post(
        "/api/v1/auth/bootstrap",
        headers={
            "Authorization": "Bearer bootstrap-token",
            "X-Device-UUID": "device-uuid-1",
        },
        json={
            "device_uuid": "device-uuid-1",
            "device_name": "Pixel 8",
            "platform": "android",
            "app_version": "1.0.0",
            "fcm_token": "fcm-token",
            "public_identity_key": "identity-key",
            "public_signing_key": "signing-key",
            "signed_prekey": "signed-prekey",
            "signed_prekey_signature": "signature",
            "one_time_prekeys": [
                {"prekey_id": 1, "public_prekey": "prekey1"},
                {"prekey_id": 2, "public_prekey": "prekey2"},
            ],
        },
    )

    app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["ok"] is True
    assert body["data"]["device_id"] == 10
    assert body["data"]["prekeys_count"] == 2
