from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.models.chat_enums import EventType


class ConversationEventItemSchema(BaseModel):
    event_id: int
    event_uuid: str
    event_type: EventType
    actor_user_id: int | None = None
    actor_device_id: int | None = None
    target_message_id: int | None = None
    payload: dict[str, Any] | None = None
    created_at: datetime


class ConversationEventsResponseData(BaseModel):
    conversation_id: int
    items: list[ConversationEventItemSchema] = Field(default_factory=list)
    next_after_event_id: int | None = None
    has_more: bool
