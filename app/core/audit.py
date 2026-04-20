from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("audit")


def audit_log(
    event: str,
    *,
    user_id: int | None = None,
    device_id: int | None = None,
    conversation_id: int | None = None,
    message_id: int | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    payload: dict[str, Any] = {
        "event": event,
    }

    if user_id is not None:
        payload["user_id"] = user_id
    if device_id is not None:
        payload["device_id"] = device_id
    if conversation_id is not None:
        payload["conversation_id"] = conversation_id
    if message_id is not None:
        payload["message_id"] = message_id
    if extra:
        payload.update(extra)

    logger.info("audit_event", extra=payload)
