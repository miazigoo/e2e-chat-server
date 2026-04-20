from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.api.v1.health import router as health_router
from app.core.config import settings
from app.core.db import close_db, init_db
from app.core.error_handlers import register_error_handlers
from app.core.logging import setup_logging
from app.core.metrics import setup_metrics
from app.core.request_id import RequestIDMiddleware
from app.core.telemetry import setup_tracing


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Initialize and gracefully close application resources."""
    setup_logging()
    await init_db()
    yield
    await close_db()


app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    debug=settings.debug,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.backend_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestIDMiddleware)

setup_metrics(app)
setup_tracing(app, service_name=settings.app_name)

register_error_handlers(app)

app.include_router(api_router, prefix=settings.api_v1_prefix)
app.include_router(health_router)
