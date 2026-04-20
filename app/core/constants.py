from typing import Any

from app.schemas.common import ApiErrorResponse

COMMON_ERROR_RESPONSES: dict[int | str, dict[str, Any]] = {
    400: {"model": ApiErrorResponse, "description": "Bad request."},
    401: {
        "model": ApiErrorResponse,
        "description": "Authentication failed or missing.",
    },
    403: {"model": ApiErrorResponse, "description": "Operation is forbidden."},
    404: {"model": ApiErrorResponse, "description": "Resource was not found."},
    409: {
        "model": ApiErrorResponse,
        "description": "Conflict with current resource state.",
    },
    410: {"model": ApiErrorResponse, "description": "Resource is no longer available."},
    422: {"model": ApiErrorResponse, "description": "Request validation error."},
    423: {"model": ApiErrorResponse, "description": "Resource is locked."},
    429: {"model": ApiErrorResponse, "description": "Too many requests."},
    500: {"model": ApiErrorResponse, "description": "Internal server error."},
}
