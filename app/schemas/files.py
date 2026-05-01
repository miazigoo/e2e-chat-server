from datetime import datetime

from pydantic import BaseModel, Field

from app.schemas.media_tags import MediaTagSchema


class CreateUploadSessionRequest(BaseModel):
    conversation_id: int
    files_expected_count: int = Field(ge=1, le=20)


class InitAttachmentItemRequest(BaseModel):
    encrypted_file_name: str | None = Field(default=None, max_length=1024)
    file_size: int = Field(gt=0)
    mime_hint: str | None = Field(default=None, max_length=255)
    sha256_encrypted_blob: str = Field(min_length=64, max_length=64)
    encrypted_metadata: dict | None = None


class InitAttachmentsRequest(BaseModel):
    items: list[InitAttachmentItemRequest] = Field(min_length=1, max_length=20)


class CompleteUploadSessionRequest(BaseModel):
    attachment_ids: list[int] = Field(min_length=1, max_length=20)


class AttachmentInitItemSchema(BaseModel):
    attachment_id: int
    attachment_uuid: str
    storage_key: str
    bucket_name: str
    upload_status: str
    expires_at: datetime | None = None
    upload_url: str | None = None
    upload_method: str | None = None
    upload_headers: dict[str, str] = Field(default_factory=dict)


class InitAttachmentsResponseData(BaseModel):
    session_id: int
    session_uuid: str
    items: list[AttachmentInitItemSchema] = Field(default_factory=list)


class CreateUploadSessionResponseData(BaseModel):
    session_id: int
    session_uuid: str
    conversation_id: int
    files_expected_count: int
    files_uploaded_count: int
    status: str
    expires_at: datetime


class CompleteUploadSessionResponseData(BaseModel):
    session_id: int
    session_uuid: str
    status: str
    files_expected_count: int
    files_uploaded_count: int
    completed_at: datetime


class AttachmentMetadataItemSchema(BaseModel):
    attachment_id: int
    attachment_uuid: str
    message_id: int | None = None
    encrypted_file_name: str | None = None
    encrypted_metadata: dict | None = None
    file_size: int
    mime_hint: str | None = None
    sha256_encrypted_blob: str
    bucket_name: str
    storage_key: str
    upload_status: str
    created_at: datetime
    expires_at: datetime | None = None
    deleted_at: datetime | None = None
    media_tags: list[MediaTagSchema] = Field(default_factory=list)


class ListMessageAttachmentsResponseData(BaseModel):
    message_id: int
    items: list[AttachmentMetadataItemSchema] = Field(default_factory=list)


class GetAttachmentResponseData(AttachmentMetadataItemSchema):
    can_download: bool = True
    download_url: str | None = None
    download_url_expires_in: int | None = None
