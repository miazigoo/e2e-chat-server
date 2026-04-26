from __future__ import annotations

import asyncio
import logging
import smtplib
from email.message import EmailMessage

from app.core.config import settings
from app.core.exceptions import ServiceUnavailableError

logger = logging.getLogger(__name__)


def _build_login_code_message(
    *,
    recipient_email: str,
    recipient_nickname: str,
    code: str,
) -> EmailMessage:
    from_name = (
        settings.smtp_from_name or settings.app_name
    ).strip() or settings.app_name
    from_email = (settings.smtp_from_email or "").strip()
    subject = f"{settings.app_name}: verification code"

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = f"{from_name} <{from_email}>"
    message["To"] = recipient_email
    message.set_content(
        "\n".join(
            [
                f"Hello {recipient_nickname},",
                "",
                f"Your verification code is: {code}",
                "",
                f"The code expires in {settings.email_code_expire_minutes} minutes.",
                "If you did not request this code, you can ignore this email.",
            ]
        )
    )
    return message


def _send_message_sync(message: EmailMessage) -> None:
    host = (settings.smtp_host or "").strip()
    from_email = (settings.smtp_from_email or "").strip()
    if not host or not from_email:
        raise ServiceUnavailableError(
            code="EMAIL_DELIVERY_NOT_CONFIGURED",
            message="Email delivery is not configured",
        )

    smtp_cls = smtplib.SMTP_SSL if settings.smtp_use_ssl else smtplib.SMTP
    with smtp_cls(
        host, settings.smtp_port, timeout=settings.smtp_timeout_seconds
    ) as client:
        if settings.smtp_starttls and not settings.smtp_use_ssl:
            client.starttls()

        username = (settings.smtp_username or "").strip()
        if username:
            client.login(username, settings.smtp_password or "")

        client.send_message(message)


async def send_login_code_email(
    *,
    recipient_email: str,
    recipient_nickname: str,
    code: str,
) -> None:
    message = _build_login_code_message(
        recipient_email=recipient_email,
        recipient_nickname=recipient_nickname,
        code=code,
    )

    try:
        await asyncio.to_thread(_send_message_sync, message)
    except ServiceUnavailableError:
        raise
    except Exception as exc:
        logger.exception(
            "Failed to deliver auth email code",
            extra={
                "event": "auth_email_delivery_failed",
                "reason": exc.__class__.__name__,
            },
        )
        raise ServiceUnavailableError(
            code="EMAIL_DELIVERY_FAILED",
            message="Could not deliver verification code",
        ) from exc
