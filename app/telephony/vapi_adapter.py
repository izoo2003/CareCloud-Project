"""Parse Vapi webhook payloads and format tool results. No patient logic here."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastapi import HTTPException, Request

from app.config import get_settings

logger = logging.getLogger(__name__)

_logged_first_shape = False


@dataclass(frozen=True)
class ParsedToolCall:
    """One tool invocation extracted from a Vapi tool-calls message."""

    tool_call_id: str
    name: str
    arguments: dict[str, Any]


def verify_vapi_secret(request: Request) -> None:
    """Accept Authorization: Bearer <secret> or x-vapi-secret. Empty config is closed."""
    expected = get_settings().vapi_server_secret
    if not expected:
        raise HTTPException(status_code=401, detail="Unauthorized")
    authorization = request.headers.get("authorization", "")
    bearer = ""
    if authorization.lower().startswith("bearer "):
        bearer = authorization[7:].strip()
    header_secret = request.headers.get("x-vapi-secret", "")
    if bearer != expected and header_secret != expected:
        raise HTTPException(status_code=401, detail="Unauthorized")


def parse_webhook_body(body: dict[str, Any]) -> tuple[str, str | None, list[ParsedToolCall]]:
    """Return (message_type, vapi_call_id, tool_calls) from a Vapi server message."""
    message = body.get("message") if isinstance(body.get("message"), dict) else {}
    msg_type = ""
    if isinstance(message.get("type"), str):
        msg_type = message["type"]
    elif isinstance(body.get("type"), str):
        msg_type = body["type"]

    call = message.get("call") if isinstance(message.get("call"), dict) else {}
    if not call and isinstance(body.get("call"), dict):
        call = body["call"]
    raw_call_id = call.get("id")
    if isinstance(raw_call_id, str) and raw_call_id.strip():
        vapi_call_id = raw_call_id.strip()
    else:
        vapi_call_id = None

    raw_list = message.get("toolCallList")
    if not isinstance(raw_list, list):
        raw_list = message.get("toolWithToolCallList")
    if not isinstance(raw_list, list):
        raw_list = body.get("toolCallList")
    if not isinstance(raw_list, list):
        raw_list = []

    tools = [parsed for item in raw_list if (parsed := _parse_one_tool(item)) is not None]
    return msg_type, vapi_call_id, tools


def format_tool_results(pairs: list[tuple[str, dict[str, Any]]]) -> dict[str, list[dict[str, str]]]:
    """Vapi expects result as a single-line JSON string, not an object."""
    return {
        "results": [
            {"toolCallId": tool_call_id, "result": json.dumps(result, separators=(",", ":"))}
            for tool_call_id, result in pairs
        ]
    }


def ack_event() -> dict[str, bool]:
    """Informational server messages (end-of-call-report, status-update) need a 200."""
    return {"ok": True}


def parse_end_of_call_report(body: dict[str, Any]) -> dict[str, Any]:
    """Extract call_logs fields from a Vapi end-of-call-report payload.

    Defensive: Vapi has moved summary/transcript/recording around over time.
    """
    message = body.get("message") if isinstance(body.get("message"), dict) else {}
    call = message.get("call") if isinstance(message.get("call"), dict) else {}
    if not call and isinstance(body.get("call"), dict):
        call = body["call"]

    raw_call_id = call.get("id")
    vapi_call_id = raw_call_id.strip() if isinstance(raw_call_id, str) else None

    artifact = message.get("artifact") if isinstance(message.get("artifact"), dict) else {}
    analysis = message.get("analysis") if isinstance(message.get("analysis"), dict) else {}
    if not analysis and isinstance(call.get("analysis"), dict):
        analysis = call["analysis"]

    transcript = _as_optional_str(artifact.get("transcript"))
    if transcript is None:
        transcript = _as_optional_str(message.get("transcript"))

    summary = _as_optional_str(analysis.get("summary"))
    if summary is None:
        summary = _as_optional_str(message.get("summary"))

    ended_reason = _as_optional_str(message.get("endedReason"))
    if ended_reason is None:
        ended_reason = _as_optional_str(call.get("endedReason"))

    recording_url = _extract_recording_url(artifact.get("recording"))
    if recording_url is None:
        recording_url = _extract_recording_url(message.get("recordingUrl"))
    if recording_url is None:
        recording_url = _extract_recording_url(message.get("recording"))

    caller_number = _extract_caller_number(message, call)

    started_at = _parse_iso_datetime(message.get("startedAt") or call.get("startedAt"))
    ended_at = _parse_iso_datetime(message.get("endedAt") or call.get("endedAt"))

    return {
        "vapi_call_id": vapi_call_id,
        "caller_number": caller_number,
        "ended_reason": ended_reason,
        "summary": summary,
        "transcript": transcript,
        "recording_url": recording_url,
        "started_at": started_at,
        "ended_at": ended_at,
    }


def maybe_log_first_webhook_shape(body: dict[str, Any]) -> None:
    """Once per process, in development only, log the incoming Vapi keys."""
    global _logged_first_shape
    if _logged_first_shape or not get_settings().is_development:
        return
    _logged_first_shape = True
    logger.info("vapi_webhook_request_shape", extra={"body_keys": sorted(body.keys())})


def _parse_one_tool(item: object) -> ParsedToolCall | None:
    if not isinstance(item, dict):
        return None

    # Vapi has also sent {name, toolCall: {id, parameters}}.
    if isinstance(item.get("toolCall"), dict):
        nested = dict(item["toolCall"])
        if "name" not in nested and item.get("name"):
            nested["name"] = item["name"]
        item = nested

    func = item.get("function") if isinstance(item.get("function"), dict) else {}
    name = item.get("name") or func.get("name") or ""
    if not isinstance(name, str) or not name:
        return None

    raw_args = _first_present(
        item.get("arguments"),
        item.get("parameters"),
        func.get("arguments"),
        func.get("parameters"),
    )
    arguments = _coerce_arguments(raw_args)

    raw_id = item.get("id") or item.get("toolCallId") or func.get("id") or ""
    tool_call_id = str(raw_id) if raw_id is not None else ""
    return ParsedToolCall(tool_call_id=tool_call_id, name=name, arguments=arguments)


def _first_present(*values: object) -> object:
    for value in values:
        if value is not None:
            return value
    return {}


def _coerce_arguments(raw: object) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        if not raw.strip():
            return {}
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _as_optional_str(value: object) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def _extract_recording_url(recording: object) -> str | None:
    if isinstance(recording, str) and recording.strip():
        return recording.strip()
    if not isinstance(recording, dict):
        return None
    for key in ("url", "stereoUrl", "monoUrl", "recordingUrl"):
        candidate = recording.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def _extract_caller_number(message: dict[str, Any], call: dict[str, Any]) -> str | None:
    customer = message.get("customer") if isinstance(message.get("customer"), dict) else {}
    if not customer and isinstance(call.get("customer"), dict):
        customer = call["customer"]
    for source in (customer, call, message):
        if not isinstance(source, dict):
            continue
        for key in ("number", "phoneNumber", "customerNumber"):
            text = _as_optional_str(source.get(key))
            if text:
                return text
    return None


def _parse_iso_datetime(value: object) -> datetime | None:
    """Best-effort parse of Vapi ISO timestamps."""
    if isinstance(value, datetime):
        return value
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None
