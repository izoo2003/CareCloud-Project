"""Map voice-agent tool names to PatientService calls and LLM-friendly results."""

from __future__ import annotations

import logging
import time
import uuid
from typing import Any

from pydantic import ValidationError

from app.core.errors import DatabaseUnavailable, NotFound, ValidationFailed
from app.core.validators import normalize_phone
from app.schemas.patient import PatientCreate, PatientUpdate
from app.services.patient_service import PatientService

logger = logging.getLogger(__name__)

_VALIDATION_NEXT = (
    "Ask the caller again for only these fields, confirm them, then call the tool again."
)
_SERVER_NEXT = (
    "Apologize briefly and try once more. If it fails again, tell the caller it could "
    "not be saved and to call back later. Do not say it was saved."
)
_SUCCESS_NEXT = "Tell the caller they're all set using their first name."


async def dispatch_tool(
    name: str,
    arguments: dict[str, Any],
    service: PatientService,
    vapi_call_id: str | None,
) -> dict[str, Any]:
    """Run one named tool. Always returns a JSON-serializable result dict."""
    started = time.perf_counter()
    outcome = "error"
    try:
        if name == "lookup_patient_by_phone":
            result = await lookup_patient_by_phone(arguments, service)
        elif name == "register_patient":
            result = await register_patient(arguments, service, vapi_call_id)
        elif name == "update_patient":
            result = await update_patient(arguments, service, vapi_call_id)
        else:
            result = _server_result()
            result["next_step"] = "Continue the conversation without this tool."
        outcome = _outcome_label(result)
        return result
    except DatabaseUnavailable:
        logger.exception(
            "tool_server_error",
            extra={"tool": name, "vapi_call_id": vapi_call_id, "payload": arguments},
        )
        return _server_result()
    except Exception:
        logger.exception(
            "tool_unhandled_error",
            extra={"tool": name, "vapi_call_id": vapi_call_id, "payload": arguments},
        )
        return _server_result()
    finally:
        latency_ms = int((time.perf_counter() - started) * 1000)
        logger.info(
            "tool_call",
            extra={
                "tool": name,
                "outcome": outcome,
                "latency_ms": latency_ms,
                "vapi_call_id": vapi_call_id,
            },
        )


async def lookup_patient_by_phone(
    arguments: dict[str, Any],
    service: PatientService,
) -> dict[str, Any]:
    """Duplicate detection. Returns found + name only, never other fields."""
    try:
        phone = normalize_phone(arguments.get("phone_number"), field="phone_number")
    except ValueError as exc:
        return _validation_result([{"field": "phone_number", "message": str(exc)}])
    patient = await service.find_active_by_phone(phone)
    if patient is None:
        return {"found": False}
    return {
        "found": True,
        "patient_id": str(patient.patient_id),
        "first_name": patient.first_name,
        "last_name": patient.last_name,
    }


async def register_patient(
    arguments: dict[str, Any],
    service: PatientService,
    vapi_call_id: str | None,
) -> dict[str, Any]:
    """Create a patient after the caller confirmed the read-back."""
    try:
        payload = PatientCreate.model_validate(arguments)
    except ValidationError as exc:
        return _validation_result(_pydantic_field_errors(exc))
    try:
        patient = await service.create(payload)
    except ValidationFailed as exc:
        return _validation_result(exc.details or [{"field": "body", "message": exc.message}])
    logger.info(
        "tool_register",
        extra={"vapi_call_id": vapi_call_id, "patient_id": str(patient.patient_id)},
    )
    return {
        "success": True,
        "patient_id": str(patient.patient_id),
        "first_name": patient.first_name,
        "next_step": _SUCCESS_NEXT,
    }


async def update_patient(
    arguments: dict[str, Any],
    service: PatientService,
    vapi_call_id: str | None,
) -> dict[str, Any]:
    """Partial update after a returning caller confirms the changes."""
    raw_id = arguments.get("patient_id")
    try:
        patient_id = uuid.UUID(str(raw_id))
    except (ValueError, TypeError):
        return _validation_result(
            [{"field": "patient_id", "message": "patient_id must be a valid UUID"}]
        )
    update_args = {key: value for key, value in arguments.items() if key != "patient_id"}
    try:
        payload = PatientUpdate.model_validate(update_args)
    except ValidationError as exc:
        return _validation_result(_pydantic_field_errors(exc))
    if not payload.model_dump(exclude_unset=True):
        return _validation_result(
            [{"field": "body", "message": "At least one field to update is required"}]
        )
    try:
        patient = await service.update(patient_id, payload)
    except ValidationFailed as exc:
        return _validation_result(exc.details or [{"field": "body", "message": exc.message}])
    except NotFound:
        return _validation_result([{"field": "patient_id", "message": "Patient not found"}])
    logger.info(
        "tool_update",
        extra={"vapi_call_id": vapi_call_id, "patient_id": str(patient.patient_id)},
    )
    return {
        "success": True,
        "patient_id": str(patient.patient_id),
        "first_name": patient.first_name,
        "next_step": _SUCCESS_NEXT,
    }


def _validation_result(field_errors: list[dict[str, str]]) -> dict[str, Any]:
    return {
        "success": False,
        "error_type": "validation",
        "field_errors": field_errors,
        "next_step": _VALIDATION_NEXT,
    }


def _server_result() -> dict[str, Any]:
    return {
        "success": False,
        "error_type": "server",
        "next_step": _SERVER_NEXT,
    }


def _pydantic_field_errors(exc: ValidationError) -> list[dict[str, str]]:
    details: list[dict[str, str]] = []
    for error in exc.errors():
        loc = error.get("loc", ())
        field = str(loc[0]) if loc else "body"
        details.append({"field": field, "message": str(error.get("msg", "Invalid"))})
    return details or [{"field": "body", "message": "Invalid input"}]


def _outcome_label(result: dict[str, Any]) -> str:
    if result.get("success") is True:
        return "success"
    if result.get("found") is True:
        return "found"
    if result.get("found") is False:
        return "not_found"
    if result.get("error_type") == "validation":
        return "validation"
    return "error"
