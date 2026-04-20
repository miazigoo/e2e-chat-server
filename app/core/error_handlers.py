from __future__ import annotations

import logging
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.exceptions import AppError
from app.schemas.common import ApiErrorResponse, ErrorBody, MetaSchema

logger = logging.getLogger(__name__)


def _get_request_id(request: Request) -> str | None:
    return getattr(request.state, "request_id", None)


def _api_error_response(
    *,
    request: Request,
    status_code: int,
    code: str,
    message: str,
) -> JSONResponse:
    payload = ApiErrorResponse(
        ok=False,
        error=ErrorBody(code=code, message=message),
        meta=MetaSchema(request_id=_get_request_id(request)),
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump())


def register_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return _api_error_response(
            request=request,
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
        )

    @app.exception_handler(HTTPException)
    async def handle_http_exception(
        request: Request,
        exc: HTTPException,
    ) -> JSONResponse:
        detail: Any = exc.detail

        if isinstance(detail, dict):
            code = str(detail.get("code", "HTTP_ERROR"))
            message = str(detail.get("message", "Request failed"))
        else:
            code = "HTTP_ERROR"
            message = str(detail or "Request failed")

        return _api_error_response(
            request=request,
            status_code=exc.status_code,
            code=code,
            message=message,
        )

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        logger.warning("Validation error", extra={"errors": exc.errors()})
        return _api_error_response(
            request=request,
            status_code=422,
            code="VALIDATION_ERROR",
            message="Request validation failed",
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        logger.exception("Unhandled application error", exc_info=exc)
        return _api_error_response(
            request=request,
            status_code=500,
            code="INTERNAL_ERROR",
            message="Internal server error",
        )
