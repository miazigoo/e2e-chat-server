from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.models.chat_enums import ProtectionMode
from app.schemas.messages import MessagePreviewSchema


class CreateConversationRequest(BaseModel):
    recipient_user_id: int
    title: str | None = Field(default=None, max_length=255)
    protection_mode: ProtectionMode = ProtectionMode.NORMAL
    message_ttl_days: int | None = Field(default=60, ge=1, le=60)
    delete_after_read_seconds: int | None = Field(default=None, gt=0)


class UpdateConversationRequest(BaseModel):
    title: str | None = Field(default=None, max_length=255)
    message_ttl_days: int | None = Field(default=None, ge=1, le=60)
    delete_after_read_seconds: int | None = Field(default=None, gt=0)


class ClearConversationRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=255)


class UpdateConversationSettingsRequest(BaseModel):
    shared_secret_enabled: bool | None = None
    shared_secret_fingerprint: str | None = Field(
        default=None,
        min_length=16,
        max_length=128,
    )

    @model_validator(mode="after")
    def validate_shared_secret(self) -> "UpdateConversationSettingsRequest":
        if self.shared_secret_enabled is True and not self.shared_secret_fingerprint:
            raise ValueError(
                "shared_secret_fingerprint is required when shared secret is enabled"
            )
        return self


class CreateConversationResponseData(BaseModel):
    conversation_id: int
    conversation_uuid: str
    recipient_user_id: int
    protection_mode: str
    is_saved_messages: bool = False


class GetConversationResponseData(BaseModel):
    conversation_id: int
    conversation_uuid: str
    title: str | None = None
    peer_user_id: int
    is_saved_messages: bool = False
    protection_mode: str
    message_ttl_days: int | None = None
    delete_after_read_seconds: int | None = None
    shared_secret_enabled: bool = False
    shared_secret_fingerprint: str | None = None
    shared_secret_updated_at: datetime | None = None
    peer_shared_secret_enabled: bool = False
    is_active: bool
    is_purged: bool
    is_pinned: bool = False
    pinned_message: MessagePreviewSchema | None = None


class UpdateConversationResponseData(BaseModel):
    conversation_id: int
    updated: bool


class ConversationSettingsResponseData(BaseModel):
    conversation_id: int
    user_id: int
    shared_secret_enabled: bool
    shared_secret_fingerprint: str | None = None
    shared_secret_updated_at: datetime | None = None


class ClearConversationResponseData(BaseModel):
    conversation_id: int
    scope: str
    cleared: bool
    cleared_at: str | None = None
    deleted_messages_count: int | None = None
    deleted_attachment_ids: list[int] = Field(default_factory=list)


class PinConversationResponseData(BaseModel):
    conversation_id: int
    is_pinned: bool


class DeleteConversationResponseData(BaseModel):
    conversation_id: int
    deleted: bool
    deleted_messages_count: int = 0
    deleted_attachment_ids: list[int] = Field(default_factory=list)


class ConversationPeerSchema(BaseModel):
    user_id: int
    nickname: str | None = None


class ConversationLastMessageSchema(BaseModel):
    message_id: int
    message_uuid: str
    sender_user_id: int
    sender_device_id: int
    recipient_user_id: int
    message_type: str
    client_created_at: datetime
    server_received_at: datetime
    has_attachments: bool


class ConversationListItemSchema(BaseModel):
    conversation_id: int
    conversation_uuid: str
    title: str | None = None
    is_saved_messages: bool = False
    protection_mode: ProtectionMode
    message_ttl_days: int | None = None
    delete_after_read_seconds: int | None = None
    shared_secret_enabled: bool = False
    shared_secret_fingerprint: str | None = None
    shared_secret_updated_at: datetime | None = None
    peer_shared_secret_enabled: bool = False
    is_active: bool
    is_purged: bool
    is_pinned: bool = False
    updated_at: datetime
    peer: ConversationPeerSchema
    unread_count: int = 0
    last_message: ConversationLastMessageSchema | None = None
    pinned_message: MessagePreviewSchema | None = None


class ListConversationsResponseData(BaseModel):
    items: list[ConversationListItemSchema] = Field(default_factory=list)
