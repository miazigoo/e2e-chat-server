from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.auth import (
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    VerifyEmailCodeRequest,
)
from app.schemas.devices import BootstrapDeviceRequest
from app.services.auth_service import (
    login_user,
    refresh_access_token,
    register_user,
    verify_email_code,
)
from app.services.device_service import bootstrap_device

router = APIRouter()


@router.post("/register")
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


@router.post("/login")
async def login(
    payload: LoginRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
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


@router.post("/login/verify-email-code")
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


@router.post("/refresh")
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


@router.post("/bootstrap")
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


@router.post("/logout")
async def logout() -> dict[str, Any]:
    return {
        "ok": True,
        "data": {
            "message": "Logged out",
        },
        "meta": {},
    }


@router.post("/logout-all")
async def logout_all() -> dict[str, Any]:
    return {
        "ok": True,
        "data": {
            "message": "All sessions revoked",
        },
        "meta": {},
    }
