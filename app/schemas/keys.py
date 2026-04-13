from pydantic import BaseModel, Field


class OneTimePreKeySchema(BaseModel):
    prekey_id: int = Field(ge=1)
    public_prekey: str = Field(min_length=1)


class RefillPreKeysRequest(BaseModel):
    prekeys: list[OneTimePreKeySchema] = Field(min_length=1, max_length=200)


class RotateSignedPreKeyRequest(BaseModel):
    signed_prekey: str = Field(min_length=1)
    signed_prekey_signature: str = Field(min_length=1)
