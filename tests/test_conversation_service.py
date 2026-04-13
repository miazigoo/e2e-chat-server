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
    active = SimpleNamespace(
        id=1,
        conversation_uuid="uuid-1",
        title="active",
        user_a_id=1,
        user_b_id=2,
        protection_mode=SimpleNamespace(value="normal"),
        message_ttl_days=60,
        delete_after_read_seconds=None,
        is_active=True,
        is_purged=False,
        created_at=_dt(),
        updated_at=_dt(),
    )
    purged = SimpleNamespace(
        id=2,
        conversation_uuid="uuid-2",
        title="purged",
        user_a_id=1,
        user_b_id=3,
        protection_mode=SimpleNamespace(value="normal"),
        message_ttl_days=60,
        delete_after_read_seconds=None,
        is_active=True,
        is_purged=True,
        created_at=_dt(),
        updated_at=_dt(),
    )

    async def fake_list_for_user(session: Any, user_id: int) -> list[Any]:
        return [active, purged]

    monkeypatch.setattr(
        conversation_service.conversations_repo, "list_for_user", fake_list_for_user
    )

    session = cast(Any, SimpleNamespace())

    result = await conversation_service.list_conversations(
        session,
        current_user=cast(Any, SimpleNamespace(id=1)),
    )

    assert len(result["items"]) == 1
    assert result["items"][0]["conversation_id"] == 1
