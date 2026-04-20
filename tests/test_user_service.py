from types import SimpleNamespace
from typing import Any, cast

import pytest

import app.services.user_service as user_service
from app.core.exceptions import BadRequestError, NotFoundError


@pytest.mark.asyncio
async def test_get_user_safety_rejects_self() -> None:
    session = cast(Any, SimpleNamespace())
    current_user = cast(Any, SimpleNamespace(id=1))

    with pytest.raises(BadRequestError) as exc:
        await user_service.get_user_safety(
            session,
            current_user=current_user,
            target_user_id=1,
        )

    assert exc.value.status_code == 400
    assert exc.value.code == "SELF_TARGET_NOT_ALLOWED"


@pytest.mark.asyncio
async def test_get_user_safety_user_not_found(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_get_by_id(session: Any, user_id: int) -> Any:
        return None

    monkeypatch.setattr(user_service.users_repo, "get_by_id", fake_get_by_id)

    session = cast(Any, SimpleNamespace())
    current_user = cast(Any, SimpleNamespace(id=1))

    with pytest.raises(NotFoundError) as exc:
        await user_service.get_user_safety(
            session,
            current_user=current_user,
            target_user_id=2,
        )

    assert exc.value.status_code == 404
    assert exc.value.code == "USER_NOT_FOUND"
