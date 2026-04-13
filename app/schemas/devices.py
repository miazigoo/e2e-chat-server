from pydantic import BaseModel, Field


class OneTimePreKeyRequest(BaseModel):
    prekey_id: int = Field(ge=1)
    public_prekey: str = Field(min_length=1)


class BootstrapDeviceRequest(BaseModel):
    device_uuid: str = Field(min_length=1)
    device_name: str = Field(min_length=1, max_length=255)
    platform: str = Field(default="android", min_length=1, max_length=32)
    app_version: str = Field(min_length=1, max_length=64)
    fcm_token: str | None = None

    public_identity_key: str = Field(min_length=1)
    public_signing_key: str = Field(min_length=1)
    signed_prekey: str = Field(min_length=1)
    signed_prekey_signature: str = Field(min_length=1)

    one_time_prekeys: list[OneTimePreKeyRequest] = Field(
        default_factory=list, max_length=200
    )
