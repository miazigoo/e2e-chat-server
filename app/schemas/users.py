from datetime import datetime

from pydantic import BaseModel, Field


class UserSearchItemSchema(BaseModel):
    """Compact public user record returned in search results."""

    user_id: int = Field(description="Internal numeric user identifier.")
    nickname: str = Field(description="Public nickname used to identify the user.")


class UserSearchResponseData(BaseModel):
    """Response payload with user search results."""

    items: list[UserSearchItemSchema] = Field(
        default_factory=list,
        description="Matched users ordered by nickname prefix.",
    )


class UserSafetyResponseData(BaseModel):
    """User state relevant for starting a secure conversation."""

    user_id: int = Field(description="Target user identifier.")
    nickname: str = Field(description="Target user nickname.")
    can_start_conversation: bool = Field(
        description="Whether the current user can start a conversation with this user."
    )
    is_deleted: bool = Field(description="Whether the account has been deleted.")
    pending_deletion: bool = Field(
        description="Whether the account is scheduled for deletion."
    )
    has_active_device: bool = Field(
        description="Whether the user has an active device."
    )
    supports_encrypted_chat: bool = Field(
        description="Whether encrypted chat is currently available for this user."
    )
    safety_code_available: bool = Field(
        description="Whether a safety code can be established for the user."
    )


class UserProfileSettingsSchema(BaseModel):
    """User preference block returned for the authenticated profile owner."""

    language_code: str = Field(description="Preferred UI language code.")
    theme: str = Field(description="Preferred application theme.")
    push_notifications_enabled: bool = Field(
        description="Master switch for push notifications."
    )
    apk_update_notifications_enabled: bool = Field(
        description="Whether app update notifications should be sent."
    )


class UserPublicProfileResponseData(BaseModel):
    """Publicly visible user profile payload."""

    user_id: int = Field(description="Internal numeric user identifier.")
    public_id: str = Field(description="Public UUID-like identifier for the user.")
    nickname: str = Field(description="Public nickname.")
    full_name: str | None = Field(default=None, description="Optional display name.")
    bio: str | None = Field(default=None, description="Optional profile biography.")
    avatar_url: str | None = Field(
        default=None,
        description="Temporary presigned avatar URL if the user has an avatar.",
    )
    avatar_updated_at: datetime | None = Field(
        default=None,
        description="Timestamp of the last avatar update.",
    )
    created_at: datetime = Field(description="Account creation timestamp.")


class UserProfileResponseData(UserPublicProfileResponseData):
    """Authenticated user's full profile including private settings."""

    settings: UserProfileSettingsSchema


class UpdateUserProfileRequest(BaseModel):
    """Patch request for updating the authenticated user's profile and settings."""

    nickname: str | None = Field(
        default=None,
        min_length=3,
        max_length=64,
        description="New public nickname.",
    )
    full_name: str | None = Field(
        default=None,
        max_length=255,
        description="Optional display name.",
    )
    bio: str | None = Field(
        default=None,
        max_length=1024,
        description="Optional short user biography.",
    )
    language_code: str | None = Field(
        default=None,
        min_length=2,
        max_length=16,
        description="Preferred UI language code.",
    )
    theme: str | None = Field(
        default=None,
        max_length=16,
        description="Preferred theme: light, dark or system.",
    )
    push_notifications_enabled: bool | None = Field(
        default=None,
        description="Enable or disable all push notifications.",
    )
    apk_update_notifications_enabled: bool | None = Field(
        default=None,
        description="Enable or disable application update notifications.",
    )
