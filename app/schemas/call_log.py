"""Call-log response schemas."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


class CallLogOut(BaseModel):
    """API representation of one call_logs row. Timestamps are UTC with Z."""

    model_config = ConfigDict(from_attributes=True)

    call_log_id: uuid.UUID
    vapi_call_id: str
    patient_id: uuid.UUID | None
    caller_number: str | None
    status: str
    ended_reason: str | None
    summary: str | None
    transcript: str | None
    recording_url: str | None
    collected_payload: dict[str, Any] | None
    started_at: str | None
    ended_at: str | None
    created_at: str
    updated_at: str

    @field_validator(
        "started_at",
        "ended_at",
        "created_at",
        "updated_at",
        mode="before",
    )
    @classmethod
    def _ts_out(cls, value: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        return str(value)
