from datetime import datetime

from pydantic import BaseModel, Field


class AppReleaseDetailsSchema(BaseModel):
    """Public metadata describing the latest published mobile app release."""

    platform: str = Field(description="Target mobile platform for the release.")
    version_name: str = Field(description="Human-readable app version string.")
    version_code: int = Field(description="Monotonic numeric build version.")
    file_name: str = Field(description="Original uploaded APK file name.")
    file_size: int = Field(description="APK size in bytes.")
    sha256: str = Field(description="SHA-256 checksum of the APK file.")
    changelog: str | None = Field(
        default=None,
        description="Optional release notes for the published version.",
    )
    content_type: str | None = Field(
        default=None,
        description="Stored APK content type.",
    )
    uploaded_at: datetime = Field(description="Release publication timestamp.")


class LatestAppReleaseResponseData(AppReleaseDetailsSchema):
    """Latest APK payload including a direct temporary download URL."""

    download_url: str = Field(description="Temporary presigned URL for APK download.")
    download_url_expires_in: int = Field(
        ge=1,
        description="Download URL lifetime in seconds.",
    )


class AppVersionCheckResponseData(BaseModel):
    """Result of comparing the client build number with the latest published APK."""

    current_version_code: int = Field(
        description="Client build number supplied by the device."
    )
    latest_version_code: int = Field(description="Latest available build number.")
    update_available: bool = Field(
        description="Whether the client should prompt the user to update."
    )
    release: LatestAppReleaseResponseData = Field(
        description="Metadata for the latest available Android APK."
    )


class ApkUploadResponseData(AppReleaseDetailsSchema):
    """Response payload returned after a new APK has been uploaded and published."""

    notified_devices: int = Field(
        description="Number of devices that accepted the push notification."
    )
