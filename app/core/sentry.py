from __future__ import annotations

import sentry_sdk
from fastapi import FastAPI
from sentry_sdk.integrations.asyncio import AsyncioIntegration
from sentry_sdk.integrations.celery import CeleryIntegration
from sentry_sdk.integrations.fastapi import FastApiIntegration
from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

from app.core.config import settings


def setup_sentry(app: FastAPI) -> None:
    if not settings.sentry_dsn:
        return

    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment or settings.app_env,
        release=settings.sentry_release,
        integrations=[
            FastApiIntegration(),
            SqlalchemyIntegration(),
            CeleryIntegration(),
            AsyncioIntegration(),
        ],
        traces_sample_rate=0.2 if settings.app_env == "production" else 1.0,
        send_default_pii=False,
    )

    @app.get("/sentry-debug")
    async def sentry_debug() -> dict[str, str]:
        return {"status": "ok"}
