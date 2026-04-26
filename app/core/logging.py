from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

from app.core.config import settings


class JsonFormatter(logging.Formatter):
    """Structured JSON formatter for app and infra logs."""

    EXTRA_FIELDS = {
        "request_id",
        "user_id",
        "device_id",
        "conversation_id",
        "message_id",
        "event",
        "task_name",
        "reason",
        "code",
        "path",
        "method",
        "status_code",
    }

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        for field in self.EXTRA_FIELDS:
            value = getattr(record, field, None)
            if value is not None:
                payload[field] = value

        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)

        return json.dumps(payload, ensure_ascii=False, default=str)


def _configure_named_logger(name: str, handler: logging.Handler, level: int) -> None:
    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger.addHandler(handler)
    logger.setLevel(level)
    logger.propagate = False


def setup_logging() -> None:
    """Configure root and common framework loggers to stdout JSON."""

    level = logging.DEBUG if settings.debug else logging.INFO
    sqlalchemy_level = logging.INFO if settings.debug else logging.WARNING

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    for logger_name in (
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "sqlalchemy.pool",
        "celery",
        "audit",
    ):
        _configure_named_logger(logger_name, handler, level)

    _configure_named_logger("sqlalchemy.engine", handler, sqlalchemy_level)
