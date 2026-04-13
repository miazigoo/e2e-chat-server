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
