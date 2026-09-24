"""POST /vapi/webhook — Vapi tool-calls and informational server messages."""

from __future__ import annotations

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_session
from app.services.call_log_service import CallLogService
from app.services.patient_service import PatientService
from app.services.tool_handlers import dispatch_tool
from app.telephony.vapi_adapter import (
    ack_event,
    format_tool_results,
    maybe_log_first_webhook_shape,
    parse_end_of_call_report,
    parse_webhook_body,
    verify_vapi_secret,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/vapi", tags=["vapi"])


def get_patient_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PatientService:
    """Shared PatientService used by voice tools (same layer as REST)."""
    return PatientService(session)


def get_call_log_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> CallLogService:
    """CallLogService for end-of-call reports and register/update linking."""
    return CallLogService(session)


@router.post("/webhook")
async def vapi_webhook(
    request: Request,
    service: Annotated[PatientService, Depends(get_patient_service)],
    call_logs: Annotated[CallLogService, Depends(get_call_log_service)],
) -> Any:
    """Always 200 after auth so Vapi can speak a tool result instead of dying."""
    verify_vapi_secret(request)
    try:
        body = await request.json()
    except Exception:
        logger.warning("vapi_webhook_malformed_json")
        return JSONResponse(ack_event())
    if not isinstance(body, dict):
        return JSONResponse(ack_event())

    maybe_log_first_webhook_shape(body)

    try:
        msg_type, vapi_call_id, tool_calls = parse_webhook_body(body)

        if msg_type == "end-of-call-report":
            report = parse_end_of_call_report(body)
            try:
                await call_logs.upsert_from_report(report)
            except Exception:
                # Never fail the webhook — transcript is also in Vapi's dashboard.
                logger.exception(
                    "call_log_upsert_failed",
                    extra={"vapi_call_id": report.get("vapi_call_id")},
                )
            return JSONResponse(ack_event())

        if msg_type != "tool-calls" and not tool_calls:
            return JSONResponse(ack_event())

        pairs: list[tuple[str, dict[str, Any]]] = []
        for call in tool_calls:
            result = await dispatch_tool(
                call.name,
                call.arguments,
                service,
                vapi_call_id,
                call_logs=call_logs,
            )
            pairs.append((call.tool_call_id, result))
        if not pairs:
            return JSONResponse(ack_event())
        return JSONResponse(format_tool_results(pairs))
    except Exception:
        logger.exception("vapi_webhook_unhandled")
        return JSONResponse(ack_event())
