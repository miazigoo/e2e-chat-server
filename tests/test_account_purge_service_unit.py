from types import SimpleNamespace
from typing import Any, cast

import pytest

from app.services.account_purge_service import purge_account


@pytest.mark.asyncio
async def test_purge_account_not_found() -> None:
    class FakeSession:
        async def get(self, model: Any, user_id: int) -> Any:
            return None

    result = await purge_account(
        cast(Any, FakeSession()),
        user_id=123,
        reason="unit-test",
    )

    assert result["found"] is False
    assert result["purged"] is False
