from __future__ import annotations

from typing import Any

import anyio
import redis.asyncio as redis
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.config import settings
from app.core.db import AsyncSessionLocal
from app.core.storage import bucket_exists
from app.schemas.common import ApiResponse, HealthResponse
from app.worker.celery_app import celery_app

router = APIRouter(prefix="/health", tags=["health"])


async def _check_db() -> bool:
    async with AsyncSessionLocal() as session:
        await session.execute(text("SELECT 1"))
    return True


async def _check_redis() -> bool:
    client = redis.from_url(settings.redis_url, decode_responses=True)
    try:
        return bool(await client.ping())
    finally:
        await client.close()


def _check_rabbitmq_sync() -> bool:
    with celery_app.connection_for_read() as conn:
        conn.ensure_connection(max_retries=1)
    return True


async def _check_minio() -> bool:
    attachments_ok = await bucket_exists(settings.minio_bucket_attachments)
    temp_ok = await bucket_exists(settings.minio_bucket_temp)
    return attachments_ok and temp_ok


@router.get(
    "/live",
    response_model=ApiResponse[HealthResponse],
    include_in_schema=False,
)
async def live() -> ApiResponse[HealthResponse]:
    return ApiResponse(
        data=HealthResponse(
            ok=True,
            service=settings.app_name,
            env=settings.app_env,
        )
    )


@router.get("/ready", include_in_schema=False)
async def ready() -> JSONResponse:
    checks: dict[str, Any] = {}
    ok = True

    async def run_check(name: str, check_coro: Any) -> None:
        nonlocal ok
        try:
            result = await check_coro
            checks[name] = {"ok": bool(result)}
            if not result:
                ok = False
        except Exception as exc:
            checks[name] = {"ok": False, "error": exc.__class__.__name__}
            ok = False

    await run_check("database", _check_db())
    await run_check("redis", _check_redis())
    await run_check("minio", _check_minio())
    await run_check(
        "rabbitmq",
        anyio.to_thread.run_sync(_check_rabbitmq_sync),
    )

    payload = {
        "ok": ok,
        "data": {
            "ok": ok,
            "service": settings.app_name,
            "env": settings.app_env,
            "checks": checks,
        },
        "meta": {},
    }

    return JSONResponse(status_code=200 if ok else 503, content=payload)
