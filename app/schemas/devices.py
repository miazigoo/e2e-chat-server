from datetime import datetime

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class OneTimePreKeyRequest(BaseModel):
    prekey_id: int = Field(ge=1)
    public_prekey: str = Field(min_length=1)


class BootstrapDeviceRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    device_uuid: str = Field(min_length=1)
    device_name: str = Field(min_length=1, max_length=255)
    platform: str = Field(default="android", min_length=1, max_length=32)
    app_version: str = Field(min_length=1, max_length=64)
    fcm_token: str | None = None

    registration_id: int = Field(ge=1)
    public_identity_key: str = Field(min_length=1)
    public_signing_key: str = Field(min_length=1)
    signed_prekey_id: int = Field(default=1, ge=1)
    signed_prekey: str = Field(min_length=1)
    signed_prekey_signature: str = Field(min_length=1)

    one_time_prekeys: list[OneTimePreKeyRequest] = Field(
        default_factory=list,
        max_length=200,
        validation_alias=AliasChoices("one_time_prekeys", "prekeys"),
        serialization_alias="one_time_prekeys",
    )


class BootstrapDeviceResponseData(BaseModel):
    device_id: int
    device_uuid: str
    is_active: bool
    prekeys_count: int
    last_seen_at: str | None = None


class UpdateFcmTokenRequest(BaseModel):
    fcm_token: str | None = Field(default=None, max_length=4096)


class DeviceHeartbeatResponseData(BaseModel):
    device_id: int
    device_uuid: str
    status: str
    last_seen_at: datetime


class UpdateFcmTokenResponseData(BaseModel):
    device_id: int
    updated: bool
    fcm_token_present: bool
    last_seen_at: datetime | None = None


class RevokeCurrentDeviceResponseData(BaseModel):
    device_id: int
    revoked: bool
    revoked_sessions: int
    revoked_at: datetime


class DeviceListItemSchema(BaseModel):
    device_id: int
    device_uuid: str
    device_name: str
    platform: str
    app_version: str
    is_current: bool = False
    fcm_token_present: bool = False
    registered_at: datetime
    last_seen_at: datetime | None = None


class ListDevicesResponseData(BaseModel):
    items: list[DeviceListItemSchema]


class RevokeDeviceResponseData(BaseModel):
    device_id: int
    revoked: bool
    revoked_sessions: int
    revoked_at: datetime


class DeviceAuthorizationRequestSchema(BaseModel):
    request_id: str
    device_uuid: str
    device_name: str | None = None
    platform: str | None = None
    app_version: str | None = None
    ip_address: str | None = None
    user_agent: str | None = None
    requested_at: datetime
    expires_at: datetime


class ListDeviceAuthorizationRequestsResponseData(BaseModel):
    items: list[DeviceAuthorizationRequestSchema]


class ResolveDeviceAuthorizationRequestResponseData(BaseModel):
    request_id: str
    status: str
    bootstrap_available: bool = False
