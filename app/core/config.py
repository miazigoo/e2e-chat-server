from typing import List, Optional

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    app_name: str = Field(default="secure-chat-backend", alias="APP_NAME")
    app_env: str = Field(default="development", alias="APP_ENV")
    debug: bool = Field(default=True, alias="DEBUG")
    api_v1_prefix: str = Field(default="/api/v1", alias="API_V1_PREFIX")

    database_url: str = Field(alias="DATABASE_URL")
    redis_url: str = Field(alias="REDIS_URL")
    rabbitmq_url: str = Field(alias="RABBITMQ_URL")

    jwt_secret_key: str = Field(alias="JWT_SECRET_KEY")
    jwt_algorithm: str = Field(default="HS256", alias="JWT_ALGORITHM")
    access_token_expire_minutes: int = Field(
        default=15, alias="ACCESS_TOKEN_EXPIRE_MINUTES"
    )
    refresh_token_expire_days: int = Field(
        default=30, alias="REFRESH_TOKEN_EXPIRE_DAYS"
    )
    bootstrap_token_expire_minutes: int = Field(
        default=15, alias="BOOTSTRAP_TOKEN_EXPIRE_MINUTES"
    )

    email_code_expire_minutes: int = Field(
        default=10, alias="EMAIL_CODE_EXPIRE_MINUTES"
    )
    email_code_max_attempts: int = Field(
        default=5,
        alias="EMAIL_CODE_MAX_ATTEMPTS",
    )
    login_max_failed_attempts: int = Field(default=5, alias="LOGIN_MAX_FAILED_ATTEMPTS")
    login_failure_window_minutes: int = Field(
        default=30, alias="LOGIN_FAILURE_WINDOW_MINUTES"
    )

    minio_endpoint: str = Field(alias="MINIO_ENDPOINT")
    minio_access_key: str = Field(alias="MINIO_ACCESS_KEY")
    minio_secret_key: str = Field(alias="MINIO_SECRET_KEY")
    minio_secure: bool = Field(default=False, alias="MINIO_SECURE")
    minio_bucket_attachments: str = Field(alias="MINIO_BUCKET_ATTACHMENTS")
    minio_bucket_temp: str = Field(alias="MINIO_BUCKET_TEMP")
    presigned_download_expire_seconds: int = Field(
        default=300, alias="PRESIGNED_DOWNLOAD_EXPIRE_SECONDS"
    )
    presigned_upload_expire_seconds: int = Field(
        default=900, alias="PRESIGNED_UPLOAD_EXPIRE_SECONDS"
    )

    fcm_project_id: Optional[str] = Field(default=None, alias="FCM_PROJECT_ID")
    fcm_credentials_path: Optional[str] = Field(
        default=None, alias="FCM_CREDENTIALS_PATH"
    )
    fcm_notification_ttl_seconds: int = Field(
        default=300, alias="FCM_NOTIFICATION_TTL_SECONDS"
    )

    sentry_dsn: Optional[str] = Field(default=None, alias="SENTRY_DSN")
    sentry_environment: Optional[str] = Field(default=None, alias="SENTRY_ENVIRONMENT")
    sentry_release: Optional[str] = Field(default=None, alias="SENTRY_RELEASE")

    backend_cors_origins_raw: str = Field(default="*", alias="BACKEND_CORS_ORIGINS")
    trusted_hosts_raw: str = Field(
        default="localhost,127.0.0.1",
        alias="TRUSTED_HOSTS",
    )

    @property
    def backend_cors_origins(self) -> List[str]:
        raw = self.backend_cors_origins_raw.strip()
        if raw == "*":
            return ["*"]
        return [item.strip() for item in raw.split(",") if item.strip()]

    @property
    def trusted_hosts(self) -> List[str]:
        raw = self.trusted_hosts_raw.strip()
        if raw == "*":
            return ["*"]
        return [item.strip() for item in raw.split(",") if item.strip()]

    @model_validator(mode="after")
    def validate_prod_cors(self) -> "Settings":
        if self.app_env == "production" and self.backend_cors_origins == ["*"]:
            raise ValueError("BACKEND_CORS_ORIGINS cannot be '*' in production")
        return self

    @model_validator(mode="after")
    def validate_security_limits(self) -> "Settings":
        if self.email_code_max_attempts < 1:
            raise ValueError("EMAIL_CODE_MAX_ATTEMPTS must be >= 1")
        if self.email_code_expire_minutes < 1:
            raise ValueError("EMAIL_CODE_EXPIRE_MINUTES must be >= 1")
        return self


settings = Settings()  # type: ignore[call-arg]
