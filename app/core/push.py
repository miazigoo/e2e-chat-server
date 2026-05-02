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


def build_device_approval_push_payload(*, request_id: str) -> dict[str, str]:
    return {
        "type": "device_approval_requested",
        "request_id": request_id,
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
    file_name: str,
    file_size: int,
    sha256: str,
    uploaded_at: str,
    changelog: str | None,
    force_update: bool,
    min_supported_version_code: int | None,
) -> dict[str, str]:
    return {
        "type": "app_update_available",
        "platform": "android",
        "version_name": version_name,
        "version_code": str(version_code),
        "file_name": file_name,
        "file_size": str(file_size),
        "sha256": sha256,
        "uploaded_at": uploaded_at,
        "changelog": changelog or "",
        "force_update": "true" if force_update else "false",
        "min_supported_version_code": (
            str(min_supported_version_code) if min_supported_version_code else ""
        ),
    }
