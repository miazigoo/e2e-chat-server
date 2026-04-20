from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.db import get_db
from app.schemas.common import ApiResponse, HealthResponse

router = APIRouter(prefix="/health", tags=["health"])


@router.get("/live", response_model=ApiResponse[HealthResponse])
async def liveness() -> ApiResponse[HealthResponse]:
    """Simple liveness probe. Returns success if the app process is alive."""
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
    """Readiness probe. Verifies that core dependencies are reachable."""
    await session.execute(text("SELECT 1"))

    return ApiResponse(
        data=HealthResponse(
            ok=True,
            service=settings.app_name,
            env=settings.app_env,
        )
    )
