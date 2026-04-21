from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.chat_enums import EncryptionMode, MessageType


class SendMessageRequest(BaseModel):
    conversation_id: int
    recipient_user_id: int

    message_uuid: str = Field(min_length=36, max_length=64)
    reply_to_message_id: int | None = None

    message_type: MessageType = MessageType.TEXT
    ciphertext: str = Field(min_length=1)
    ciphertext_version: int = Field(default=1, ge=1)
    encryption_mode: EncryptionMode = EncryptionMode.SIGNAL
    nonce: str = Field(min_length=1)
    aad_hash: str | None = None

    client_created_at: datetime
    expires_at: datetime | None = None
    auto_delete_after_read_seconds: int | None = Field(default=None, gt=0)

    attachment_ids: list[int] = Field(default_factory=list, max_length=20)

    @field_validator("message_uuid")
    @classmethod
    def validate_message_uuid(cls, value: str) -> str:
        try:
            return str(UUID(value))
        except ValueError as exc:
            raise ValueError("message_uuid must be a valid UUID") from exc

    @field_validator("attachment_ids")
    @classmethod
    def validate_attachment_ids_unique(cls, value: list[int]) -> list[int]:
        if len(value) != len(set(value)):
            raise ValueError("attachment_ids must be unique")
        return value


class MarkDeliveredRequest(BaseModel):
    delivered_at: datetime | None = None


class MarkReadRequest(BaseModel):
    read_at: datetime | None = None


class DeleteMessagesRequest(BaseModel):
    conversation_id: int
    message_ids: list[int] = Field(min_length=1, max_length=200)

    @field_validator("message_ids")
    @classmethod
    def validate_message_ids_unique(cls, value: list[int]) -> list[int]:
        if len(value) != len(set(value)):
            raise ValueError("message_ids must be unique")
        return value


class SendMessageResponseData(BaseModel):
    message_id: int
    message_uuid: str
    conversation_id: int
    recipient_user_id: int
    recipient_device_id: int
    server_received_at: datetime
    delivery_status: str
    is_idempotent_replay: bool = False


class MessageListItemSchema(BaseModel):
    message_id: int
    message_uuid: str
    sender_user_id: int
    recipient_user_id: int
    message_type: MessageType
    ciphertext: str
    ciphertext_version: int
    encryption_mode: EncryptionMode
    nonce: str
    aad_hash: str | None = None
    client_created_at: datetime
    server_received_at: datetime
    delivered_at: datetime | None = None
    read_at: datetime | None = None
    expires_at: datetime
    has_attachments: bool


class ListMessagesResponseData(BaseModel):
    items: list[MessageListItemSchema] = Field(default_factory=list)


class MarkDeliveredResponseData(BaseModel):
    message_id: int
    status: str
    delivered_at: datetime


class MarkReadResponseData(BaseModel):
    message_id: int
    status: str
    read_at: datetime


class DeleteMessagesResponseData(BaseModel):
    deleted: bool
    scope: str
    message_ids: list[int] = Field(default_factory=list)
