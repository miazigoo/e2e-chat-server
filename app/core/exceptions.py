from __future__ import annotations


class AppError(Exception):
    """
    Base application exception mapped to a unified API error response.
    """

    def __init__(
        self,
        *,
        code: str,
        message: str,
        status_code: int,
        details: dict[str, object] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


class BadRequestError(AppError):
    def __init__(
        self,
        message: str = "Bad request.",
        *,
        code: str = "BAD_REQUEST",
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(
            code=code,
            message=message,
            status_code=400,
            details=details,
        )


class UnauthorizedError(AppError):
    def __init__(
        self,
        message: str = "Authentication is required.",
        *,
        code: str = "UNAUTHORIZED",
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(
            code=code,
            message=message,
            status_code=401,
            details=details,
        )


class ForbiddenError(AppError):
    def __init__(
        self,
        message: str = "You do not have permission to perform this action.",
        *,
        code: str = "FORBIDDEN",
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(
            code=code,
            message=message,
            status_code=403,
            details=details,
        )


class NotFoundError(AppError):
    def __init__(
        self,
        message: str = "Requested resource was not found.",
        *,
        code: str = "NOT_FOUND",
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(
            code=code,
            message=message,
            status_code=404,
            details=details,
        )


class ConflictError(AppError):
    def __init__(
        self,
        message: str = "Resource conflict.",
        *,
        code: str = "CONFLICT",
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(
            code=code,
            message=message,
            status_code=409,
            details=details,
        )


class GoneError(AppError):
    def __init__(
        self,
        message: str = "Resource is no longer available.",
        *,
        code: str = "GONE",
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(
            code=code,
            message=message,
            status_code=410,
            details=details,
        )


class LockedError(AppError):
    def __init__(
        self,
        message: str = "Resource is locked.",
        *,
        code: str = "LOCKED",
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(
            code=code,
            message=message,
            status_code=423,
            details=details,
        )


class ValidationError(AppError):
    def __init__(
        self,
        message: str = "Request validation failed.",
        *,
        code: str = "VALIDATION_ERROR",
        details: dict[str, object] | None = None,
    ) -> None:
        super().__init__(
            code=code,
            message=message,
            status_code=422,
            details=details,
        )
