from __future__ import annotations

from typing import Literal

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


class LoginRequest(BaseModel):
    nickname: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=256)


class Login2FAChallengeData(BaseModel):
    requires_email_code: Literal[True] = True
    login_challenge_id: str
    email_masked: str | None = None
    debug_code: str | None = None


class LoginSuccessData(BaseModel):
    requires_email_code: Literal[False] = False
    access_token: str
    refresh_token: str
    expires_in: int


class LoginResponseData(BaseModel):
    requires_email_code: bool
    login_challenge_id: str | None = None
    email_masked: str | None = None
    debug_code: str | None = None
    access_token: str | None = None
    refresh_token: str | None = None
    expires_in: int | None = None


class VerifyEmailCodeRequest(BaseModel):
    login_challenge_id: str
    code: str = Field(min_length=6, max_length=6)


class VerifyEmailCodeResponseData(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int


class RefreshRequest(BaseModel):
    refresh_token: str


class RefreshResponseData(BaseModel):
    access_token: str
    expires_in: int


class LogoutResponseData(BaseModel):
    message: str


class LogoutAllResponseData(BaseModel):
    message: str
    revoked_sessions: int
