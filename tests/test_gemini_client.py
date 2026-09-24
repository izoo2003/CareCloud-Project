"""Gemini client failover: 429 rotates keys; tool_call ids are filled in."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from openai import RateLimitError

from app.config import Settings
from app.llm.gemini_client import _ensure_tool_call_ids, stream_completion
from app.llm.key_pool import KeyPool


def _rate_limit_error() -> RateLimitError:
    request = httpx.Request("POST", "https://example.com/v1/chat/completions")
    response = httpx.Response(429, request=request, headers={"retry-after": "60"})
    return RateLimitError("rate limited", response=response, body=None)


class _FakeStream:
    def __init__(self, chunks: list[dict[str, Any]]) -> None:
        self._chunks = chunks

    def __aiter__(self) -> _FakeStream:
        return self

    async def __anext__(self) -> SimpleNamespace:
        if not self._chunks:
            raise StopAsyncIteration
        payload = self._chunks.pop(0)
        return SimpleNamespace(model_dump=lambda **_: payload)


class _FakeClient:
    def __init__(self, api_key: str, behavior: dict[str, Any]) -> None:
        self.api_key = api_key
        self._behavior = behavior
        self.chat = SimpleNamespace(completions=self)

    async def create(self, **_kwargs: Any) -> _FakeStream:
        action = self._behavior[self.api_key]
        if action == "429":
            raise _rate_limit_error()
        return _FakeStream(
            [{"choices": [{"index": 0, "delta": {"content": "Hello there."}}]}]
        )

    async def close(self) -> None:
        return None


@pytest.mark.asyncio
async def test_stream_rotates_after_429(monkeypatch: pytest.MonkeyPatch) -> None:
    keys = ["AIza_test_key_one_xxxx", "AIza_test_key_two_yyyy"]
    pool = KeyPool(keys)
    settings = Settings(
        gemini_api_keys=",".join(keys),
        gemini_model="gemini-3.5-flash-lite",
        gemini_fallback_model="gemini-3.8-flash",
        gemini_reasoning_effort="low",
    )
    behavior = {keys[0]: "429", keys[1]: "ok"}

    def fake_make_client(_settings: Settings, api_key: str) -> _FakeClient:
        return _FakeClient(api_key, behavior)

    monkeypatch.setattr("app.llm.gemini_client._make_client", fake_make_client)

    chunks: list[str] = []
    async for line in stream_completion(
        {"messages": [{"role": "user", "content": "hi"}]},
        settings=settings,
        pool=pool,
    ):
        chunks.append(line)

    text = "".join(chunks)
    assert "Hello there." in text
    assert "[DONE]" in text
    status = pool.status()
    assert status["cooling_down"] == 1
    assert status["available"] == 1
    assert status["disabled"] == 0


@pytest.mark.asyncio
async def test_stream_single_key_tries_fallback_model_after_429(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One key: primary 429 must still attempt the fallback model (reuse lease)."""
    key = "AIza_test_key_only_xxxx"
    pool = KeyPool([key])
    settings = Settings(
        gemini_api_keys=key,
        gemini_model="gemini-primary",
        gemini_fallback_model="gemini-fallback,gemini-tertiary",
        gemini_reasoning_effort="low",
    )
    calls: list[str] = []

    class _TrackingClient(_FakeClient):
        async def create(self, **kwargs: Any) -> _FakeStream:
            model = str(kwargs.get("model", ""))
            calls.append(model)
            if model == "gemini-primary":
                raise _rate_limit_error()
            return _FakeStream(
                [{"choices": [{"index": 0, "delta": {"content": "Recovered."}}]}]
            )

    def fake_make_client(_settings: Settings, api_key: str) -> _TrackingClient:
        return _TrackingClient(api_key, {api_key: "ok"})

    monkeypatch.setattr("app.llm.gemini_client._make_client", fake_make_client)

    chunks: list[str] = []
    async for line in stream_completion(
        {"messages": [{"role": "user", "content": "hi"}]},
        settings=settings,
        pool=pool,
    ):
        chunks.append(line)

    text = "".join(chunks)
    assert "Recovered." in text
    assert "gemini-primary" in calls
    assert "gemini-fallback" in calls
    assert "trouble on my end" not in text


def test_ensure_tool_call_ids_fills_missing() -> None:
    payload = {"choices": [{"delta": {"tool_calls": [{"function": {"name": "register_patient"}}]}}]}
    _ensure_tool_call_ids(payload)
    call = payload["choices"][0]["delta"]["tool_calls"][0]
    assert call["id"].startswith("call_")
    assert call["index"] == 0
