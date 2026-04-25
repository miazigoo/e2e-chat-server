from __future__ import annotations

import logging
from datetime import timedelta

import firebase_admin
from firebase_admin import credentials, messaging

from app.core.config import settings

logger = logging.getLogger(__name__)


def _ensure_firebase_initialized() -> bool:
    if not settings.fcm_credentials_path or not settings.fcm_project_id:
        return False

    if not firebase_admin._apps:
        cred = credentials.Certificate(settings.fcm_credentials_path)
        firebase_admin.initialize_app(
            cred,
            {"projectId": settings.fcm_project_id},
        )
    return True


def send_push_data_message(*, token: str, data: dict[str, str]) -> str | None:
    if not token:
        return None

    try:
        if not _ensure_firebase_initialized():
            return None

        message = messaging.Message(
            token=token,
            data=data,
            android=messaging.AndroidConfig(
                priority="high",
                ttl=timedelta(seconds=settings.fcm_notification_ttl_seconds),
            ),
        )
        result = messaging.send(message)
        return str(result) if result is not None else None
    except Exception:
        logger.exception("FCM push send failed")
        return None


def build_new_message_push_payload(
    *,
    conversation_id: int,
    message_id: int,
) -> dict[str, str]:
    return {
        "type": "new_message",
        "conversation_id": str(conversation_id),
        "message_id": str(message_id),
    }


def build_generic_event_push_payload(
    *,
    conversation_id: int,
    event_type: str,
) -> dict[str, str]:
    return {
        "type": "conversation_event",
        "conversation_id": str(conversation_id),
        "event_type": event_type,
    }


def build_app_update_push_payload(
    *,
    version_name: str,
    version_code: int,
) -> dict[str, str]:
    return {
        "type": "app_update_available",
        "platform": "android",
        "version_name": version_name,
        "version_code": str(version_code),
    }
