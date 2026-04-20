from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.api.router import api_router
from app.api.v1.health import router as health_router
from app.api.v1.ws import bind_realtime_handlers
from app.core.config import settings
from app.core.db import close_db, init_db
from app.core.error_handlers import register_error_handlers
from app.core.logging import setup_logging
from app.core.metrics import setup_metrics
from app.core.rate_limit import rate_limiter
from app.core.realtime import realtime_hub
from app.core.request_id import RequestIDMiddleware
from app.core.sentry import setup_sentry
from app.core.telemetry import setup_tracing
from app.core.unread_cache import unread_cache


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    setup_logging()
    bind_realtime_handlers()
    await init_db()
    await rate_limiter.start()
    await unread_cache.start()
    await realtime_hub.start()
    yield
    await realtime_hub.stop()
    await unread_cache.stop()
    await rate_limiter.stop()
    await close_db()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    debug=settings.debug,
    lifespan=lifespan,
)

allow_credentials = settings.backend_cors_origins != ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.backend_cors_origins,
    allow_credentials=allow_credentials,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestIDMiddleware)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=(
        ["*"] if settings.app_env != "production" else ["localhost", "127.0.0.1"]
    ),
)

setup_metrics(app)
setup_tracing(app, service_name=settings.app_name)
setup_sentry(app)

register_error_handlers(app)

app.include_router(api_router, prefix=settings.api_v1_prefix)
app.include_router(health_router)
