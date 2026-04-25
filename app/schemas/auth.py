from __future__ import annotations

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    nickname: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=256)
    email: EmailStr | None = None
    email_2fa_enabled: bool = False


class RegisterResponseData(BaseModel):
    user_id: int
    nickname: str
    requires_device_registration: bool = True
    bootstrap_token: str | None = None
    bootstrap_expires_in: int | None = None


class LoginRequest(BaseModel):
    nickname: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=256)
    device_uuid: str | None = Field(default=None, min_length=1, max_length=128)
    totp_code: str | None = Field(default=None, min_length=6, max_length=8)


class LoginResponseData(BaseModel):
    requires_email_code: bool
    requires_totp: bool = False
    requires_bootstrap: bool = False
    login_challenge_id: str | None = None
    email_masked: str | None = None
    debug_code: str | None = None
    bootstrap_token: str | None = None
    bootstrap_expires_in: int | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    expires_in: int | None = None


class VerifyEmailCodeRequest(BaseModel):
    login_challenge_id: str
    code: str = Field(min_length=6, max_length=6)
    device_uuid: str | None = Field(default=None, min_length=1, max_length=128)


class VerifyEmailCodeResponseData(BaseModel):
    requires_bootstrap: bool = False
    bootstrap_token: str | None = None
    bootstrap_expires_in: int | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    expires_in: int | None = None


class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponseData(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int


class LogoutResponseData(BaseModel):
    message: str
    revoked_sessions: int


class LogoutAllResponseData(BaseModel):
    message: str
    revoked_sessions: int


class Google2FASetupResponseData(BaseModel):
    secret: str
    provisioning_uri: str
    issuer: str
    account_name: str


class Google2FAConfirmRequest(BaseModel):
    code: str = Field(min_length=6, max_length=8)


class Google2FAStatusResponseData(BaseModel):
    enabled: bool
    confirmed_at: str | None = None
