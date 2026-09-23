"""Patient request/response schemas. Normalization lives in core.validators."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from app.core import validators as v

_REQUIRED_ON_UPDATE = {
    "first_name",
    "last_name",
    "date_of_birth",
    "sex",
    "phone_number",
    "address_line_1",
    "city",
    "state",
    "zip_code",
}


class PatientCreate(BaseModel):
    """Body for POST /patients. Client-sent ids and timestamps are ignored."""

    model_config = ConfigDict(extra="ignore")

    first_name: str
    last_name: str
    date_of_birth: date
    sex: str
    phone_number: str
    email: str | None = None
    address_line_1: str
    address_line_2: str | None = None
    city: str
    state: str
    zip_code: str
    insurance_provider: str | None = None
    insurance_member_id: str | None = None
    preferred_language: str = "English"
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None

    @field_validator("first_name", mode="before")
    @classmethod
    def _first_name(cls, value: object) -> str:
        return v.normalize_name(value, field="first_name")

    @field_validator("last_name", mode="before")
    @classmethod
    def _last_name(cls, value: object) -> str:
        return v.normalize_name(value, field="last_name")

    @field_validator("date_of_birth", mode="before")
    @classmethod
    def _dob(cls, value: object) -> date:
        return v.normalize_dob(value)

    @field_validator("sex", mode="before")
    @classmethod
    def _sex(cls, value: object) -> str:
        return v.normalize_sex(value)

    @field_validator("phone_number", mode="before")
    @classmethod
    def _phone(cls, value: object) -> str:
        return v.normalize_phone(value, field="phone_number")

    @field_validator("email", mode="before")
    @classmethod
    def _email(cls, value: object) -> str | None:
        return v.normalize_email(value)

    @field_validator("address_line_1", mode="before")
    @classmethod
    def _addr1(cls, value: object) -> str:
        return v.normalize_address_line_1(value)

    @field_validator("address_line_2", mode="before")
    @classmethod
    def _addr2(cls, value: object) -> str | None:
        return v.normalize_address_line_2(value)

    @field_validator("city", mode="before")
    @classmethod
    def _city(cls, value: object) -> str:
        return v.normalize_city(value)

    @field_validator("state", mode="before")
    @classmethod
    def _state(cls, value: object) -> str:
        return v.normalize_state(value)

    @field_validator("zip_code", mode="before")
    @classmethod
    def _zip(cls, value: object) -> str:
        return v.normalize_zip(value)

    @field_validator("insurance_provider", mode="before")
    @classmethod
    def _insurer(cls, value: object) -> str | None:
        return v.normalize_insurance_provider(value)

    @field_validator("insurance_member_id", mode="before")
    @classmethod
    def _member_id(cls, value: object) -> str | None:
        return v.normalize_member_id(value)

    @field_validator("preferred_language", mode="before")
    @classmethod
    def _language(cls, value: object) -> str:
        return v.normalize_language(value)

    @field_validator("emergency_contact_name", mode="before")
    @classmethod
    def _ec_name(cls, value: object) -> str | None:
        return v.normalize_emergency_name(value)

    @field_validator("emergency_contact_phone", mode="before")
    @classmethod
    def _ec_phone(cls, value: object) -> str | None:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return v.normalize_phone(value, field="emergency_contact_phone")


class PatientUpdate(BaseModel):
    """Partial update. Only sent fields change. Null clears optional fields."""

    model_config = ConfigDict(extra="ignore")

    first_name: str | None = None
    last_name: str | None = None
    date_of_birth: date | None = None
    sex: str | None = None
    phone_number: str | None = None
    email: str | None = None
    address_line_1: str | None = None
    address_line_2: str | None = None
    city: str | None = None
    state: str | None = None
    zip_code: str | None = None
    insurance_provider: str | None = None
    insurance_member_id: str | None = None
    preferred_language: str | None = None
    emergency_contact_name: str | None = None
    emergency_contact_phone: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _reject_null_required(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        for field in _REQUIRED_ON_UPDATE:
            if field in data and data[field] is None:
                raise ValueError(f"{field} cannot be null")
        return data

    @field_validator("first_name", mode="before")
    @classmethod
    def _first_name(cls, value: object) -> str | None:
        return None if value is None else v.normalize_name(value, field="first_name")

    @field_validator("last_name", mode="before")
    @classmethod
    def _last_name(cls, value: object) -> str | None:
        return None if value is None else v.normalize_name(value, field="last_name")

    @field_validator("date_of_birth", mode="before")
    @classmethod
    def _dob(cls, value: object) -> date | None:
        return None if value is None else v.normalize_dob(value)

    @field_validator("sex", mode="before")
    @classmethod
    def _sex(cls, value: object) -> str | None:
        return None if value is None else v.normalize_sex(value)

    @field_validator("phone_number", mode="before")
    @classmethod
    def _phone(cls, value: object) -> str | None:
        return None if value is None else v.normalize_phone(value, field="phone_number")

    @field_validator("email", mode="before")
    @classmethod
    def _email(cls, value: object) -> str | None:
        return v.normalize_email(value)

    @field_validator("address_line_1", mode="before")
    @classmethod
    def _addr1(cls, value: object) -> str | None:
        return None if value is None else v.normalize_address_line_1(value)

    @field_validator("address_line_2", mode="before")
    @classmethod
    def _addr2(cls, value: object) -> str | None:
        return v.normalize_address_line_2(value)

    @field_validator("city", mode="before")
    @classmethod
    def _city(cls, value: object) -> str | None:
        return None if value is None else v.normalize_city(value)

    @field_validator("state", mode="before")
    @classmethod
    def _state(cls, value: object) -> str | None:
        return None if value is None else v.normalize_state(value)

    @field_validator("zip_code", mode="before")
    @classmethod
    def _zip(cls, value: object) -> str | None:
        return None if value is None else v.normalize_zip(value)

    @field_validator("insurance_provider", mode="before")
    @classmethod
    def _insurer(cls, value: object) -> str | None:
        return v.normalize_insurance_provider(value)

    @field_validator("insurance_member_id", mode="before")
    @classmethod
    def _member_id(cls, value: object) -> str | None:
        return v.normalize_member_id(value)

    @field_validator("preferred_language", mode="before")
    @classmethod
    def _language(cls, value: object) -> str | None:
        # NOT NULL in the database; null resets to the documented default.
        if value is None:
            return "English"
        return v.normalize_language(value)

    @field_validator("emergency_contact_name", mode="before")
    @classmethod
    def _ec_name(cls, value: object) -> str | None:
        return v.normalize_emergency_name(value)

    @field_validator("emergency_contact_phone", mode="before")
    @classmethod
    def _ec_phone(cls, value: object) -> str | None:
        if value is None or (isinstance(value, str) and not value.strip()):
            return None
        return v.normalize_phone(value, field="emergency_contact_phone")


class PatientOut(BaseModel):
    """API representation. DOB is MM/DD/YYYY; timestamps are UTC with Z."""

    model_config = ConfigDict(from_attributes=True)

    patient_id: uuid.UUID
    first_name: str
    last_name: str
    date_of_birth: str
    sex: str
    phone_number: str
    email: str | None
    address_line_1: str
    address_line_2: str | None
    city: str
    state: str
    zip_code: str
    insurance_provider: str | None
    insurance_member_id: str | None
    preferred_language: str
    emergency_contact_name: str | None
    emergency_contact_phone: str | None
    created_at: str
    updated_at: str
    deleted_at: str | None = None

    @field_validator("date_of_birth", mode="before")
    @classmethod
    def _dob_out(cls, value: object) -> str:
        if isinstance(value, datetime):
            value = value.date()
        if isinstance(value, date):
            return value.strftime("%m/%d/%Y")
        return str(value)

    @field_validator("created_at", "updated_at", "deleted_at", mode="before")
    @classmethod
    def _ts_out(cls, value: object) -> str | None:
        if value is None:
            return None
        if isinstance(value, datetime):
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
        return str(value)

    @field_validator("sex", mode="before")
    @classmethod
    def _sex_out(cls, value: object) -> str:
        return value.value if hasattr(value, "value") else str(value)
