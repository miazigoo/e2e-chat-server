from datetime import datetime

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


class UserProfileSettingsSchema(BaseModel):
    language_code: str
    theme: str
    push_notifications_enabled: bool
    apk_update_notifications_enabled: bool


class UserPublicProfileResponseData(BaseModel):
    user_id: int
    public_id: str
    nickname: str
    full_name: str | None = None
    bio: str | None = None
    avatar_url: str | None = None
    avatar_updated_at: datetime | None = None
    created_at: datetime


class UserProfileResponseData(UserPublicProfileResponseData):
    settings: UserProfileSettingsSchema


class UpdateUserProfileRequest(BaseModel):
    nickname: str | None = Field(default=None, min_length=3, max_length=64)
    full_name: str | None = Field(default=None, max_length=255)
    bio: str | None = Field(default=None, max_length=1024)
    language_code: str | None = Field(default=None, min_length=2, max_length=16)
    theme: str | None = Field(default=None, max_length=16)
    push_notifications_enabled: bool | None = None
    apk_update_notifications_enabled: bool | None = None
