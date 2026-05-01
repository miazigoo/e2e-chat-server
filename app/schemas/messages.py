from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.models.chat_enums import EncryptionMode, MessageType


class SendMessageRequest(BaseModel):
    """Client request for creating a new message in a conversation."""

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
    device_payloads: list["MessageDevicePayloadRequest"] = Field(
        default_factory=list,
        max_length=100,
    )

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

    @field_validator("device_payloads")
    @classmethod
    def validate_device_payloads_unique(
        cls, value: list["MessageDevicePayloadRequest"]
    ) -> list["MessageDevicePayloadRequest"]:
        device_ids = [item.device_id for item in value]
        if len(device_ids) != len(set(device_ids)):
            raise ValueError("device_payloads device_id values must be unique")
        return value


class MessageDevicePayloadRequest(BaseModel):
    device_id: int = Field(ge=1)
    ciphertext: str = Field(min_length=1)
    ciphertext_version: int = Field(default=1, ge=1)
    nonce: str = Field(min_length=1)
    aad_hash: str | None = None


class MessageDevicePayloadSchema(BaseModel):
    device_id: int
    ciphertext: str
    ciphertext_version: int
    nonce: str
    aad_hash: str | None = None


class ForwardMessagesRequest(BaseModel):
    """Batch request for forwarding existing messages into another conversation."""

    conversation_id: int
    recipient_user_id: int
    message_ids: list[int] = Field(min_length=1, max_length=50)
    client_created_at: datetime | None = None

    @field_validator("message_ids")
    @classmethod
    def validate_message_ids_unique(cls, value: list[int]) -> list[int]:
        if len(value) != len(set(value)):
            raise ValueError("message_ids must be unique")
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


class SetMessageReactionRequest(BaseModel):
    reaction: str = Field(min_length=1, max_length=32)

    @field_validator("reaction")
    @classmethod
    def validate_reaction(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("reaction must not be blank")
        return value


class SendMessageResponseData(BaseModel):
    """Server acknowledgement for a newly accepted message."""

    message_id: int
    message_uuid: str
    conversation_id: int
    recipient_user_id: int
    recipient_device_id: int
    recipient_device_ids: list[int] = Field(default_factory=list)
    server_received_at: datetime
    delivery_status: str
    is_idempotent_replay: bool = False


class ForwardedMessageItemSchema(BaseModel):
    """Mapping between a source message and the newly created forwarded message."""

    source_message_id: int
    message_id: int
    message_uuid: str
    recipient_device_id: int
    recipient_device_ids: list[int] = Field(default_factory=list)
    server_received_at: datetime


class ForwardMessagesResponseData(BaseModel):
    """Response payload for batch forwarding."""

    conversation_id: int
    recipient_user_id: int
    items: list[ForwardedMessageItemSchema] = Field(default_factory=list)


class MessageReactionSummarySchema(BaseModel):
    """Reaction aggregate for one emoji/reaction string on a message."""

    reaction: str
    count: int
    me: bool = False


class MessagePreviewSchema(BaseModel):
    """Compact message preview used for replies, forwards and pinned messages."""

    message_id: int
    message_uuid: str
    sender_user_id: int
    message_type: MessageType
    ciphertext: str
    ciphertext_version: int | None = None
    nonce: str | None = None
    aad_hash: str | None = None
    device_payload: MessageDevicePayloadSchema | None = None
    has_attachments: bool
    client_created_at: datetime


class MessageListItemSchema(BaseModel):
    """Expanded message item returned in history, search and shared tabs."""

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
    device_payload: MessageDevicePayloadSchema | None = None
    client_created_at: datetime
    server_received_at: datetime
    delivered_at: datetime | None = None
    read_at: datetime | None = None
    expires_at: datetime
    has_attachments: bool
    reply_to_message_id: int | None = None
    forward_from_message_id: int | None = None
    reply_preview: MessagePreviewSchema | None = None
    forward_preview: MessagePreviewSchema | None = None
    reactions: list[MessageReactionSummarySchema] = Field(default_factory=list)


class ListMessagesResponseData(BaseModel):
    """Paginated message history response."""

    items: list[MessageListItemSchema] = Field(default_factory=list)
    before_cursor: int | None = None
    after_cursor: int | None = None
    has_more_before: bool = False
    has_more_after: bool = False
    anchor_message_id: int | None = None


class SearchMessagesResponseData(BaseModel):
    """Conversation-local message search results."""

    conversation_id: int
    query: str
    items: list[MessageListItemSchema] = Field(default_factory=list)


class SharedTabCountsSchema(BaseModel):
    """Counters for shared content tabs similar to Telegram media sections."""

    media: int = 0
    links: int = 0
    files: int = 0


class SharedMessagesResponseData(BaseModel):
    """Items for one shared-content tab together with tab counters."""

    conversation_id: int
    tab: str
    counts: SharedTabCountsSchema
    items: list[MessageListItemSchema] = Field(default_factory=list)


class MarkDeliveredResponseData(BaseModel):
    """Delivery acknowledgement response."""

    message_id: int
    status: str
    delivered_at: datetime


class MarkReadResponseData(BaseModel):
    """Read acknowledgement response."""

    message_id: int
    status: str
    read_at: datetime


class DeleteMessagesResponseData(BaseModel):
    """Deletion result for local or global delete operations."""

    deleted: bool
    scope: str
    message_ids: list[int] = Field(default_factory=list)


class SetMessageReactionResponseData(BaseModel):
    """Result of setting or replacing a reaction on a message."""

    message_id: int
    reaction: str
    updated: bool


class DeleteMessageReactionResponseData(BaseModel):
    """Result of removing the current user's reaction from a message."""

    message_id: int
    removed: bool


class PinMessageResponseData(BaseModel):
    """Result of pinning or unpinning a conversation message."""

    conversation_id: int
    message_id: int | None = None
    pinned: bool
