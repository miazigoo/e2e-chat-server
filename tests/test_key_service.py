from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import HTTPException

import app.services.key_service as key_service
from app.core.exceptions import BadRequestError, ConflictError, NotFoundError
from app.schemas.keys import RefillPreKeysRequest, RotateSignedPreKeyRequest


@pytest.mark.asyncio
async def test_get_key_bundle_for_user_success_with_prekey(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_by_id(session: Any, user_id: int) -> Any:
        return SimpleNamespace(
            id=user_id,
            is_deleted=False,
            pending_deletion=False,
        )

    async def fake_get_active_by_user_id(session: Any, user_id: int) -> Any:
        return SimpleNamespace(
            id=22,
            prekeys_count=50,
            registration_id=7001,
            public_identity_key="identity",
            public_signing_key="signing",
            signed_prekey_id=51,
            signed_prekey="signed",
            signed_prekey_signature="signature",
        )

    async def fake_claim_one_time_prekey(session: Any, device_id: int) -> Any:
        return SimpleNamespace(prekey_id=101, public_prekey="otp-101")

    async def fake_count_available_prekeys(session: Any, device_id: int) -> int:
        return 49

    async def fake_commit() -> None:
        return None

    session = SimpleNamespace(commit=fake_commit)

    monkeypatch.setattr(key_service.users_repo, "get_by_id", fake_get_by_id)
    monkeypatch.setattr(
        key_service.devices_repo,
        "get_active_by_user_id",
        fake_get_active_by_user_id,
    )
    monkeypatch.setattr(
        key_service.keys_repo,
        "claim_one_time_prekey",
        fake_claim_one_time_prekey,
    )
    monkeypatch.setattr(
        key_service.keys_repo,
        "count_available_prekeys",
        fake_count_available_prekeys,
    )

    result = await key_service.get_key_bundle_for_user(
        cast(Any, session),
        current_user=cast(Any, SimpleNamespace(id=1)),
        current_device=cast(Any, SimpleNamespace(id=10)),
        target_user_id=2,
    )

    assert result["user_id"] == 2
    assert result["device_id"] == 22
    assert result["requested_by_device_id"] == 10
    assert result["registration_id"] == 7001
    assert result["signed_prekey_id"] == 51
    assert result["one_time_prekey"]["prekey_id"] == 101
    assert result["prekeys_remaining"] == 49


@pytest.mark.asyncio
async def test_get_key_bundle_for_user_success_without_prekey(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_by_id(session: Any, user_id: int) -> Any:
        return SimpleNamespace(
            id=user_id,
            is_deleted=False,
            pending_deletion=False,
        )

    async def fake_get_active_by_user_id(session: Any, user_id: int) -> Any:
        return SimpleNamespace(
            id=22,
            prekeys_count=0,
            registration_id=7002,
            public_identity_key="identity",
            public_signing_key="signing",
            signed_prekey_id=52,
            signed_prekey="signed",
            signed_prekey_signature="signature",
        )

    async def fake_claim_one_time_prekey(session: Any, device_id: int) -> Any:
        return None

    async def fake_count_available_prekeys(session: Any, device_id: int) -> int:
        return 0

    async def fake_commit() -> None:
        return None

    session = SimpleNamespace(commit=fake_commit)

    monkeypatch.setattr(key_service.users_repo, "get_by_id", fake_get_by_id)
    monkeypatch.setattr(
        key_service.devices_repo,
        "get_active_by_user_id",
        fake_get_active_by_user_id,
    )
    monkeypatch.setattr(
        key_service.keys_repo,
        "claim_one_time_prekey",
        fake_claim_one_time_prekey,
    )
    monkeypatch.setattr(
        key_service.keys_repo,
        "count_available_prekeys",
        fake_count_available_prekeys,
    )

    result = await key_service.get_key_bundle_for_user(
        cast(Any, session),
        current_user=cast(Any, SimpleNamespace(id=1)),
        current_device=cast(Any, SimpleNamespace(id=10)),
        target_user_id=2,
    )

    assert result["one_time_prekey"] is None
    assert result["prekeys_remaining"] == 0


@pytest.mark.asyncio
async def test_get_key_bundle_for_user_rejects_self() -> None:
    session = cast(Any, SimpleNamespace())

    with pytest.raises(BadRequestError) as exc:
        await key_service.get_key_bundle_for_user(
            session,
            current_user=cast(Any, SimpleNamespace(id=1)),
            current_device=cast(Any, SimpleNamespace(id=10)),
            target_user_id=1,
        )

    assert exc.value.status_code == 400
    assert exc.value.code == "SELF_BUNDLE_REQUEST_NOT_ALLOWED"


@pytest.mark.asyncio
async def test_get_key_bundle_for_user_target_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_by_id(session: Any, user_id: int) -> Any:
        return None

    monkeypatch.setattr(key_service.users_repo, "get_by_id", fake_get_by_id)

    session = cast(Any, SimpleNamespace())

    with pytest.raises(NotFoundError) as exc:
        await key_service.get_key_bundle_for_user(
            session,
            current_user=cast(Any, SimpleNamespace(id=1)),
            current_device=cast(Any, SimpleNamespace(id=10)),
            target_user_id=2,
        )

    assert exc.value.status_code == 404
    assert exc.value.code == "TARGET_USER_NOT_FOUND"


@pytest.mark.asyncio
async def test_get_key_bundle_for_user_no_active_device(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_by_id(session: Any, user_id: int) -> Any:
        return SimpleNamespace(
            id=user_id,
            is_deleted=False,
            pending_deletion=False,
        )

    async def fake_get_active_by_user_id(session: Any, user_id: int) -> Any:
        return None

    monkeypatch.setattr(key_service.users_repo, "get_by_id", fake_get_by_id)
    monkeypatch.setattr(
        key_service.devices_repo,
        "get_active_by_user_id",
        fake_get_active_by_user_id,
    )

    session = cast(Any, SimpleNamespace())

    with pytest.raises(ConflictError) as exc:
        await key_service.get_key_bundle_for_user(
            session,
            current_user=cast(Any, SimpleNamespace(id=1)),
            current_device=cast(Any, SimpleNamespace(id=10)),
            target_user_id=2,
        )

    assert exc.value.status_code == 409
    assert exc.value.code == "TARGET_DEVICE_NOT_READY"


@pytest.mark.asyncio
async def test_refill_prekeys_deduplicates_ids(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, Any] = {}

    async def fake_add_prekeys(
        session: Any,
        device_id: int,
        prekeys: list[dict[str, str | int]],
    ) -> int:
        captured["prekeys"] = prekeys
        return len(prekeys)

    async def fake_count_available_prekeys(session: Any, device_id: int) -> int:
        return 2

    async def fake_commit() -> None:
        return None

    session = SimpleNamespace(commit=fake_commit)
    current_device = SimpleNamespace(id=10, prekeys_count=0)

    monkeypatch.setattr(key_service.keys_repo, "add_prekeys", fake_add_prekeys)
    monkeypatch.setattr(
        key_service.keys_repo,
        "count_available_prekeys",
        fake_count_available_prekeys,
    )

    payload = RefillPreKeysRequest(
        prekeys=[
            {"prekey_id": 1, "public_prekey": "pk1"},
            {"prekey_id": 1, "public_prekey": "pk1-dup"},
            {"prekey_id": 2, "public_prekey": "pk2"},
        ]
    )

    result = await key_service.refill_prekeys(
        cast(Any, session),
        current_device=cast(Any, current_device),
        payload=payload,
    )

    assert result["added"] == 2
    assert result["prekeys_count"] == 2
    assert len(captured["prekeys"]) == 2


@pytest.mark.asyncio
async def test_rotate_signed_prekey_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_rotate_signed_prekey(
        session: Any,
        device: Any,
        signed_prekey_id: int,
        signed_prekey: str,
        signed_prekey_signature: str,
    ) -> Any:
        device.signed_prekey_id = signed_prekey_id
        device.signed_prekey = signed_prekey
        device.signed_prekey_signature = signed_prekey_signature
        return device

    async def fake_commit() -> None:
        return None

    session = SimpleNamespace(commit=fake_commit)
    current_device = SimpleNamespace(id=10)

    monkeypatch.setattr(
        key_service.keys_repo,
        "rotate_signed_prekey",
        fake_rotate_signed_prekey,
    )

    result = await key_service.rotate_signed_prekey(
        cast(Any, session),
        current_device=cast(Any, current_device),
        payload=RotateSignedPreKeyRequest(
            signed_prekey_id=9,
            signed_prekey="new-spk",
            signed_prekey_signature="new-sig",
        ),
    )

    assert result["device_id"] == 10
    assert result["rotated"] is True
