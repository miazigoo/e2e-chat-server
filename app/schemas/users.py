from pydantic import BaseModel, Field


class UserSearchItemSchema(BaseModel):
    user_id: int
    nickname: str


class UserSearchResponseData(BaseModel):
    items: list[UserSearchItemSchema] = Field(default_factory=list)


class UserSafetyResponseData(BaseModel):
    user_id: int
    nickname: str
    can_start_conversation: bool
    is_deleted: bool
    pending_deletion: bool
    has_active_device: bool
    supports_encrypted_chat: bool
    safety_code_available: bool
