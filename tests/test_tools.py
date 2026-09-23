"""Vapi webhook dispatcher: both tool-call shapes, result contract, auth."""

from __future__ import annotations

import json
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.core.errors import DatabaseUnavailable, NotFound
from app.llm.key_pool import reset_key_pool
from app.main import create_app
from app.telephony.vapi_adapter import format_tool_results, parse_webhook_body


class FakePatientService:
    """In-memory stand-in so webhook tests never touch the live DB."""

    def __init__(self) -> None:
        self.by_phone: dict[str, Any] = {}
        self.create_error: Exception | None = None
        self.update_error: Exception | None = None
        self.created: list[Any] = []
        self.updated: list[tuple[uuid.UUID, Any]] = []

    async def find_active_by_phone(self, phone_number: str) -> Any | None:
        return self.by_phone.get(phone_number)

    async def create(self, payload: Any) -> Any:
        if self.create_error is not None:
            raise self.create_error
        patient = SimpleNamespace(
            patient_id=uuid.uuid4(),
            first_name=payload.first_name,
            last_name=payload.last_name,
        )
        self.created.append(patient)
        return patient

    async def update(self, patient_id: uuid.UUID, payload: Any) -> Any:
        if self.update_error is not None:
            raise self.update_error
        self.updated.append((patient_id, payload))
        return SimpleNamespace(
            patient_id=patient_id,
            first_name=getattr(payload, "first_name", None) or "Jane",
            last_name="Doe",
        )

    async def get(self, patient_id: uuid.UUID) -> Any:
        raise NotFound("Patient not found")


@pytest.fixture
def service() -> FakePatientService:
    return FakePatientService()


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, service: FakePatientService) -> TestClient:
    monkeypatch.setenv("VAPI_SERVER_SECRET", "test-secret")
    monkeypatch.setenv("GEMINI_API_KEYS", "AIza_test_key_one_xxxx")
    monkeypatch.setenv("APP_ENV", "development")
    get_settings.cache_clear()
    reset_key_pool(None)

    from app.api.vapi import get_patient_service

    application = create_app()
    application.dependency_overrides[get_patient_service] = lambda: service
    with TestClient(application) as test_client:
        yield test_client
    application.dependency_overrides.clear()
    reset_key_pool(None)
    get_settings.cache_clear()


def _headers(*, secret: str = "test-secret") -> dict[str, str]:
    return {"Authorization": f"Bearer {secret}"}


def _result(response_json: dict[str, Any]) -> dict[str, Any]:
    raw = response_json["results"][0]["result"]
    assert isinstance(raw, str)
    assert "\n" not in raw
    return json.loads(raw)


REGISTER_ARGS = {
    "first_name": "Morgan",
    "last_name": "Lee",
    "date_of_birth": "03/14/1988",
    "sex": "Female",
    "phone_number": "5125550188",
    "address_line_1": "10 Oak Avenue",
    "city": "Austin",
    "state": "TX",
    "zip_code": "78701",
}


def test_parse_top_level_name_and_parameters() -> None:
    body = {
        "message": {
            "type": "tool-calls",
            "call": {"id": "call-abc"},
            "toolCallList": [
                {
                    "id": "tc_1",
                    "name": "lookup_patient_by_phone",
                    "parameters": {"phone_number": "5125550101"},
                }
            ],
        }
    }
    msg_type, call_id, tools = parse_webhook_body(body)
    assert msg_type == "tool-calls"
    assert call_id == "call-abc"
    assert len(tools) == 1
    assert tools[0].tool_call_id == "tc_1"
    assert tools[0].name == "lookup_patient_by_phone"
    assert tools[0].arguments == {"phone_number": "5125550101"}


def test_parse_function_arguments_json_string() -> None:
    body = {
        "message": {
            "type": "tool-calls",
            "toolCallList": [
                {
                    "id": "tc_2",
                    "function": {
                        "name": "lookup_patient_by_phone",
                        "arguments": '{"phone_number": "512-555-0101"}',
                    },
                }
            ],
        }
    }
    _msg_type, _call_id, tools = parse_webhook_body(body)
    assert tools[0].name == "lookup_patient_by_phone"
    assert tools[0].arguments == {"phone_number": "512-555-0101"}


def test_format_tool_results_is_single_line_json_string() -> None:
    payload = format_tool_results([("tc_1", {"found": False})])
    assert payload["results"][0]["toolCallId"] == "tc_1"
    raw = payload["results"][0]["result"]
    assert raw == '{"found":false}'


def test_rejects_missing_secret(client: TestClient) -> None:
    response = client.post("/vapi/webhook", json={"message": {"type": "status-update"}})
    assert response.status_code == 401
    body = response.json()
    assert body["data"] is None
    assert body["error"]["code"] == "UNAUTHORIZED"


def test_rejects_wrong_secret(client: TestClient) -> None:
    response = client.post(
        "/vapi/webhook",
        headers=_headers(secret="wrong"),
        json={"message": {"type": "status-update"}},
    )
    assert response.status_code == 401


def test_end_of_call_report_acks_200(client: TestClient) -> None:
    response = client.post(
        "/vapi/webhook",
        headers=_headers(),
        json={
            "message": {
                "type": "end-of-call-report",
                "call": {"id": "call-xyz"},
                "endedReason": "hangup",
            }
        },
    )
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_lookup_top_level_shape_found(
    client: TestClient, service: FakePatientService
) -> None:
    patient_id = uuid.uuid4()
    service.by_phone["5125550101"] = SimpleNamespace(
        patient_id=patient_id,
        first_name="Jane",
        last_name="Doe",
    )
    response = client.post(
        "/vapi/webhook",
        headers=_headers(),
        json={
            "message": {
                "type": "tool-calls",
                "call": {"id": "call-1"},
                "toolCallList": [
                    {
                        "id": "tc_lookup",
                        "name": "lookup_patient_by_phone",
                        "parameters": {"phone_number": "(512) 555-0101"},
                    }
                ],
            }
        },
    )
    assert response.status_code == 200
    result = _result(response.json())
    assert result == {
        "found": True,
        "patient_id": str(patient_id),
        "first_name": "Jane",
        "last_name": "Doe",
    }
    assert response.json()["results"][0]["toolCallId"] == "tc_lookup"


def test_lookup_function_arguments_string_not_found(client: TestClient) -> None:
    response = client.post(
        "/vapi/webhook",
        headers=_headers(),
        json={
            "message": {
                "type": "tool-calls",
                "toolCallList": [
                    {
                        "id": "tc_miss",
                        "function": {
                            "name": "lookup_patient_by_phone",
                            "arguments": '{"phone_number": "5125550198"}',
                        },
                    }
                ],
            }
        },
    )
    assert response.status_code == 200
    assert _result(response.json()) == {"found": False}


def test_lookup_bad_phone_is_validation(client: TestClient) -> None:
    response = client.post(
        "/vapi/webhook",
        headers=_headers(),
        json={
            "message": {
                "type": "tool-calls",
                "toolCallList": [
                    {
                        "id": "tc_bad",
                        "name": "lookup_patient_by_phone",
                        "parameters": {"phone_number": "555"},
                    }
                ],
            }
        },
    )
    assert response.status_code == 200
    result = _result(response.json())
    assert result["success"] is False
    assert result["error_type"] == "validation"
    assert result["field_errors"][0]["field"] == "phone_number"


def test_register_success(client: TestClient, service: FakePatientService) -> None:
    response = client.post(
        "/vapi/webhook",
        headers=_headers(),
        json={
            "message": {
                "type": "tool-calls",
                "call": {"id": "call-reg"},
                "toolCallList": [
                    {
                        "id": "tc_reg",
                        "name": "register_patient",
                        "parameters": REGISTER_ARGS,
                    }
                ],
            }
        },
    )
    assert response.status_code == 200
    result = _result(response.json())
    assert result["success"] is True
    assert result["first_name"] == "Morgan"
    assert result["patient_id"]
    assert "all set" in result["next_step"].lower()
    assert len(service.created) == 1


def test_register_bad_zip_is_validation(client: TestClient) -> None:
    args = {**REGISTER_ARGS, "zip_code": "1234"}
    response = client.post(
        "/vapi/webhook",
        headers=_headers(),
        json={
            "message": {
                "type": "tool-calls",
                "toolCallList": [
                    {
                        "id": "tc_zip",
                        "name": "register_patient",
                        "parameters": args,
                    }
                ],
            }
        },
    )
    assert response.status_code == 200
    result = _result(response.json())
    assert result["success"] is False
    assert result["error_type"] == "validation"
    fields = [item["field"] for item in result["field_errors"]]
    assert "zip_code" in fields


def test_register_db_failure_is_server_200(
    client: TestClient, service: FakePatientService
) -> None:
    service.create_error = DatabaseUnavailable("SIMULATE_DB_FAILURE is enabled")
    response = client.post(
        "/vapi/webhook",
        headers=_headers(),
        json={
            "message": {
                "type": "tool-calls",
                "toolCallList": [
                    {
                        "id": "tc_db",
                        "name": "register_patient",
                        "parameters": REGISTER_ARGS,
                    }
                ],
            }
        },
    )
    assert response.status_code == 200
    result = _result(response.json())
    assert result["success"] is False
    assert result["error_type"] == "server"
    assert "not" in result["next_step"].lower() or "Do not say" in result["next_step"]


def test_update_unknown_patient_is_validation(
    client: TestClient, service: FakePatientService
) -> None:
    service.update_error = NotFound("Patient not found")
    response = client.post(
        "/vapi/webhook",
        headers=_headers(),
        json={
            "message": {
                "type": "tool-calls",
                "toolCallList": [
                    {
                        "id": "tc_upd",
                        "name": "update_patient",
                        "parameters": {
                            "patient_id": str(uuid.uuid4()),
                            "zip_code": "78702",
                        },
                    }
                ],
            }
        },
    )
    assert response.status_code == 200
    result = _result(response.json())
    assert result["success"] is False
    assert result["error_type"] == "validation"
    assert result["field_errors"][0]["field"] == "patient_id"
