"""Adapter parsing for Vapi end-of-call-report payloads."""

from __future__ import annotations

from app.services.call_log_service import _resolve_status
from app.telephony.vapi_adapter import parse_end_of_call_report


def test_parse_end_of_call_report_common_shape() -> None:
    report = parse_end_of_call_report(
        {
            "message": {
                "type": "end-of-call-report",
                "endedReason": "hangup",
                "startedAt": "2026-09-24T12:00:00.000Z",
                "endedAt": "2026-09-24T12:02:00.000Z",
                "call": {"id": "call-1"},
                "customer": {"number": "+17579087431"},
                "artifact": {
                    "transcript": "AI: Hello",
                    "recording": {"stereoUrl": "https://cdn.example/r.wav"},
                },
                "analysis": {"summary": "Brief call"},
            }
        }
    )
    assert report["vapi_call_id"] == "call-1"
    assert report["ended_reason"] == "hangup"
    assert report["transcript"] == "AI: Hello"
    assert report["summary"] == "Brief call"
    assert report["recording_url"] == "https://cdn.example/r.wav"
    assert report["caller_number"] == "+17579087431"
    assert report["started_at"] is not None
    assert report["ended_at"] is not None


def test_resolve_status_incomplete_without_patient() -> None:
    assert _resolve_status(ended_reason="customer-ended-call", patient_id=None) == "incomplete"


def test_resolve_status_completed_with_patient() -> None:
    import uuid

    assert (
        _resolve_status(ended_reason="assistant-ended-call", patient_id=uuid.uuid4())
        == "completed"
    )


def test_resolve_status_failed_on_error_reason() -> None:
    assert _resolve_status(ended_reason="pipeline-error-openai", patient_id=None) == "failed"
