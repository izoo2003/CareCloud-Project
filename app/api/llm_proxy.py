"""POST /llm/chat/completions — OpenAI-compatible Custom LLM endpoint for Vapi."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import StreamingResponse

from app.config import get_settings
from app.llm.gemini_client import complete, stream_completion
from app.llm.prompt import render_system_prompt

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/llm", tags=["llm"])

_WHITELIST = frozenset(
    {
        "messages",
        "tools",
        "tool_choice",
        "temperature",
        "max_tokens",
        "max_completion_tokens",
        "stream",
    }
)

_logged_first_shape = False


def _verify_vapi_secret(request: Request) -> None:
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


def _extract_caller_number(body: dict[str, Any]) -> str:
    """Pull caller ID from Vapi metadata; web calls often have none."""
    call = body.get("call") if isinstance(body.get("call"), dict) else {}
    customer = call.get("customer") if isinstance(call.get("customer"), dict) else None
    if customer is None and isinstance(body.get("customer"), dict):
        customer = body["customer"]
    number = customer.get("number") if customer else None
    if isinstance(number, str) and number.strip():
        return number.strip()
    return "unknown"


def _whitelist_body(body: dict[str, Any]) -> dict[str, Any]:
    return {key: body[key] for key in _WHITELIST if key in body}


def _inject_system_prompt(messages: list[Any], caller_number: str) -> list[dict[str, Any]]:
    settings = get_settings()
    today = datetime.now(ZoneInfo(settings.clinic_timezone)).date()
    system = render_system_prompt(
        clinic_name=settings.clinic_name,
        today=today,
        caller_number=caller_number,
    )
    rewritten: list[dict[str, Any]] = []
    replaced = False
    for item in messages:
        if not isinstance(item, dict):
            continue
        if item.get("role") == "system":
            if not replaced:
                rewritten.append({"role": "system", "content": system})
                replaced = True
            continue
        rewritten.append(item)
    if not replaced:
        rewritten.insert(0, {"role": "system", "content": system})
    return rewritten


def _maybe_log_first_shape(body: dict[str, Any]) -> None:
    global _logged_first_shape
    if _logged_first_shape or not get_settings().is_development:
        return
    _logged_first_shape = True
    logger.info("vapi_llm_request_shape", extra={"body_keys": sorted(body.keys())})


@router.post("/chat/completions")
async def chat_completions(request: Request) -> Any:
    """OpenAI chat-completions shape. Not wrapped in the {data, error} envelope."""
    _verify_vapi_secret(request)
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Malformed JSON") from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="Malformed JSON")

    _maybe_log_first_shape(body)
    caller_number = _extract_caller_number(body)
    payload = _whitelist_body(body)
    raw_messages = payload.get("messages")
    if not isinstance(raw_messages, list):
        raise HTTPException(status_code=400, detail="messages is required")
    payload["messages"] = _inject_system_prompt(raw_messages, caller_number)

    stream = payload.get("stream", True)
    if stream:
        return StreamingResponse(
            stream_completion(payload),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )
    return await complete(payload)
