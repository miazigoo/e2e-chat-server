from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, cast

import pytest

import app.services.conversation_service as conversation_service
from app.core.exceptions import NotFoundError
from app.schemas.conversations import (
    ClearConversationRequest,
    CreateConversationRequest,
    UpdateConversationRequest,
)


def _dt() -> datetime:
    return datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_create_conversation_with_self_returns_saved_messages(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_saved_messages_for_user(session: Any, user_id: int) -> Any:
        return None

    async def fake_create_conversation(session: Any, **kwargs: Any) -> Any:
        return SimpleNamespace(
            id=10,
            conversation_uuid="saved-messages-uuid",
            protection_mode=SimpleNamespace(value="normal"),
            is_saved_messages=True,
        )

    monkeypatch.setattr(
        conversation_service.conversations_repo,
        "get_saved_messages_for_user",
        fake_get_saved_messages_for_user,
    )
    monkeypatch.setattr(
        conversation_service.conversations_repo,
        "create_conversation",
        fake_create_conversation,
    )

    session = cast(Any, SimpleNamespace())
    committed = False

    async def fake_commit() -> None:
        nonlocal committed
        committed = True

    session.commit = fake_commit

    result = await conversation_service.create_conversation(
        session,
        current_user=cast(Any, SimpleNamespace(id=1)),
        payload=CreateConversationRequest(
            recipient_user_id=1,
            title="self",
            protection_mode="normal",
            message_ttl_days=60,
        ),
    )

    assert committed is True
    assert result["conversation_id"] == 10
    assert result["recipient_user_id"] == 1
    assert result["is_saved_messages"] is True


@pytest.mark.asyncio
async def test_create_conversation_recipient_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_by_id(session: Any, user_id: int) -> Any:
        return None

    monkeypatch.setattr(conversation_service.users_repo, "get_by_id", fake_get_by_id)

    session = cast(Any, SimpleNamespace())

    with pytest.raises(NotFoundError) as exc:
        await conversation_service.create_conversation(
            session,
            current_user=cast(Any, SimpleNamespace(id=1)),
            payload=CreateConversationRequest(
                recipient_user_id=2,
                title="chat",
                protection_mode="normal",
                message_ttl_days=60,
            ),
        )

    assert exc.value.status_code == 404
    assert exc.value.code == "RECIPIENT_NOT_FOUND"


@pytest.mark.asyncio
async def test_get_conversation_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_for_user(
        session: Any, conversation_id: int, user_id: int
    ) -> Any:
        return None

    monkeypatch.setattr(
        conversation_service.conversations_repo, "get_for_user", fake_get_for_user
    )

    session = cast(Any, SimpleNamespace())

    with pytest.raises(NotFoundError) as exc:
        await conversation_service.get_conversation(
            session,
            current_user=cast(Any, SimpleNamespace(id=1)),
            conversation_id=999,
        )

    assert exc.value.status_code == 404
    assert exc.value.code == "CONVERSATION_NOT_FOUND"
