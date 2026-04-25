from datetime import datetime

from pydantic import BaseModel, Field


class LatestAppReleaseResponseData(BaseModel):
    platform: str
    version_name: str
    version_code: int
    file_name: str
    file_size: int
    sha256: str
    changelog: str | None = None
    content_type: str
    uploaded_at: datetime
    download_url: str
    download_url_expires_in: int = Field(ge=1)


class ApkUploadResponseData(BaseModel):
    platform: str
    version_name: str
    version_code: int
    file_name: str
    file_size: int
    sha256: str
    uploaded_at: datetime
    notified_devices: int
