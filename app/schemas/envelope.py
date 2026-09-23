"""Canonical {data, error} envelope used by every HTTP response."""

from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class ApiErrorDetail(BaseModel):
    """Per-field validation problem."""

    field: str
    message: str


class ApiError(BaseModel):
    """Machine-readable error payload. `details` is omitted when unused."""

    code: str
    message: str
    details: list[ApiErrorDetail] | None = None


class ApiResponse(BaseModel, Generic[T]):
    """Success or failure envelope. Exactly one of data/error is meaningful."""

    data: T | None = None
    error: ApiError | None = None


def success(data: Any) -> dict[str, Any]:
    """Wrap a successful payload."""
    return {"data": data, "error": None}


def failure(
    code: str,
    message: str,
    details: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Wrap an error. `data` is always null."""
    error: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        error["details"] = details
    return {"data": None, "error": error}


class HealthGeminiStatus(BaseModel):
    """Masked Gemini key-pool snapshot."""

    configured: bool
    keys: list[str] = Field(default_factory=list)
    available: int = 0
    cooling_down: int = 0
    disabled: int = 0


class HealthData(BaseModel):
    """Body of GET /health."""

    status: str
    database: str
    gemini: HealthGeminiStatus
