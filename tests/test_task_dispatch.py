from typing import Any

import app.core.task_dispatch as task_dispatch
from app.core.task_dispatch import dispatch_background_task


def test_dispatch_background_task_success() -> None:
    calls: list[tuple[int, str]] = []

    def fake_dispatcher(user_id: int, reason: str) -> None:
        calls.append((user_id, reason))

    result = dispatch_background_task(
        task_name="purge_account_task",
        dispatcher=fake_dispatcher,
        args=(7, "too_many_attempts"),
        extra={"user_id": 7},
    )

    assert result is True
    assert calls == [(7, "too_many_attempts")]


def test_dispatch_background_task_logs_failure(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    def fake_dispatcher(user_id: int) -> None:
        raise RuntimeError("broker unavailable")

    def fake_exception(message: str, *, extra: dict[str, object]) -> None:
        captured["message"] = message
        captured["extra"] = extra

    monkeypatch.setattr(task_dispatch.logger, "exception", fake_exception)

    result = dispatch_background_task(
        task_name="recompute_unread_counters_for_user_task",
        dispatcher=fake_dispatcher,
        args=(7,),
        extra={"user_id": 7},
    )

    assert result is False
    assert captured["message"] == "Background task dispatch failed"
    assert captured["extra"]["task_name"] == "recompute_unread_counters_for_user_task"
    assert captured["extra"]["user_id"] == 7
