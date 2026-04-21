from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest

import app.services.message_service as message_service
from app.core.exceptions import BadRequestError, ConflictError, GoneError, NotFoundError
from app.schemas.messages import MarkReadRequest, SendMessageRequest


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _conversation(**overrides: Any) -> SimpleNamespace:
    base = {
        "id": 1,
        "user_a_id": 1,
        "user_b_id": 2,
        "is_purged": False,
        "is_active": True,
        "message_ttl_days": 60,
        "delete_after_read_seconds": None,
        "protection_mode": "normal",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _device(**overrides: Any) -> SimpleNamespace:
    base = {
        "id": 10,
        "user_id": 1,
        "device_uuid": "device-uuid-1",
        "is_active": True,
        "revoked_at": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


@pytest.mark.asyncio
async def test_send_message_conversation_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_for_user(
        session: Any,
        conversation_id: int,
        user_id: int,
    ) -> Any:
        return None

    monkeypatch.setattr(
        message_service.conversations_repo,
        "get_for_user",
        fake_get_for_user,
    )

    session = cast(Any, SimpleNamespace())

    with pytest.raises(NotFoundError) as exc:
        await message_service.send_message(
            session,
            current_user=cast(Any, SimpleNamespace(id=1)),
            current_device=cast(Any, _device()),
            payload=SendMessageRequest(
                conversation_id=1,
                recipient_user_id=2,
                message_uuid=str(uuid4()),
                message_type="text",
                ciphertext="cipher",
                ciphertext_version=1,
                encryption_mode="signal",
                nonce="nonce",
                client_created_at=_now(),
            ),
        )

    assert exc.value.status_code == 404
    assert exc.value.code == "CONVERSATION_NOT_FOUND"


@pytest.mark.asyncio
async def test_send_message_invalid_recipient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation = _conversation()

    async def fake_get_for_user(
        session: Any,
        conversation_id: int,
        user_id: int,
    ) -> Any:
        return conversation

    monkeypatch.setattr(
        message_service.conversations_repo,
        "get_for_user",
        fake_get_for_user,
    )

    session = cast(Any, SimpleNamespace())

    with pytest.raises(BadRequestError) as exc:
        await message_service.send_message(
            session,
            current_user=cast(Any, SimpleNamespace(id=1)),
            current_device=cast(Any, _device()),
            payload=SendMessageRequest(
                conversation_id=1,
                recipient_user_id=999,
                message_uuid=str(uuid4()),
                message_type="text",
                ciphertext="cipher",
                ciphertext_version=1,
                encryption_mode="signal",
                nonce="nonce",
                client_created_at=_now(),
            ),
        )

    assert exc.value.status_code == 400
    assert exc.value.code == "INVALID_RECIPIENT"


@pytest.mark.asyncio
async def test_send_message_to_purged_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation = _conversation(is_purged=True)

    async def fake_get_for_user(
        session: Any,
        conversation_id: int,
        user_id: int,
    ) -> Any:
        return conversation

    monkeypatch.setattr(
        message_service.conversations_repo,
        "get_for_user",
        fake_get_for_user,
    )

    session = cast(Any, SimpleNamespace())

    with pytest.raises(GoneError) as exc:
        await message_service.send_message(
            session,
            current_user=cast(Any, SimpleNamespace(id=1)),
            current_device=cast(Any, _device()),
            payload=SendMessageRequest(
                conversation_id=1,
                recipient_user_id=2,
                message_uuid=str(uuid4()),
                message_type="text",
                ciphertext="cipher",
                ciphertext_version=1,
                encryption_mode="signal",
                nonce="nonce",
                client_created_at=_now(),
            ),
        )

    assert exc.value.status_code == 410
    assert exc.value.code == "CONVERSATION_PURGED"


@pytest.mark.asyncio
async def test_send_message_when_recipient_has_no_device(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation = _conversation()

    async def fake_get_for_user(
        session: Any,
        conversation_id: int,
        user_id: int,
    ) -> Any:
        return conversation

    async def fake_get_active_by_user_id(session: Any, user_id: int) -> Any:
        return None

    monkeypatch.setattr(
        message_service.conversations_repo,
        "get_for_user",
        fake_get_for_user,
    )
    monkeypatch.setattr(
        message_service.devices_repo,
        "get_active_by_user_id",
        fake_get_active_by_user_id,
    )

    session = cast(Any, SimpleNamespace())

    with pytest.raises(ConflictError) as exc:
        await message_service.send_message(
            session,
            current_user=cast(Any, SimpleNamespace(id=1)),
            current_device=cast(Any, _device()),
            payload=SendMessageRequest(
                conversation_id=1,
                recipient_user_id=2,
                message_uuid=str(uuid4()),
                message_type="text",
                ciphertext="cipher",
                ciphertext_version=1,
                encryption_mode="signal",
                nonce="nonce",
                client_created_at=_now(),
            ),
        )

    assert exc.value.status_code == 409
    assert exc.value.code == "RECIPIENT_DEVICE_NOT_READY"


@pytest.mark.asyncio
async def test_mark_read_message_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_message_for_recipient(
        session: Any,
        message_id: int,
        user_id: int,
        recipient_device_id: int,
    ) -> Any:
        return None

    monkeypatch.setattr(
        message_service.messages_repo,
        "get_message_for_recipient",
        fake_get_message_for_recipient,
    )

    session = cast(Any, SimpleNamespace())

    with pytest.raises(NotFoundError) as exc:
        await message_service.mark_read(
            session,
            current_user=cast(Any, SimpleNamespace(id=2)),
            current_device=cast(
                Any,
                _device(id=20, user_id=2, device_uuid="device-uuid-2"),
            ),
            message_id=1,
            payload=MarkReadRequest(),
        )

    assert exc.value.status_code == 404
    assert exc.value.code == "MESSAGE_NOT_FOUND"


@pytest.mark.asyncio
async def test_send_message_rejects_client_service_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation = _conversation(protection_mode="normal")

    async def fake_get_for_user(
        session: Any,
        conversation_id: int,
        user_id: int,
    ) -> Any:
        return conversation

    monkeypatch.setattr(
        message_service.conversations_repo,
        "get_for_user",
        fake_get_for_user,
    )

    session = cast(Any, SimpleNamespace())

    with pytest.raises(BadRequestError) as exc:
        await message_service.send_message(
            session,
            current_user=cast(Any, SimpleNamespace(id=1)),
            current_device=cast(Any, _device()),
            payload=SendMessageRequest(
                conversation_id=1,
                recipient_user_id=2,
                message_uuid="11111111-1111-1111-1111-111111111111",
                message_type="service",
                ciphertext="cipher",
                ciphertext_version=1,
                encryption_mode="signal",
                nonce="nonce",
                client_created_at=_now(),
            ),
        )

    assert exc.value.status_code == 400
    assert exc.value.code == "CLIENT_MESSAGE_TYPE_NOT_ALLOWED"


@pytest.mark.asyncio
async def test_send_message_file_requires_attachments(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation = _conversation(protection_mode="normal")

    async def fake_get_for_user(
        session: Any,
        conversation_id: int,
        user_id: int,
    ) -> Any:
        return conversation

    monkeypatch.setattr(
        message_service.conversations_repo,
        "get_for_user",
        fake_get_for_user,
    )

    session = cast(Any, SimpleNamespace())

    with pytest.raises(BadRequestError) as exc:
        await message_service.send_message(
            session,
            current_user=cast(Any, SimpleNamespace(id=1)),
            current_device=cast(Any, _device()),
            payload=SendMessageRequest(
                conversation_id=1,
                recipient_user_id=2,
                message_uuid="22222222-2222-2222-2222-222222222222",
                message_type="file",
                ciphertext="cipher",
                ciphertext_version=1,
                encryption_mode="signal",
                nonce="nonce",
                client_created_at=_now(),
                attachment_ids=[],
            ),
        )

    assert exc.value.status_code == 400
    assert exc.value.code == "FILE_MESSAGE_REQUIRES_ATTACHMENTS"


@pytest.mark.asyncio
async def test_send_message_rejects_encryption_mode_mismatch_for_normal_chat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation = _conversation(protection_mode="normal")

    async def fake_get_for_user(
        session: Any,
        conversation_id: int,
        user_id: int,
    ) -> Any:
        return conversation

    monkeypatch.setattr(
        message_service.conversations_repo,
        "get_for_user",
        fake_get_for_user,
    )

    session = cast(Any, SimpleNamespace())

    with pytest.raises(BadRequestError) as exc:
        await message_service.send_message(
            session,
            current_user=cast(Any, SimpleNamespace(id=1)),
            current_device=cast(Any, _device()),
            payload=SendMessageRequest(
                conversation_id=1,
                recipient_user_id=2,
                message_uuid="33333333-3333-3333-3333-333333333333",
                message_type="text",
                ciphertext="cipher",
                ciphertext_version=1,
                encryption_mode="signal_plus_shared_secret",
                nonce="nonce",
                client_created_at=_now(),
            ),
        )

    assert exc.value.status_code == 400
    assert exc.value.code == "INVALID_ENCRYPTION_MODE"


@pytest.mark.asyncio
async def test_send_message_rejects_encryption_mode_mismatch_for_shared_secret_chat(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation = _conversation(protection_mode="shared_secret")

    async def fake_get_for_user(
        session: Any,
        conversation_id: int,
        user_id: int,
    ) -> Any:
        return conversation

    monkeypatch.setattr(
        message_service.conversations_repo,
        "get_for_user",
        fake_get_for_user,
    )

    session = cast(Any, SimpleNamespace())

    with pytest.raises(BadRequestError) as exc:
        await message_service.send_message(
            session,
            current_user=cast(Any, SimpleNamespace(id=1)),
            current_device=cast(Any, _device()),
            payload=SendMessageRequest(
                conversation_id=1,
                recipient_user_id=2,
                message_uuid="44444444-4444-4444-4444-444444444444",
                message_type="text",
                ciphertext="cipher",
                ciphertext_version=1,
                encryption_mode="signal",
                nonce="nonce",
                client_created_at=_now(),
            ),
        )

    assert exc.value.status_code == 400
    assert exc.value.code == "INVALID_ENCRYPTION_MODE"

