from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, cast

import pytest
from fastapi import HTTPException

import app.services.conversation_service as conversation_service
from app.schemas.conversations import (
    ClearConversationRequest,
    CreateConversationRequest,
    UpdateConversationRequest,
)


def _dt() -> datetime:
    return datetime.now(timezone.utc)


@pytest.mark.asyncio
async def test_create_conversation_with_self_forbidden() -> None:
    session = cast(Any, SimpleNamespace())

    with pytest.raises(HTTPException) as exc:
        await conversation_service.create_conversation(
            session,
            current_user=cast(Any, SimpleNamespace(id=1)),
            payload=CreateConversationRequest(
                recipient_user_id=1,
                title="self",
                protection_mode="normal",
                message_ttl_days=60,
            ),
        )

    assert exc.value.status_code == 400
    assert exc.value.detail["code"] == "SELF_CONVERSATION_NOT_ALLOWED"


@pytest.mark.asyncio
async def test_create_conversation_recipient_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_by_id(session: Any, user_id: int) -> Any:
        return None

    monkeypatch.setattr(conversation_service.users_repo, "get_by_id", fake_get_by_id)

    session = cast(Any, SimpleNamespace())

    with pytest.raises(HTTPException) as exc:
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
    assert exc.value.detail["code"] == "RECIPIENT_NOT_FOUND"


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

    with pytest.raises(HTTPException) as exc:
        await conversation_service.get_conversation(
            session,
            current_user=cast(Any, SimpleNamespace(id=1)),
            conversation_id=999,
        )

    assert exc.value.status_code == 404
    assert exc.value.detail["code"] == "CONVERSATION_NOT_FOUND"


@pytest.mark.asyncio
async def test_update_conversation_not_found(
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

    with pytest.raises(HTTPException) as exc:
        await conversation_service.update_conversation(
            session,
            current_user=cast(Any, SimpleNamespace(id=1)),
            conversation_id=999,
            payload=UpdateConversationRequest(title="new title"),
        )

    assert exc.value.status_code == 404
    assert exc.value.detail["code"] == "CONVERSATION_NOT_FOUND"


@pytest.mark.asyncio
async def test_clear_local_conversation_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_participant(
        session: Any, conversation_id: int, user_id: int
    ) -> Any:
        return None

    monkeypatch.setattr(
        conversation_service.conversations_repo, "get_participant", fake_get_participant
    )

    session = cast(Any, SimpleNamespace())

    with pytest.raises(HTTPException) as exc:
        await conversation_service.clear_local(
            session,
            current_user=cast(Any, SimpleNamespace(id=1)),
            conversation_id=999,
        )

    assert exc.value.status_code == 404
    assert exc.value.detail["code"] == "CONVERSATION_NOT_FOUND"


@pytest.mark.asyncio
async def test_clear_global_conversation_not_found(
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

    with pytest.raises(HTTPException) as exc:
        await conversation_service.clear_global(
            session,
            current_user=cast(Any, SimpleNamespace(id=1)),
            conversation_id=999,
            payload=ClearConversationRequest(reason="cleanup"),
        )

    assert exc.value.status_code == 404
    assert exc.value.detail["code"] == "CONVERSATION_NOT_FOUND"


@pytest.mark.asyncio
async def test_list_conversations_filters_purged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    conversation_active = SimpleNamespace(
        id=1,
        conversation_uuid="11111111-1111-1111-1111-111111111111",
        title="Active",
        protection_mode="normal",
        message_ttl_days=60,
        delete_after_read_seconds=None,
        is_active=True,
        is_purged=False,
        updated_at=datetime.now(timezone.utc),
    )
    conversation_purged = SimpleNamespace(
        id=2,
        conversation_uuid="22222222-2222-2222-2222-222222222222",
        title="Purged",
        protection_mode="normal",
        message_ttl_days=60,
        delete_after_read_seconds=None,
        is_active=True,
        is_purged=True,
        updated_at=datetime.now(timezone.utc),
    )

    async def fake_list_overview_for_user(
        session: Any, *, user_id: int
    ) -> list[dict[str, Any]]:
        return [
            {
                "conversation": conversation_active,
                "peer_user_id": 2,
                "peer_nickname": "@alice",
                "unread_count": 1,
                "last_message": None,
            },
            {
                "conversation": conversation_purged,
                "peer_user_id": 3,
                "peer_nickname": "@bob",
                "unread_count": 0,
                "last_message": None,
            },
        ]

    monkeypatch.setattr(
        conversation_service.conversations_repo,
        "list_overview_for_user",
        fake_list_overview_for_user,
    )

    session = cast(Any, SimpleNamespace())
    current_user = cast(Any, SimpleNamespace(id=1))

    result = await conversation_service.list_conversations(
        session,
        current_user=current_user,
    )

    assert len(result.items) == 2
    assert result.items[0].peer.nickname == "@alice"
    assert result.items[1].peer.nickname == "@bob"
