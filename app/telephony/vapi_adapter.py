"""Parse Vapi webhook payloads and format tool results. No patient logic here."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
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
