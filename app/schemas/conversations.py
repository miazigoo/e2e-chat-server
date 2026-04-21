from datetime import datetime

from pydantic import BaseModel, Field

from app.models.chat_enums import ProtectionMode


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


class CreateConversationResponseData(BaseModel):
    conversation_id: int
    conversation_uuid: str
    recipient_user_id: int
    protection_mode: str


class GetConversationResponseData(BaseModel):
    conversation_id: int
    conversation_uuid: str
    title: str | None = None
    peer_user_id: int
    protection_mode: str
    message_ttl_days: int | None = None
    delete_after_read_seconds: int | None = None
    is_active: bool
    is_purged: bool


class UpdateConversationResponseData(BaseModel):
    conversation_id: int
    updated: bool


class ClearConversationResponseData(BaseModel):
    conversation_id: int
    scope: str
    cleared: bool
    cleared_at: str | None = None
    deleted_messages_count: int | None = None
    deleted_attachment_ids: list[int] = Field(default_factory=list)


class ConversationPeerSchema(BaseModel):
    user_id: int
    nickname: str | None = None


class ConversationLastMessageSchema(BaseModel):
    message_id: int
    message_uuid: str
    sender_user_id: int
    recipient_user_id: int
    message_type: str
    client_created_at: datetime
    server_received_at: datetime
    has_attachments: bool


class ConversationListItemSchema(BaseModel):
    conversation_id: int
    conversation_uuid: str
    title: str | None = None
    protection_mode: ProtectionMode
    message_ttl_days: int | None = None
    delete_after_read_seconds: int | None = None
    is_active: bool
    is_purged: bool
    updated_at: datetime
    peer: ConversationPeerSchema
    unread_count: int = 0
    last_message: ConversationLastMessageSchema | None = None


class ListConversationsResponseData(BaseModel):
    items: list[ConversationListItemSchema] = Field(default_factory=list)
