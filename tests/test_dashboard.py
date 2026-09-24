"""Dashboard HTML smoke test (no DB required)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.llm.key_pool import reset_key_pool
from app.main import create_app


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("VAPI_SERVER_SECRET", "test-secret")
    monkeypatch.setenv("GEMINI_API_KEYS", "AIza_test_key_one_xxxx")
    monkeypatch.setenv("CLINIC_NAME", "Maple Grove Family Health")
    get_settings.cache_clear()
    reset_key_pool(None)
    application = create_app()
    with TestClient(application) as test_client:
        yield test_client
    reset_key_pool(None)
    get_settings.cache_clear()


def test_dashboard_renders_html(client: TestClient) -> None:
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    assert "Maple Grove Family Health" in response.text
    assert "/patients" in response.text
