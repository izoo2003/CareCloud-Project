"""JSON logging, request-id middleware, and secret-masking helpers."""

from __future__ import annotations

import contextvars
import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from pythonjsonlogger.json import JsonFormatter
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

REQUEST_ID_HEADER = "X-Request-ID"
_request_id_ctx: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id",
    default="-",
)


class RequestIdFilter(logging.Filter):
    """Attach the current request id to every log record."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = _request_id_ctx.get()
        return True


def mask_secret(value: str, *, prefix: int = 4, suffix: int = 4) -> str:
    """Mask an API key for logs, e.g. AIza...x9Q2. Never log the full value."""
    if not value:
        return ""
    if len(value) <= prefix + suffix:
        return "****"
    return f"{value[:prefix]}...{value[-suffix:]}"


def mask_phone(phone: str) -> str:
    """Keep only the last four digits of a phone number for casual logs."""
    digits = "".join(char for char in phone if char.isdigit())
    if len(digits) < 4:
        return "****"
    return f"***-***-{digits[-4:]}"


def configure_logging(level: str) -> None:
    """Send structured JSON logs to stdout. Replaces any inherited handlers."""
    handler = logging.StreamHandler()
    handler.setFormatter(
        JsonFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s %(request_id)s",
            timestamp=True,
        )
    )
    handler.addFilter(RequestIdFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level.upper())

    # Keep third-party access logs from drowning out our JSON lines.
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Propagate or mint a request id and emit one access log per request."""

    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or str(uuid.uuid4())
        request.state.request_id = request_id
        token = _request_id_ctx.set(request_id)
        started = time.perf_counter()
        access = logging.getLogger("app.http")
        try:
            response = await call_next(request)
        except Exception:
            access.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": 500,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )
            raise
        else:
            response.headers[REQUEST_ID_HEADER] = request_id
            access.info(
                "request",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "status_code": response.status_code,
                    "duration_ms": round((time.perf_counter() - started) * 1000, 1),
                },
            )
            return response
        finally:
            _request_id_ctx.reset(token)
