from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)


def dispatch_background_task(
    *,
    task_name: str,
    dispatcher: Callable[..., Any],
    args: tuple[Any, ...],
    extra: dict[str, object] | None = None,
) -> bool:
    try:
        dispatcher(*args)
        return True
    except Exception:
        log_extra: dict[str, object] = {
            "event": "task_dispatch_failed",
            "task_name": task_name,
        }
        if extra:
            log_extra.update(extra)
        logger.exception("Background task dispatch failed", extra=log_extra)
        return False
