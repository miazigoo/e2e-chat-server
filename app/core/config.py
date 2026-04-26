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
    smtp_host: Optional[str] = Field(default=None, alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_username: Optional[str] = Field(default=None, alias="SMTP_USERNAME")
    smtp_password: Optional[str] = Field(default=None, alias="SMTP_PASSWORD")
    smtp_from_email: Optional[str] = Field(default=None, alias="SMTP_FROM_EMAIL")
    smtp_from_name: Optional[str] = Field(default=None, alias="SMTP_FROM_NAME")
    smtp_starttls: bool = Field(default=True, alias="SMTP_STARTTLS")
    smtp_use_ssl: bool = Field(default=False, alias="SMTP_USE_SSL")
    smtp_timeout_seconds: int = Field(default=10, alias="SMTP_TIMEOUT_SECONDS")
    allow_debug_email_codes: bool = Field(
        default=False,
        alias="ALLOW_DEBUG_EMAIL_CODES",
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
    minio_bucket_assets: str = Field(alias="MINIO_BUCKET_ASSETS")
    presigned_download_expire_seconds: int = Field(
        default=300, alias="PRESIGNED_DOWNLOAD_EXPIRE_SECONDS"
    )
    presigned_upload_expire_seconds: int = Field(
        default=900, alias="PRESIGNED_UPLOAD_EXPIRE_SECONDS"
    )
    avatar_max_bytes: int = Field(default=5 * 1024 * 1024, alias="AVATAR_MAX_BYTES")
    apk_max_bytes: int = Field(default=256 * 1024 * 1024, alias="APK_MAX_BYTES")
    apk_upload_token: str = Field(alias="APK_UPLOAD_TOKEN")

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

    @property
    def email_delivery_enabled(self) -> bool:
        return bool(
            (self.smtp_host or "").strip() and (self.smtp_from_email or "").strip()
        )

    @model_validator(mode="after")
    def validate_prod_cors(self) -> "Settings":
        if self.app_env == "production" and self.backend_cors_origins == ["*"]:
            raise ValueError("BACKEND_CORS_ORIGINS cannot be '*' in production")
        return self

    @model_validator(mode="after")
    def validate_debug_email_codes(self) -> "Settings":
        if self.app_env == "production" and self.allow_debug_email_codes:
            raise ValueError("ALLOW_DEBUG_EMAIL_CODES cannot be enabled in production")
        return self

    @model_validator(mode="after")
    def validate_security_limits(self) -> "Settings":
        if self.email_code_max_attempts < 1:
            raise ValueError("EMAIL_CODE_MAX_ATTEMPTS must be >= 1")
        if self.email_code_expire_minutes < 1:
            raise ValueError("EMAIL_CODE_EXPIRE_MINUTES must be >= 1")
        if self.smtp_port < 1:
            raise ValueError("SMTP_PORT must be >= 1")
        if self.smtp_timeout_seconds < 1:
            raise ValueError("SMTP_TIMEOUT_SECONDS must be >= 1")
        if self.smtp_use_ssl and self.smtp_starttls:
            raise ValueError("SMTP_USE_SSL and SMTP_STARTTLS cannot both be enabled")
        if (
            any(
                value
                for value in (
                    self.smtp_host,
                    self.smtp_username,
                    self.smtp_password,
                    self.smtp_from_email,
                    self.smtp_from_name,
                )
            )
            and not self.email_delivery_enabled
        ):
            raise ValueError(
                "SMTP_HOST and SMTP_FROM_EMAIL are required when SMTP is configured"
            )
        return self


settings = Settings()  # type: ignore[call-arg]
