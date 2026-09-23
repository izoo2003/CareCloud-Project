"""FastAPI application factory, routers, and exception handlers."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.health import router as health_router
from app.api.llm_proxy import router as llm_router
from app.api.patients import router as patients_router
from app.api.vapi import router as vapi_router
from app.config import get_settings
from app.core.errors import DatabaseUnavailable, NotFound, ValidationFailed
from app.core.logging import RequestIdMiddleware, configure_logging
from app.db.session import dispose_engine
from app.llm.key_pool import get_key_pool
from app.schemas.envelope import failure

logger = logging.getLogger(__name__)

_HTTP_ERROR_CODES = {
    400: "BAD_REQUEST",
    401: "UNAUTHORIZED",
    404: "NOT_FOUND",
    422: "VALIDATION_ERROR",
    500: "INTERNAL_ERROR",
    503: "INTERNAL_ERROR",
}


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Configure logging on boot; dispose the engine on shutdown."""
    settings = get_settings()
    configure_logging(settings.log_level)
    get_key_pool()
    logger.info("startup", extra={"app_env": settings.app_env})
    yield
    await dispose_engine()
    logger.info("shutdown")


def create_app() -> FastAPI:
    """Build the ASGI app with envelope-only error responses."""
    application = FastAPI(
        title="CareCloud Patient Registration",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.add_middleware(RequestIdMiddleware)
    application.include_router(health_router)
    application.include_router(patients_router)
    application.include_router(llm_router)
    application.include_router(vapi_router)
    _register_exception_handlers(application)
    return application


def _register_exception_handlers(application: FastAPI) -> None:
    """Force every error path through the {data, error} envelope."""

    @application.exception_handler(RequestValidationError)
    async def request_validation_handler(
        _request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        errors = exc.errors()
        # FastAPI uses type json_invalid when the body is not parseable JSON.
        if any(item.get("type") == "json_invalid" for item in errors):
            return JSONResponse(
                status_code=400,
                content=failure("BAD_REQUEST", "Malformed JSON"),
            )
        details = [_field_detail(item) for item in errors]
        return JSONResponse(
            status_code=422,
            content=failure("VALIDATION_ERROR", "Invalid input", details),
        )

    @application.exception_handler(NotFound)
    async def not_found_handler(_request: Request, exc: NotFound) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content=failure("NOT_FOUND", exc.message),
        )

    @application.exception_handler(ValidationFailed)
    async def validation_failed_handler(
        _request: Request,
        exc: ValidationFailed,
    ) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=failure("VALIDATION_ERROR", exc.message, exc.details or None),
        )

    @application.exception_handler(DatabaseUnavailable)
    async def database_unavailable_handler(
        _request: Request,
        exc: DatabaseUnavailable,
    ) -> JSONResponse:
        logger.exception("database_unavailable", extra={"reason": exc.message})
        return JSONResponse(
            status_code=500,
            content=failure("INTERNAL_ERROR", "An unexpected error occurred"),
        )

    @application.exception_handler(StarletteHTTPException)
    async def http_exception_handler(
        _request: Request,
        exc: StarletteHTTPException,
    ) -> JSONResponse:
        code = _HTTP_ERROR_CODES.get(exc.status_code, "INTERNAL_ERROR")
        message = exc.detail if isinstance(exc.detail, str) else "Request failed"
        return JSONResponse(
            status_code=exc.status_code,
            content=failure(code, message),
        )

    @application.exception_handler(Exception)
    async def unhandled_handler(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_error", extra={"error_type": type(exc).__name__})
        return JSONResponse(
            status_code=500,
            content=failure("INTERNAL_ERROR", "An unexpected error occurred"),
        )


def _field_detail(error: dict) -> dict[str, str]:
    """Turn a Pydantic error loc into a dotted field name."""
    loc = error.get("loc", ())
    parts = [str(item) for item in loc if item != "body"]
    return {
        "field": ".".join(parts) if parts else "body",
        "message": str(error.get("msg", "Invalid")),
    }


app = create_app()
