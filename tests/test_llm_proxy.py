"""LLM proxy auth, whitelist, prompt swap, and SSE fallback. Gemini is mocked."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.llm.key_pool import reset_key_pool
from app.llm.prompt import render_system_prompt
from app.main import create_app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("VAPI_SERVER_SECRET", "test-secret")
    monkeypatch.setenv("GEMINI_API_KEYS", "AIza_test_key_one_xxxx")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    monkeypatch.setenv("GEMINI_FALLBACK_MODEL", "gemini-3.8-flash")
    monkeypatch.setenv("CLINIC_NAME", "Maple Grove Family Health")
    monkeypatch.setenv("CLINIC_TIMEZONE", "America/New_York")
    monkeypatch.setenv("APP_ENV", "development")
    get_settings.cache_clear()
    reset_key_pool(None)
    with TestClient(create_app()) as test_client:
        yield test_client
    reset_key_pool(None)
    get_settings.cache_clear()


def _headers(*, secret: str = "test-secret", use_x_header: bool = False) -> dict[str, str]:
    if use_x_header:
        return {"x-vapi-secret": secret}
    return {"Authorization": f"Bearer {secret}"}


def test_rejects_missing_secret(client: TestClient) -> None:
    response = client.post("/llm/chat/completions", json={"messages": []})
    assert response.status_code == 401
    body = response.json()
    assert body["data"] is None
    assert body["error"]["code"] == "UNAUTHORIZED"


def test_rejects_wrong_secret(client: TestClient) -> None:
    response = client.post(
        "/llm/chat/completions",
        headers=_headers(secret="wrong"),
        json={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 401


def test_accepts_x_vapi_secret_and_replaces_system_prompt(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    async def fake_complete(payload: dict[str, Any]) -> dict[str, Any]:
        captured["payload"] = payload
        return {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "choices": [{"index": 0, "message": {"role": "assistant", "content": "Hi"}}],
        }

    monkeypatch.setattr("app.api.llm_proxy.complete", fake_complete)

    response = client.post(
        "/llm/chat/completions",
        headers=_headers(use_x_header=True),
        json={
            "model": "vapi-should-drop-this",
            "stream": False,
            "messages": [
                {"role": "system", "content": "ignore me"},
                {"role": "user", "content": "hello"},
            ],
            "call": {"customer": {"number": "5125550101"}},
            "metadata": {"foo": 1},
            "phoneNumber": {"number": "+1555"},
        },
    )
    assert response.status_code == 200
    payload = captured["payload"]
    assert "call" not in payload
    assert "metadata" not in payload
    assert "phoneNumber" not in payload
    assert payload["messages"][0]["role"] == "system"
    system = payload["messages"][0]["content"]
    assert "Maple Grove Family Health" in system
    assert "5125550101" in system
    assert "0101" in system
    assert "ignore me" not in system
    assert payload["messages"][1]["content"] == "hello"


def test_stream_default_is_sse(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_stream(_payload: dict[str, Any]) -> AsyncIterator[str]:
        yield 'data: {"choices":[{"delta":{"content":"Hi"}}]}\n\n'
        yield "data: [DONE]\n\n"

    monkeypatch.setattr("app.api.llm_proxy.stream_completion", fake_stream)

    response = client.post(
        "/llm/chat/completions",
        headers=_headers(),
        json={"messages": [{"role": "user", "content": "hi"}]},
    )
    assert response.status_code == 200
    assert "text/event-stream" in response.headers["content-type"]
    text = response.text
    assert "data: " in text
    assert "[DONE]" in text


def test_spoken_fallback_when_pool_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("VAPI_SERVER_SECRET", "test-secret")
    monkeypatch.setenv("GEMINI_API_KEYS", "")
    monkeypatch.setenv("GEMINI_MODEL", "gemini-3.5-flash-lite")
    get_settings.cache_clear()
    reset_key_pool(None)
    with TestClient(create_app()) as test_client:
        response = test_client.post(
            "/llm/chat/completions",
            headers=_headers(),
            json={"stream": True, "messages": [{"role": "user", "content": "hi"}]},
        )
    reset_key_pool(None)
    get_settings.cache_clear()
    assert response.status_code == 200
    assert "trouble on my end" in response.text
    assert "[DONE]" in response.text


def test_render_system_prompt_unknown_caller() -> None:
    text = render_system_prompt(
        clinic_name="Maple Grove Family Health",
        today=date(2026, 9, 24),
        caller_number="",
    )
    assert "September 24, 2026" in text
    assert "2026-09-24" in text
    assert "Caller ID: unknown" in text
    assert "{first}" in text
    assert "{first_name}" in text
