from app.core.config import Settings


def test_minio_public_endpoint_accepts_host_port() -> None:
    settings = Settings(
        APP_ENV="production",
        BACKEND_CORS_ORIGINS="https://170.168.10.207",
        MINIO_PUBLIC_ENDPOINT="170.168.10.207:9443",
        MINIO_PUBLIC_SECURE=True,
    )

    assert settings.resolved_minio_public_base_url == "https://170.168.10.207:9443"
