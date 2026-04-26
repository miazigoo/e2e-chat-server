from app.core import storage


def test_rewrite_presigned_url_uses_public_base(monkeypatch) -> None:
    monkeypatch.setattr(
        storage.settings,
        "minio_public_endpoint",
        "170.168.10.207:9443",
    )
    monkeypatch.setattr(storage.settings, "minio_public_secure", True)
    monkeypatch.setattr(storage.settings, "minio_public_base_url", None)

    url = storage._rewrite_presigned_url_for_public_access(  # noqa: SLF001
        "http://minio:9000/chat-assets/avatar.png?X-Amz-Signature=abc123"
    )

    assert (
        url == "https://170.168.10.207:9443/chat-assets/avatar.png"
        "?X-Amz-Signature=abc123"
    )


def test_rewrite_presigned_url_keeps_internal_url_without_public_base(
    monkeypatch,
) -> None:
    monkeypatch.setattr(storage.settings, "minio_public_base_url", None)
    monkeypatch.setattr(storage.settings, "minio_public_endpoint", None)

    original = "http://minio:9000/chat-assets/avatar.png?X-Amz-Signature=abc123"

    assert (
        storage._rewrite_presigned_url_for_public_access(original) == original
    )  # noqa: SLF001
