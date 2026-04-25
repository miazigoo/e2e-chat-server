from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import struct
from datetime import datetime, timezone
from io import BytesIO
from urllib.parse import quote

TOTP_DIGITS = 6
TOTP_PERIOD_SECONDS = 30
TOTP_SECRET_BYTES = 20


def generate_totp_secret() -> str:
    secret = base64.b32encode(secrets.token_bytes(TOTP_SECRET_BYTES)).decode("ascii")
    return secret.rstrip("=")


def build_totp_provisioning_uri(*, secret: str, issuer: str, account_name: str) -> str:
    label = quote(f"{issuer}:{account_name}")
    issuer_param = quote(issuer)
    return (
        f"otpauth://totp/{label}"
        f"?secret={secret}"
        f"&issuer={issuer_param}"
        f"&algorithm=SHA1"
        f"&digits={TOTP_DIGITS}"
        f"&period={TOTP_PERIOD_SECONDS}"
    )


def verify_totp_code(
    *,
    secret: str,
    code: str,
    now_dt: datetime | None = None,
    window: int = 1,
) -> bool:
    normalized_code = code.strip().replace(" ", "")
    if len(normalized_code) != TOTP_DIGITS or not normalized_code.isdigit():
        return False

    current_dt = now_dt or datetime.now(timezone.utc)
    counter = int(current_dt.timestamp()) // TOTP_PERIOD_SECONDS

    for offset in range(-window, window + 1):
        if (
            _generate_totp_code(secret=secret, counter=counter + offset)
            == normalized_code
        ):
            return True
    return False


def render_totp_qr_png(*, provisioning_uri: str) -> bytes:
    try:
        import qrcode
    except ImportError as exc:  # pragma: no cover - depends on installed extras
        raise RuntimeError("qrcode dependency is not installed") from exc

    qr = qrcode.QRCode(box_size=8, border=4)
    qr.add_data(provisioning_uri)
    qr.make(fit=True)

    image = qr.make_image(fill_color="black", back_color="white")
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def _generate_totp_code(*, secret: str, counter: int) -> str:
    normalized_secret = secret.strip().upper()
    padding = "=" * ((8 - len(normalized_secret) % 8) % 8)
    key = base64.b32decode(normalized_secret + padding, casefold=True)
    message = struct.pack(">Q", counter)
    digest = hmac.new(key, message, hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    truncated = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    code = truncated % (10**TOTP_DIGITS)
    return f"{code:0{TOTP_DIGITS}d}"
