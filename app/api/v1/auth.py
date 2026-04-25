from typing import Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.constants import COMMON_ERROR_RESPONSES
from app.core.db import get_db
from app.core.rate_limit import rate_limit_dependency
from app.dependencies.auth import (
    get_bootstrap_user,
    get_current_session,
    get_current_user,
)
from app.models.auth_session import AuthSession
from app.models.user import User
from app.schemas.auth import (
    Google2FAConfirmRequest,
    Google2FASetupResponseData,
    Google2FAStatusResponseData,
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
from app.schemas.devices import BootstrapDeviceRequest, BootstrapDeviceResponseData
from app.services.auth_service import (
    begin_google_2fa_setup,
    confirm_google_2fa_setup,
    disable_google_2fa,
    get_google_2fa_qr_png,
    login_user,
    logout_all_sessions,
    logout_current_session,
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
    dependencies=[
        Depends(
            rate_limit_dependency(
                prefix="auth:register",
                limit=10,
                window_seconds=60,
            )
        )
    ],
)
async def register(
    payload: RegisterRequest,
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[RegisterResponseData]:
    data = await register_user(session, payload)
    return ApiResponse(data=RegisterResponseData(**data))


@router.post(
    "/login",
    response_model=ApiResponse[LoginResponseData],
    summary="Authenticate user",
    description=(
        "Login by nickname and password. "
        "If email 2FA is enabled, returns a challenge instead of tokens."
    ),
    responses=AUTH_LOGIN_RESPONSES,
    dependencies=[
        Depends(
            rate_limit_dependency(
                prefix="auth:login",
                limit=20,
                window_seconds=60,
            )
        )
    ],
)
async def login(
    payload: LoginRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[LoginResponseData]:
    ip_address = request.client.host if request.client else None
    device_fingerprint = request.headers.get("X-Device-Fingerprint")
    user_agent = request.headers.get("User-Agent")

    data = await login_user(
        session,
        payload,
        ip_address=ip_address,
        device_fingerprint=device_fingerprint,
        user_agent=user_agent,
    )
    return ApiResponse(data=LoginResponseData(**data))


@router.post(
    "/login/verify-email-code",
    response_model=ApiResponse[VerifyEmailCodeResponseData],
    summary="Verify email 2FA code",
    description="Validate the email verification code and continue authentication.",
    responses=COMMON_ERROR_RESPONSES,
    dependencies=[
        Depends(
            rate_limit_dependency(
                prefix="auth:verify-email-code",
                limit=20,
                window_seconds=300,
            )
        )
    ],
)
async def verify_email_code_endpoint(
    payload: VerifyEmailCodeRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[VerifyEmailCodeResponseData]:
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("User-Agent")

    data = await verify_email_code(
        session,
        payload,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return ApiResponse(data=VerifyEmailCodeResponseData(**data))


@router.post(
    "/2fa/google/setup",
    response_model=ApiResponse[Google2FASetupResponseData],
    summary="Begin Google TOTP 2FA setup",
    description=(
        "Generate a pending Google Authenticator compatible secret " "and otpauth URI."
    ),
    responses=COMMON_ERROR_RESPONSES,
)
async def begin_google_2fa_setup_endpoint(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[Google2FASetupResponseData]:
    data = await begin_google_2fa_setup(session, current_user=current_user)
    return ApiResponse(data=Google2FASetupResponseData(**data))


@router.post(
    "/2fa/google/confirm",
    response_model=ApiResponse[Google2FAStatusResponseData],
    summary="Confirm Google TOTP 2FA setup",
    description="Validate the TOTP code from Google Authenticator and enable 2FA.",
    responses=COMMON_ERROR_RESPONSES,
)
async def confirm_google_2fa_setup_endpoint(
    payload: Google2FAConfirmRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[Google2FAStatusResponseData]:
    data = await confirm_google_2fa_setup(
        session,
        current_user=current_user,
        payload=payload,
    )
    return ApiResponse(data=Google2FAStatusResponseData(**data))


@router.delete(
    "/2fa/google",
    response_model=ApiResponse[Google2FAStatusResponseData],
    summary="Disable Google TOTP 2FA",
    description="Disable Google Authenticator based 2FA for the authenticated user.",
    responses=COMMON_ERROR_RESPONSES,
)
async def disable_google_2fa_endpoint(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[Google2FAStatusResponseData]:
    data = await disable_google_2fa(session, current_user=current_user)
    return ApiResponse(data=Google2FAStatusResponseData(**data))


@router.get(
    "/2fa/google/qr",
    summary="Get Google TOTP setup QR",
    description="Render the current pending Google TOTP setup as a PNG QR code.",
    responses=COMMON_ERROR_RESPONSES,
)
async def get_google_2fa_qr_endpoint(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> Response:
    png_bytes = await get_google_2fa_qr_png(session, current_user=current_user)
    return Response(content=png_bytes, media_type="image/png")


@router.post(
    "/refresh",
    response_model=ApiResponse[RefreshResponseData],
    summary="Refresh access token",
    description="Rotate refresh token and issue a new access token.",
    responses=COMMON_ERROR_RESPONSES,
    dependencies=[
        Depends(
            rate_limit_dependency(
                prefix="auth:refresh",
                limit=30,
                window_seconds=60,
            )
        )
    ],
)
async def refresh_token(
    payload: RefreshRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[RefreshResponseData]:
    ip_address = request.client.host if request.client else None
    user_agent = request.headers.get("User-Agent")

    data = await refresh_access_token(
        session,
        payload,
        ip_address=ip_address,
        user_agent=user_agent,
    )
    return ApiResponse(data=RefreshResponseData(**data))


@router.post(
    "/bootstrap",
    response_model=ApiResponse[BootstrapDeviceResponseData],
    summary="Register or update device bootstrap data",
    description=(
        "Register device keys, signed prekey and one-time prekeys. "
        "Accepts either a bootstrap token or a normal access token."
    ),
    responses=COMMON_ERROR_RESPONSES,
    dependencies=[
        Depends(
            rate_limit_dependency(
                prefix="auth:bootstrap",
                limit=20,
                window_seconds=60,
            )
        )
    ],
)
async def bootstrap(
    payload: BootstrapDeviceRequest,
    bootstrap_user: User = Depends(get_bootstrap_user),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[BootstrapDeviceResponseData]:
    data = await bootstrap_device(
        session,
        current_user=bootstrap_user,
        payload=payload,
    )
    return ApiResponse(data=BootstrapDeviceResponseData(**data))


@router.post(
    "/logout",
    response_model=ApiResponse[LogoutResponseData],
    summary="Logout current session",
    description="Revoke the current authenticated session.",
    responses=COMMON_ERROR_RESPONSES,
)
async def logout(
    current_session: AuthSession = Depends(get_current_session),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[LogoutResponseData]:
    data = await logout_current_session(
        session,
        current_session=current_session,
    )
    return ApiResponse(data=LogoutResponseData(**data))


@router.post(
    "/logout-all",
    response_model=ApiResponse[LogoutAllResponseData],
    summary="Logout all sessions",
    description="Revoke all authenticated sessions for the current user.",
    responses=COMMON_ERROR_RESPONSES,
)
async def logout_all(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[LogoutAllResponseData]:
    data = await logout_all_sessions(
        session,
        user_id=current_user.id,
    )
    return ApiResponse(data=LogoutAllResponseData(**data))
