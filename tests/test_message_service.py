from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, cast
from uuid import uuid4

import pytest

import app.services.message_service as message_service
from app.core.exceptions import BadRequestError, ConflictError, GoneError, NotFoundError
from app.schemas.messages import (
    ForwardMessagesRequest,
    MarkReadRequest,
    SendMessageRequest,
    SetMessageReactionRequest,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _conversation(**overrides: Any) -> SimpleNamespace:
    base = {
        "id": 1,
        "user_a_id": 1,
        "user_b_id": 2,
        "is_saved_messages": False,
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


def _participant(**overrides: Any) -> SimpleNamespace:
    base = {
        "conversation_id": 1,
        "user_id": 1,
        "cleared_at": None,
        "shared_secret_enabled": False,
        "shared_secret_fingerprint": None,
        "shared_secret_updated_at": None,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def _patch_participant(
    monkeypatch: pytest.MonkeyPatch,
    *,
    shared_secret_enabled: bool = False,
) -> None:
    async def fake_get_participant(
        session: Any,
        conversation_id: int,
        user_id: int,
    ) -> Any:
        return _participant(
            conversation_id=conversation_id,
            user_id=user_id,
            shared_secret_enabled=shared_secret_enabled,
        )

    monkeypatch.setattr(
        message_service.conversations_repo,
        "get_participant",
        fake_get_participant,
    )


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
    _patch_participant(monkeypatch)

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
    _patch_participant(monkeypatch)

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
    _patch_participant(monkeypatch)

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
    _patch_participant(monkeypatch)

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
async def test_send_message_to_saved_messages_uses_current_device(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation = _conversation(user_b_id=1, is_saved_messages=True)
    current_device = _device(id=77, user_id=1)
    committed = False

    async def fake_get_for_user(
        session: Any,
        conversation_id: int,
        user_id: int,
    ) -> Any:
        return conversation

    async def fake_get_active_by_user_id(session: Any, user_id: int) -> Any:
        return None

    async def fake_get_by_message_uuid(
        session: Any,
        conversation_id: int,
        sender_user_id: int,
        message_uuid: str,
    ) -> Any:
        return None

    async def fake_create_message(session: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(
            id=100,
            message_uuid=kwargs["message_uuid"],
            conversation_id=kwargs["conversation_id"],
            recipient_user_id=kwargs["recipient_user_id"],
            recipient_device_id=kwargs["recipient_device_id"],
            server_received_at=_now(),
            sender_user_id=kwargs["sender_user_id"],
            sender_device_id=kwargs["sender_device_id"],
            reply_to_message_id=None,
            message_type=SimpleNamespace(value="text"),
            encryption_mode=SimpleNamespace(value="signal"),
            has_attachments=False,
            client_created_at=kwargs["client_created_at"],
            read_at=None,
            delivered_at=None,
        )

    async def fake_create_recipient_state(session: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(
            message_id=kwargs["message_id"],
            recipient_device_id=kwargs["recipient_device_id"],
        )

    async def fake_mark_delivered(
        session: Any,
        *,
        message: Any,
        state: Any,
        delivered_at: Any,
    ) -> None:
        message.delivered_at = delivered_at

    async def fake_mark_read(
        session: Any,
        *,
        message: Any,
        state: Any,
        read_at: Any,
    ) -> None:
        message.read_at = read_at

    async def fake_create_event(session: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(
            id=1,
            event_uuid="event-uuid",
            event_type=SimpleNamespace(value="message_created"),
            actor_user_id=1,
            actor_device_id=current_device.id,
            target_message_id=100,
            payload={},
            created_at=_now(),
        )

    async def fake_touch_conversation(
        session: Any,
        *,
        conversation: Any,
        touched_at: Any,
    ) -> None:
        conversation.updated_at = touched_at

    async def fake_publish_conversation_event(*args: Any, **kwargs: Any) -> None:
        return None

    async def fake_publish_user_event(*args: Any, **kwargs: Any) -> None:
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
    monkeypatch.setattr(
        message_service.messages_repo,
        "get_by_message_uuid",
        fake_get_by_message_uuid,
    )
    monkeypatch.setattr(
        message_service.messages_repo,
        "create_message",
        fake_create_message,
    )
    monkeypatch.setattr(
        message_service.messages_repo,
        "create_recipient_state",
        fake_create_recipient_state,
    )
    monkeypatch.setattr(
        message_service.messages_repo,
        "mark_delivered",
        fake_mark_delivered,
    )
    monkeypatch.setattr(
        message_service.messages_repo,
        "mark_read",
        fake_mark_read,
    )
    monkeypatch.setattr(
        message_service.conversations_repo,
        "create_event",
        fake_create_event,
    )
    monkeypatch.setattr(
        message_service.conversations_repo,
        "touch_conversation",
        fake_touch_conversation,
    )
    monkeypatch.setattr(
        message_service.realtime_hub,
        "publish_conversation_event",
        fake_publish_conversation_event,
    )
    monkeypatch.setattr(
        message_service.realtime_hub,
        "publish_user_event",
        fake_publish_user_event,
    )
    _patch_participant(monkeypatch)

    async def fake_commit() -> None:
        nonlocal committed
        committed = True

    session = cast(Any, SimpleNamespace(commit=fake_commit))

    result = await message_service.send_message(
        session,
        current_user=cast(Any, SimpleNamespace(id=1)),
        current_device=cast(Any, current_device),
        payload=SendMessageRequest(
            conversation_id=1,
            recipient_user_id=1,
            message_uuid=str(uuid4()),
            message_type="text",
            ciphertext="cipher",
            ciphertext_version=1,
            encryption_mode="signal",
            nonce="nonce",
            client_created_at=_now(),
        ),
    )

    assert committed is True
    assert result["recipient_user_id"] == 1
    assert result["recipient_device_id"] == 77


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
    _patch_participant(monkeypatch)

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
    _patch_participant(monkeypatch)

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
    _patch_participant(monkeypatch)

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
    _patch_participant(monkeypatch, shared_secret_enabled=True)

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


@pytest.mark.asyncio
async def test_set_message_reaction_message_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_by_id(session: Any, message_id: int) -> Any:
        return None

    monkeypatch.setattr(message_service.messages_repo, "get_by_id", fake_get_by_id)

    session = cast(Any, SimpleNamespace())

    with pytest.raises(NotFoundError) as exc:
        await message_service.set_message_reaction(
            session,
            current_user=cast(Any, SimpleNamespace(id=1)),
            current_device=cast(Any, _device()),
            message_id=999,
            payload=SetMessageReactionRequest(reaction="👍"),
        )

    assert exc.value.status_code == 404
    assert exc.value.code == "MESSAGE_NOT_FOUND"


def test_build_reaction_summaries_marks_my_reaction() -> None:
    reactions = [
        SimpleNamespace(reaction="👍", user_id=1),
        SimpleNamespace(reaction="👍", user_id=2),
        SimpleNamespace(reaction="❤️", user_id=2),
    ]

    summaries = message_service._build_reaction_summaries(  # noqa: SLF001
        reactions,
        current_user_id=1,
    )

    assert [summary.model_dump() for summary in summaries] == [
        {"reaction": "👍", "count": 2, "me": True},
        {"reaction": "❤️", "count": 1, "me": False},
    ]


@pytest.mark.asyncio
async def test_search_messages_blank_query_returns_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_participant(
        session: Any,
        conversation_id: int,
        user_id: int,
    ) -> Any:
        return _participant(
            conversation_id=conversation_id,
            user_id=user_id,
        )

    monkeypatch.setattr(
        message_service.conversations_repo,
        "get_participant",
        fake_get_participant,
    )

    result = await message_service.search_messages(
        cast(Any, SimpleNamespace()),
        current_user=cast(Any, SimpleNamespace(id=1)),
        conversation_id=1,
        query="   ",
        limit=20,
    )

    assert result.conversation_id == 1
    assert result.items == []


@pytest.mark.asyncio
async def test_forward_messages_invalid_recipient(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation = _conversation()

    async def fake_get_for_user(
        session: Any,
        conversation_id: int,
        user_id: int,
    ) -> Any:
        return conversation

    async def fake_get_participant(
        session: Any,
        conversation_id: int,
        user_id: int,
    ) -> Any:
        return _participant(conversation_id=conversation_id, user_id=user_id)

    monkeypatch.setattr(
        message_service.conversations_repo,
        "get_for_user",
        fake_get_for_user,
    )
    monkeypatch.setattr(
        message_service.conversations_repo,
        "get_participant",
        fake_get_participant,
    )

    with pytest.raises(BadRequestError) as exc:
        await message_service.forward_messages(
            cast(Any, SimpleNamespace()),
            current_user=cast(Any, SimpleNamespace(id=1)),
            current_device=cast(Any, _device()),
            payload=ForwardMessagesRequest(
                conversation_id=1,
                recipient_user_id=999,
                message_ids=[10],
            ),
        )

    assert exc.value.code == "INVALID_RECIPIENT"
