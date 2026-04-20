import redis.asyncio as redis
from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.schemas.common import ApiResponse, HealthResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=ApiResponse[HealthResponse])
async def liveness() -> ApiResponse[HealthResponse]:
    return ApiResponse(
        data=HealthResponse(
            ok=True,
            service=settings.app_name,
            env=settings.app_env,
        )
    )


@router.get("/ready", response_model=ApiResponse[HealthResponse])
async def readiness(
    session: AsyncSession = Depends(get_db),
) -> ApiResponse[HealthResponse]:
    await session.execute(text("SELECT 1"))

    redis_client = redis.from_url(settings.redis_url, decode_responses=True)
    try:
        await redis_client.ping()
    finally:
        await redis_client.close()

    return ApiResponse(
        data=HealthResponse(
            ok=True,
            service=settings.app_name,
            env=settings.app_env,
        )
    )
