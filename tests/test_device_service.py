from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import HTTPException

import app.services.device_service as device_service
from app.core.exceptions import BadRequestError
from app.schemas.devices import BootstrapDeviceRequest


@pytest.mark.asyncio
async def test_bootstrap_device_rejects_non_android() -> None:
    session = cast(Any, SimpleNamespace())

    with pytest.raises(BadRequestError) as exc:
        await device_service.bootstrap_device(
            session,
            current_user=cast(Any, SimpleNamespace(id=1)),
            payload=BootstrapDeviceRequest(
                device_uuid="device-1",
                device_name="iPhone",
                platform="ios",
                app_version="1.0.0",
                registration_id=101,
                public_identity_key="identity",
                public_signing_key="signing",
                signed_prekey_id=1,
                signed_prekey="signed",
                signed_prekey_signature="signature",
                one_time_prekeys=[],
            ),
        )

    assert exc.value.status_code == 400
    assert exc.value.code == "UNSUPPORTED_PLATFORM"


@pytest.mark.asyncio
async def test_bootstrap_device_deduplicates_prekeys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_get_by_user_and_uuid(
        session: Any, user_id: int, device_uuid: str
    ) -> Any:
        return None

    async def fake_deactivate_other_devices(
        session: Any, user_id: int, keep_device_id: int | None
    ) -> None:
        return None

    async def fake_create_or_update_device(session: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(
            id=10,
            device_uuid=kwargs["device_uuid"],
            is_active=True,
            prekeys_count=0,
        )

    async def fake_replace_prekeys(
        session: Any, device_id: int, prekeys: list[dict[str, Any]]
    ) -> int:
        captured["prekeys"] = prekeys
        return len(prekeys)

    async def fake_commit() -> None:
        return None

    monkeypatch.setattr(
        device_service.devices_repo, "get_by_user_and_uuid", fake_get_by_user_and_uuid
    )
    monkeypatch.setattr(
        device_service.devices_repo,
        "deactivate_other_devices",
        fake_deactivate_other_devices,
    )
    monkeypatch.setattr(
        device_service.devices_repo,
        "create_or_update_device",
        fake_create_or_update_device,
    )
    monkeypatch.setattr(
        device_service.devices_repo, "replace_prekeys", fake_replace_prekeys
    )

    session = cast(Any, SimpleNamespace(commit=fake_commit))

    payload = BootstrapDeviceRequest(
        device_uuid="device-1",
        device_name="Pixel 8",
        platform="android",
        app_version="1.0.0",
        registration_id=101,
        public_identity_key="identity",
        public_signing_key="signing",
        signed_prekey_id=1,
        signed_prekey="signed",
        signed_prekey_signature="signature",
        one_time_prekeys=[
            {"prekey_id": 1, "public_prekey": "pk1"},
            {"prekey_id": 1, "public_prekey": "pk1-dup"},
            {"prekey_id": 2, "public_prekey": "pk2"},
        ],
    )

    result = await device_service.bootstrap_device(
        session,
        current_user=cast(Any, SimpleNamespace(id=1)),
        payload=payload,
    )

    assert result["prekeys_count"] == 2
    assert len(captured["prekeys"]) == 2


@pytest.mark.asyncio
async def test_bootstrap_device_updates_existing_device(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    existing_device = SimpleNamespace(
        id=10,
        device_uuid="device-1",
        is_active=True,
        prekeys_count=0,
    )

    async def fake_get_by_user_and_uuid(
        session: Any, user_id: int, device_uuid: str
    ) -> Any:
        return existing_device

    async def fake_deactivate_other_devices(
        session: Any, user_id: int, keep_device_id: int | None
    ) -> None:
        return None

    async def fake_create_or_update_device(session: Any, **kwargs: Any) -> Any:
        return existing_device

    async def fake_replace_prekeys(
        session: Any, device_id: int, prekeys: list[dict[str, Any]]
    ) -> int:
        return 0

    async def fake_commit() -> None:
        return None

    monkeypatch.setattr(
        device_service.devices_repo, "get_by_user_and_uuid", fake_get_by_user_and_uuid
    )
    monkeypatch.setattr(
        device_service.devices_repo,
        "deactivate_other_devices",
        fake_deactivate_other_devices,
    )
    monkeypatch.setattr(
        device_service.devices_repo,
        "create_or_update_device",
        fake_create_or_update_device,
    )
    monkeypatch.setattr(
        device_service.devices_repo, "replace_prekeys", fake_replace_prekeys
    )

    session = cast(Any, SimpleNamespace(commit=fake_commit))

    result = await device_service.bootstrap_device(
        session,
        current_user=cast(Any, SimpleNamespace(id=1)),
        payload=BootstrapDeviceRequest(
            device_uuid="device-1",
            device_name="Pixel 8 Updated",
            platform="android",
            app_version="2.0.0",
            registration_id=202,
            public_identity_key="identity-new",
            public_signing_key="signing-new",
            signed_prekey_id=2,
            signed_prekey="signed-new",
            signed_prekey_signature="signature-new",
            one_time_prekeys=[],
        ),
    )

    assert result["device_id"] == 10
    assert result["device_uuid"] == "device-1"
