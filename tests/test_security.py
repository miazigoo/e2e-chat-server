from typing import Any

from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_hash_and_verify_password() -> None:
    password = "super-secret-password"
    password_hash = hash_password(password)

    assert password_hash != password
    assert verify_password(password, password_hash) is True
    assert verify_password("wrong-password", password_hash) is False


def test_create_and_decode_access_token() -> None:
    token = create_access_token("123", extra={"nickname": "@tester"})
    payload: dict[str, Any] = decode_token(token)

    assert payload["sub"] == "123"
    assert payload["type"] == "access"
    assert payload["nickname"] == "@tester"


def test_create_and_decode_refresh_token() -> None:
    token = create_refresh_token("123", extra={"nickname": "@tester"})
    payload: dict[str, Any] = decode_token(token)

    assert payload["sub"] == "123"
    assert payload["type"] == "refresh"
    assert payload["nickname"] == "@tester"
