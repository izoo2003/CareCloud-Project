"""GET /health — DB ping plus a masked Gemini key snapshot."""

from __future__ import annotations

import logging

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app.core.errors import DatabaseUnavailable
from app.db.session import get_engine
from app.llm.key_pool import get_key_pool
from app.schemas.envelope import ApiResponse, HealthData, HealthGeminiStatus, success

logger = logging.getLogger(__name__)

router = APIRouter(tags=["health"])


def _gemini_status() -> HealthGeminiStatus:
    """Masked key-pool snapshot: configured keys plus available/cooling/disabled."""
    return HealthGeminiStatus.model_validate(get_key_pool().status())


def _unhealthy(gemini: dict) -> JSONResponse:
    """503 envelope used when the database ping fails."""
    return JSONResponse(
        status_code=503,
        content={
            "data": {
                "status": "unhealthy",
                "database": "disconnected",
                "gemini": gemini,
            },
            "error": {
                "code": "INTERNAL_ERROR",
                "message": "Database unavailable",
            },
        },
    )


@router.get(
    "/health",
    response_model=ApiResponse[HealthData],
    responses={
        200: {"description": "Database reachable"},
        503: {"description": "Database unreachable"},
    },
)
async def health() -> dict | JSONResponse:
    """Ping the database and report process health without leaking secrets."""
    gemini = _gemini_status().model_dump()
    try:
        engine = get_engine()
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
    except DatabaseUnavailable as exc:
        logger.warning("health_db_unavailable", extra={"reason": exc.message})
        return _unhealthy(gemini)
    except Exception:
        # Health must not raise 500 via the generic handler; reviewers get 503.
        logger.exception("health_db_ping_failed")
        return _unhealthy(gemini)

    return success(
        {
            "status": "ok",
            "database": "connected",
            "gemini": gemini,
        }
    )
