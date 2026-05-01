from pydantic import BaseModel, Field


class OneTimePreKeySchema(BaseModel):
    prekey_id: int = Field(ge=1)
    public_prekey: str = Field(min_length=1)


class RefillPreKeysRequest(BaseModel):
    prekeys: list[OneTimePreKeySchema] = Field(min_length=1, max_length=200)


class RotateSignedPreKeyRequest(BaseModel):
    signed_prekey_id: int = Field(default=1, ge=1)
    signed_prekey: str = Field(min_length=1)
    signed_prekey_signature: str = Field(min_length=1)


class KeyBundleResponseData(BaseModel):
    user_id: int
    device_id: int
    requested_by_device_id: int
    registration_id: int
    public_identity_key: str
    public_signing_key: str
    signed_prekey_id: int
    signed_prekey: str
    signed_prekey_signature: str
    one_time_prekey: OneTimePreKeySchema | None = None
    prekeys_remaining: int


class KeyBundleItemSchema(BaseModel):
    user_id: int
    device_id: int
    requested_by_device_id: int
    registration_id: int
    public_identity_key: str
    public_signing_key: str
    signed_prekey_id: int
    signed_prekey: str
    signed_prekey_signature: str
    one_time_prekey: OneTimePreKeySchema | None = None
    prekeys_remaining: int


class KeyBundlesResponseData(BaseModel):
    user_id: int
    devices: list[KeyBundleItemSchema]


class RefillPreKeysResponseData(BaseModel):
    device_id: int
    added: int
    prekeys_count: int


class RotateSignedPreKeyResponseData(BaseModel):
    device_id: int
    rotated: bool
