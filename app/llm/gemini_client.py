"""Streaming Gemini completions via the OpenAI-compatible endpoint."""

from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import AsyncIterator
from typing import Any

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    AuthenticationError,
    BadRequestError,
    PermissionDeniedError,
    RateLimitError,
)

from app.config import Settings, get_settings
from app.llm.key_pool import KeyLease, KeyPool, get_key_pool

logger = logging.getLogger(__name__)

SPOKEN_FALLBACK = (
    "I'm sorry, I'm having a little trouble on my end. Could you say that one more time?"
)

_PRIMARY_ATTEMPT_CAP = 3
_FALLBACK_ATTEMPT_CAP = 2


def _retry_after_seconds(exc: BaseException) -> float | None:
    response = getattr(exc, "response", None)
    if response is None:
        return None
    headers = getattr(response, "headers", None) or {}
    raw = headers.get("retry-after") or headers.get("Retry-After")
    if raw is None:
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _is_reasoning_param_error(exc: BadRequestError) -> bool:
    text = str(exc).lower()
    return "reasoning_effort" in text or "thinking" in text


def _ensure_tool_call_ids(payload: dict[str, Any]) -> None:
    """Gemini sometimes omits tool_call id/index; Vapi needs both."""
    for choice in payload.get("choices") or []:
        if not isinstance(choice, dict):
            continue
        message = choice.get("delta") or choice.get("message") or {}
        if not isinstance(message, dict):
            continue
        tool_calls = message.get("tool_calls") or []
        for index, call in enumerate(tool_calls):
            if not isinstance(call, dict):
                continue
            if not call.get("id"):
                call["id"] = f"call_{uuid.uuid4().hex[:8]}"
            if call.get("index") is None:
                call["index"] = index


def _chunk_to_dict(chunk: Any) -> dict[str, Any]:
    if hasattr(chunk, "model_dump"):
        return chunk.model_dump(exclude_none=True)
    if isinstance(chunk, dict):
        return chunk
    return {}


def _sse_line(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, separators=(',', ':'))}\n\n"


def _fallback_chunk(*, streamed: bool) -> dict[str, Any]:
    created = int(time.time())
    if streamed:
        return {
            "id": "chatcmpl-fallback",
            "object": "chat.completion.chunk",
            "created": created,
            "model": "fallback",
            "choices": [
                {
                    "index": 0,
                    "delta": {"role": "assistant", "content": SPOKEN_FALLBACK},
                    "finish_reason": "stop",
                }
            ],
        }
    return {
        "id": "chatcmpl-fallback",
        "object": "chat.completion",
        "created": created,
        "model": "fallback",
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": SPOKEN_FALLBACK},
                "finish_reason": "stop",
            }
        ],
    }


def _make_client(settings: Settings, api_key: str) -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=api_key,
        base_url=settings.gemini_base_url,
        timeout=settings.llm_timeout_seconds,
        max_retries=0,
    )


def _request_kwargs(
    settings: Settings,
    payload: dict[str, Any],
    *,
    model: str,
    stream: bool,
    include_reasoning: bool,
) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "model": model,
        "messages": payload.get("messages") or [],
        "stream": stream,
    }
    if "tools" in payload:
        kwargs["tools"] = payload["tools"]
    if "tool_choice" in payload:
        kwargs["tool_choice"] = payload["tool_choice"]
    temperature = payload.get("temperature", settings.llm_temperature)
    if temperature is not None:
        kwargs["temperature"] = temperature
    max_tokens = payload.get(
        "max_tokens",
        payload.get("max_completion_tokens", settings.llm_max_tokens),
    )
    if max_tokens is not None:
        kwargs["max_tokens"] = max_tokens
    if include_reasoning and settings.gemini_reasoning_effort:
        kwargs["reasoning_effort"] = settings.gemini_reasoning_effort
    return kwargs


async def _report_failure(pool: KeyPool, lease: KeyLease, exc: BaseException) -> str:
    """Update pool state and return a short outcome label."""
    if isinstance(exc, RateLimitError):
        await pool.report_rate_limit(lease.index, _retry_after_seconds(exc))
        return "rate_limited"
    if isinstance(exc, (AuthenticationError, PermissionDeniedError)):
        await pool.report_auth_error(lease.index)
        return "auth_error"
    if isinstance(exc, (APITimeoutError, APIConnectionError)):
        await pool.report_server_error(lease.index)
        return "timeout" if isinstance(exc, APITimeoutError) else "connect_error"
    if isinstance(exc, APIStatusError) and exc.status_code >= 500:
        await pool.report_server_error(lease.index)
        return "server_error"
    if isinstance(exc, APIStatusError):
        await pool.report_server_error(lease.index)
        return "api_error"
    await pool.report_server_error(lease.index)
    return "error"


def _attempt_plan(settings: Settings, pool_size: int) -> list[str]:
    """Primary model up to min(keys, 3), then each fallback model 1–2 times."""
    if pool_size <= 0:
        return []
    plan: list[str] = []
    primary = settings.gemini_model.strip()
    if primary:
        plan.extend([primary] * min(pool_size, _PRIMARY_ATTEMPT_CAP))
    seen = {primary} if primary else set()
    for fallback in settings.gemini_fallback_models:
        if fallback in seen:
            continue
        seen.add(fallback)
        plan.extend([fallback] * min(pool_size, _FALLBACK_ATTEMPT_CAP))
    return plan


async def _acquire_for_attempt(
    pool: KeyPool,
    *,
    last_key_index: int | None,
) -> KeyLease | None:
    """Prefer a fresh key; if all are cooling mid-request, reuse the last key."""
    lease = await pool.acquire()
    if lease is not None:
        return lease
    if last_key_index is None:
        return None
    return pool.lease_by_index(last_key_index)


def _log_request(
    *,
    key_index: int | None,
    model: str,
    attempts: int,
    ttft_ms: float | None,
    total_ms: float,
    outcome: str,
) -> None:
    logger.info(
        "llm_request",
        extra={
            "key_index": key_index,
            "model": model,
            "attempts": attempts,
            "ttft_ms": ttft_ms,
            "total_ms": round(total_ms, 1),
            "outcome": outcome,
        },
    )


async def stream_completion(
    payload: dict[str, Any],
    *,
    settings: Settings | None = None,
    pool: KeyPool | None = None,
) -> AsyncIterator[str]:
    """Yield OpenAI SSE lines. Retries only happen before the first chunk."""
    settings = settings or get_settings()
    pool = pool or get_key_pool()
    started = time.perf_counter()
    attempts = 0
    last_model = settings.gemini_model or "unknown"
    last_key_index: int | None = None

    for model in _attempt_plan(settings, pool.size):
        lease = await _acquire_for_attempt(pool, last_key_index=last_key_index)
        if lease is None:
            break
        attempts += 1
        last_model = model
        last_key_index = lease.index
        include_reasoning = True
        streamed_out = False
        while True:
            client = _make_client(settings, lease.key)
            try:
                stream = await client.chat.completions.create(
                    **_request_kwargs(
                        settings,
                        payload,
                        model=model,
                        stream=True,
                        include_reasoning=include_reasoning,
                    )
                )
                first_chunk = True
                ttft_ms: float | None = None
                async for chunk in stream:
                    data = _chunk_to_dict(chunk)
                    _ensure_tool_call_ids(data)
                    if first_chunk:
                        ttft_ms = (time.perf_counter() - started) * 1000
                        first_chunk = False
                    streamed_out = True
                    yield _sse_line(data)
                if first_chunk:
                    # Stream opened but produced nothing — treat as a failed attempt.
                    await pool.report_server_error(lease.index)
                    break
                await pool.report_success(lease.index)
                yield "data: [DONE]\n\n"
                _log_request(
                    key_index=lease.index,
                    model=model,
                    attempts=attempts,
                    ttft_ms=round(ttft_ms, 1) if ttft_ms is not None else None,
                    total_ms=(time.perf_counter() - started) * 1000,
                    outcome="success",
                )
                return
            except BadRequestError as exc:
                if streamed_out:
                    yield "data: [DONE]\n\n"
                    _log_request(
                        key_index=lease.index,
                        model=model,
                        attempts=attempts,
                        ttft_ms=None,
                        total_ms=(time.perf_counter() - started) * 1000,
                        outcome="stream_error",
                    )
                    return
                if include_reasoning and _is_reasoning_param_error(exc):
                    logger.warning(
                        "gemini_reasoning_effort_rejected",
                        extra={"model": model, "key_index": lease.index},
                    )
                    include_reasoning = False
                    continue
                await _report_failure(pool, lease, exc)
                break
            except Exception as exc:
                if streamed_out:
                    yield "data: [DONE]\n\n"
                    _log_request(
                        key_index=lease.index,
                        model=model,
                        attempts=attempts,
                        ttft_ms=None,
                        total_ms=(time.perf_counter() - started) * 1000,
                        outcome="stream_error",
                    )
                    return
                await _report_failure(pool, lease, exc)
                break
            finally:
                await client.close()

    for line in (
        _sse_line(_fallback_chunk(streamed=True)),
        "data: [DONE]\n\n",
    ):
        yield line
    _log_request(
        key_index=last_key_index,
        model=last_model,
        attempts=attempts,
        ttft_ms=None,
        total_ms=(time.perf_counter() - started) * 1000,
        outcome="fallback",
    )


async def complete(
    payload: dict[str, Any],
    *,
    settings: Settings | None = None,
    pool: KeyPool | None = None,
) -> dict[str, Any]:
    """Non-streaming completion with the same retry / fallback policy."""
    settings = settings or get_settings()
    pool = pool or get_key_pool()
    started = time.perf_counter()
    attempts = 0
    last_model = settings.gemini_model or "unknown"
    last_key_index: int | None = None

    for model in _attempt_plan(settings, pool.size):
        lease = await _acquire_for_attempt(pool, last_key_index=last_key_index)
        if lease is None:
            break
        attempts += 1
        last_model = model
        last_key_index = lease.index
        include_reasoning = True
        while True:
            client = _make_client(settings, lease.key)
            try:
                response = await client.chat.completions.create(
                    **_request_kwargs(
                        settings,
                        payload,
                        model=model,
                        stream=False,
                        include_reasoning=include_reasoning,
                    )
                )
                await pool.report_success(lease.index)
                data = _chunk_to_dict(response)
                _ensure_tool_call_ids(data)
                _log_request(
                    key_index=lease.index,
                    model=model,
                    attempts=attempts,
                    ttft_ms=round((time.perf_counter() - started) * 1000, 1),
                    total_ms=(time.perf_counter() - started) * 1000,
                    outcome="success",
                )
                return data
            except BadRequestError as exc:
                if include_reasoning and _is_reasoning_param_error(exc):
                    logger.warning(
                        "gemini_reasoning_effort_rejected",
                        extra={"model": model, "key_index": lease.index},
                    )
                    include_reasoning = False
                    continue
                await _report_failure(pool, lease, exc)
                break
            except Exception as exc:
                await _report_failure(pool, lease, exc)
                break
            finally:
                await client.close()

    _log_request(
        key_index=last_key_index,
        model=last_model,
        attempts=attempts,
        ttft_ms=None,
        total_ms=(time.perf_counter() - started) * 1000,
        outcome="fallback",
    )
    return _fallback_chunk(streamed=False)
