from typing import Optional

from pydantic import BaseModel, EmailStr, Field


class RegisterRequest(BaseModel):
    nickname: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8, max_length=256)
    email: Optional[EmailStr] = None
    email_2fa_enabled: bool = False


class LoginRequest(BaseModel):
    nickname: str
    password: str


class VerifyEmailCodeRequest(BaseModel):
    login_challenge_id: str
    code: str = Field(min_length=6, max_length=6)


class RefreshRequest(BaseModel):
    refresh_token: str
