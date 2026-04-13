from datetime import datetime

from pydantic import BaseModel, Field

from app.models.chat_enums import EncryptionMode, MessageType


class SendMessageRequest(BaseModel):
    conversation_id: int
    recipient_user_id: int

    message_uuid: str | None = None
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


class MarkReadRequest(BaseModel):
    read_at: datetime | None = None


class DeleteMessagesRequest(BaseModel):
    conversation_id: int
    message_ids: list[int] = Field(min_length=1, max_length=200)
