from datetime import datetime, timezone

from app.core.totp import (
    build_totp_provisioning_uri,
    generate_totp_secret,
    verify_totp_code,
)


def test_generate_totp_secret_looks_like_base32() -> None:
    secret = generate_totp_secret()

    assert len(secret) >= 32
    assert secret.isalnum()
    assert secret.upper() == secret


def test_build_totp_provisioning_uri_contains_expected_fields() -> None:
    uri = build_totp_provisioning_uri(
        secret="JBSWY3DPEHPK3PXP",
        issuer="secure-chat-backend",
        account_name="@tester",
    )

    assert uri.startswith("otpauth://totp/")
    assert "secret=JBSWY3DPEHPK3PXP" in uri
    assert "issuer=secure-chat-backend" in uri


def test_verify_totp_code_known_vector() -> None:
    assert verify_totp_code(
        secret="JBSWY3DPEHPK3PXP",
        code="282760",
        now_dt=datetime(1970, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        window=0,
    )
