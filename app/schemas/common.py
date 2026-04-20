from typing import Generic, Optional, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class MetaSchema(BaseModel):
    request_id: Optional[str] = None


class ApiResponse(BaseModel, Generic[T]):
    ok: bool = True
    data: T
    meta: MetaSchema = Field(default_factory=MetaSchema)


class ErrorBody(BaseModel):
    code: str
    message: str


class ApiErrorResponse(BaseModel):
    ok: bool = False
    error: ErrorBody
    meta: MetaSchema = Field(default_factory=MetaSchema)


class HealthResponse(BaseModel):
    ok: bool
    service: str
    env: str
