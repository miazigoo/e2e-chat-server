from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import COMMON_ERROR_RESPONSES
from app.core.db import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    LoginResponseData,
    LogoutAllResponseData,
    LogoutResponseData,
    RefreshRequest,
    RefreshResponseData,
    RegisterRequest,
    RegisterResponseData,
    VerifyEmailCodeRequest,
    VerifyEmailCodeResponseData,
)
from app.schemas.common import ApiErrorResponse, ApiResponse
from app.schemas.devices import BootstrapDeviceRequest
from app.services.auth_service import (
    login_user,
    refresh_access_token,
    register_user,
    verify_email_code,
)
from app.services.device_service import bootstrap_device

router = APIRouter()

AUTH_LOGIN_RESPONSES: dict[int | str, dict[str, Any]] = {
    **COMMON_ERROR_RESPONSES,
    423: {
        "model": ApiErrorResponse,
        "description": "Account temporarily locked",
    },
}


@router.post(
    "/register",
    response_model=ApiResponse[RegisterResponseData],
    summary="Register user",
    description="Create a new user account with nickname and password.",
    responses=COMMON_ERROR_RESPONSES,
)
async def register(
    payload: RegisterRequest,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    data = await register_user(session, payload)
    return {
        "ok": True,
        "data": data,
        "meta": {},
    }


@router.post(
    "/login",
    response_model=ApiResponse[LoginResponseData],
    summary="Authenticate user",
    description=(
        "Login by nickname and password. "
        "If email 2FA is enabled, returns a challenge instead of tokens."
    ),
    responses=AUTH_LOGIN_RESPONSES,
)
async def login(
    payload: LoginRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Authenticate the user and return tokens or 2FA challenge."""
    ip_address = request.client.host if request.client else None
    device_fingerprint = request.headers.get("X-Device-Fingerprint")

    data = await login_user(
        session,
        payload,
        ip_address=ip_address,
        device_fingerprint=device_fingerprint,
    )
    return {
        "ok": True,
        "data": data,
        "meta": {},
    }


@router.post(
    "/login/verify-email-code",
    response_model=ApiResponse[VerifyEmailCodeResponseData],
    summary="Verify email 2FA code",
    description=(
        "Validate the email verification code " "and issue access and refresh tokens."
    ),
    responses=COMMON_ERROR_RESPONSES,
)
async def verify_email_code_endpoint(
    payload: VerifyEmailCodeRequest,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    data = await verify_email_code(session, payload)
    return {
        "ok": True,
        "data": data,
        "meta": {},
    }


@router.post(
    "/refresh",
    response_model=ApiResponse[RefreshResponseData],
    summary="Refresh access token",
    description="Issue a new access token using a valid refresh token.",
    responses=COMMON_ERROR_RESPONSES,
)
async def refresh_token(
    payload: RefreshRequest,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    data = await refresh_access_token(session, payload)
    return {
        "ok": True,
        "data": data,
        "meta": {},
    }


@router.post(
    "/bootstrap",
    summary="Register or update device bootstrap data",
    description=(
        "Register device keys, signed prekey and one-time prekeys "
        "for the authenticated user."
    ),
    responses=COMMON_ERROR_RESPONSES,
)
async def bootstrap(
    payload: BootstrapDeviceRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    data = await bootstrap_device(
        session,
        current_user=current_user,
        payload=payload,
    )
    return {
        "ok": True,
        "data": data,
        "meta": {},
    }


@router.post(
    "/logout",
    response_model=ApiResponse[LogoutResponseData],
    summary="Logout current session",
    description="Revoke the current authenticated session.",
    responses=COMMON_ERROR_RESPONSES,
)
async def logout() -> dict[str, Any]:
    return {
        "ok": True,
        "data": {
            "message": "Logged out",
        },
        "meta": {},
    }


@router.post(
    "/logout-all",
    response_model=ApiResponse[LogoutAllResponseData],
    summary="Logout all sessions",
    description=("Revoke all authenticated sessions " "for the current user."),
    responses=COMMON_ERROR_RESPONSES,
)
async def logout_all() -> dict[str, Any]:
    return {
        "ok": True,
        "data": {
            "message": "All sessions revoked",
        },
        "meta": {},
    }
