from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, cast

import pytest

import app.services.message_service as message_service
from app.core.exceptions import BadRequestError, ConflictError, GoneError, NotFoundError
from app.schemas.messages import (
    DeleteMessagesRequest,
    MarkReadRequest,
    SendMessageRequest,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_send_message_conversation_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_for_user(
        session: Any, conversation_id: int, user_id: int
    ) -> Any:
        return None

    monkeypatch.setattr(
        message_service.conversations_repo, "get_for_user", fake_get_for_user
    )

    session = cast(Any, SimpleNamespace())

    with pytest.raises(NotFoundError) as exc:
        await message_service.send_message(
            session,
            current_user=cast(Any, SimpleNamespace(id=1)),
            current_device=cast(Any, SimpleNamespace(id=10)),
            payload=SendMessageRequest(
                conversation_id=1,
                recipient_user_id=2,
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
    conversation = SimpleNamespace(
        id=1,
        user_a_id=1,
        user_b_id=2,
        is_purged=False,
        message_ttl_days=60,
        delete_after_read_seconds=None,
    )

    async def fake_get_for_user(
        session: Any, conversation_id: int, user_id: int
    ) -> Any:
        return conversation

    monkeypatch.setattr(
        message_service.conversations_repo, "get_for_user", fake_get_for_user
    )

    session = cast(Any, SimpleNamespace())

    with pytest.raises(BadRequestError) as exc:
        await message_service.send_message(
            session,
            current_user=cast(Any, SimpleNamespace(id=1)),
            current_device=cast(Any, SimpleNamespace(id=10)),
            payload=SendMessageRequest(
                conversation_id=1,
                recipient_user_id=999,
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
    conversation = SimpleNamespace(
        id=1,
        user_a_id=1,
        user_b_id=2,
        is_purged=True,
        message_ttl_days=60,
        delete_after_read_seconds=None,
    )

    async def fake_get_for_user(
        session: Any, conversation_id: int, user_id: int
    ) -> Any:
        return conversation

    monkeypatch.setattr(
        message_service.conversations_repo, "get_for_user", fake_get_for_user
    )

    session = cast(Any, SimpleNamespace())

    with pytest.raises(GoneError) as exc:
        await message_service.send_message(
            session,
            current_user=cast(Any, SimpleNamespace(id=1)),
            current_device=cast(Any, SimpleNamespace(id=10)),
            payload=SendMessageRequest(
                conversation_id=1,
                recipient_user_id=2,
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
    conversation = SimpleNamespace(
        id=1,
        user_a_id=1,
        user_b_id=2,
        is_purged=False,
        message_ttl_days=60,
        delete_after_read_seconds=None,
    )

    async def fake_get_for_user(
        session: Any, conversation_id: int, user_id: int
    ) -> Any:
        return conversation

    async def fake_get_active_by_user_id(session: Any, user_id: int) -> Any:
        return None

    monkeypatch.setattr(
        message_service.conversations_repo, "get_for_user", fake_get_for_user
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
            current_device=cast(Any, SimpleNamespace(id=10)),
            payload=SendMessageRequest(
                conversation_id=1,
                recipient_user_id=2,
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
            current_device=cast(Any, SimpleNamespace(id=20)),
            message_id=1,
            payload=MarkReadRequest(),
        )

    assert exc.value.status_code == 404
    assert exc.value.code == "MESSAGE_NOT_FOUND"
