"""Patient CRUD used by the REST API and, later, voice tools."""

from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timezone

from sqlalchemy import Select, func, select
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import DatabaseUnavailable, NotFound, ValidationFailed
from app.db.models import Patient, SexType
from app.schemas.patient import PatientCreate, PatientOut, PatientUpdate

logger = logging.getLogger(__name__)


class PatientService:
    """Server-side patient operations. Voice tools must call this, not SQL."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def create(self, payload: PatientCreate) -> Patient:
        """Insert a patient after schema validation already ran."""
        self._maybe_simulate_failure()
        patient = Patient(
            first_name=payload.first_name,
            last_name=payload.last_name,
            date_of_birth=payload.date_of_birth,
            sex=SexType(payload.sex),
            phone_number=payload.phone_number,
            email=payload.email,
            address_line_1=payload.address_line_1,
            address_line_2=payload.address_line_2,
            city=payload.city,
            state=payload.state,
            zip_code=payload.zip_code,
            insurance_provider=payload.insurance_provider,
            insurance_member_id=payload.insurance_member_id,
            preferred_language=payload.preferred_language,
            emergency_contact_name=payload.emergency_contact_name,
            emergency_contact_phone=payload.emergency_contact_phone,
        )
        self.session.add(patient)
        await self._commit("create")
        await self.session.refresh(patient)
        logger.info("patient_created", extra={"payload": _log_payload(patient)})
        return patient

    async def get(self, patient_id: uuid.UUID) -> Patient:
        """Return one active patient or raise NotFound (missing or deleted)."""
        patient = await self.session.get(Patient, patient_id)
        if patient is None or patient.deleted_at is not None:
            raise NotFound("Patient not found")
        return patient

    async def list(
        self,
        *,
        last_name: str | None = None,
        date_of_birth: date | None = None,
        phone_number: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[Patient]:
        """Active patients, newest first. Filters are exact after normalization."""
        stmt: Select[tuple[Patient]] = select(Patient).where(Patient.deleted_at.is_(None))
        if last_name is not None:
            stmt = stmt.where(func.lower(Patient.last_name) == last_name.lower())
        if date_of_birth is not None:
            stmt = stmt.where(Patient.date_of_birth == date_of_birth)
        if phone_number is not None:
            stmt = stmt.where(Patient.phone_number == phone_number)
        stmt = stmt.order_by(Patient.created_at.desc()).limit(limit).offset(offset)
        try:
            result = await self.session.execute(stmt)
        except (OperationalError, SQLAlchemyError) as exc:
            raise DatabaseUnavailable("Database unavailable") from exc
        return list(result.scalars().all())

    async def update(self, patient_id: uuid.UUID, payload: PatientUpdate) -> Patient:
        """Apply a partial update. Only fields present on the payload change."""
        patient = await self.get(patient_id)
        self._maybe_simulate_failure()
        changes = payload.model_dump(exclude_unset=True)
        for field, value in changes.items():
            if field == "sex" and value is not None:
                setattr(patient, field, SexType(value))
            else:
                setattr(patient, field, value)
        await self._commit("update")
        await self.session.refresh(patient)
        logger.info("patient_updated", extra={"payload": _log_payload(patient)})
        return patient

    async def soft_delete(self, patient_id: uuid.UUID) -> Patient:
        """Set deleted_at. Never hard-delete. Second call is NotFound."""
        patient = await self.get(patient_id)
        self._maybe_simulate_failure()
        patient.deleted_at = datetime.now(timezone.utc)
        await self._commit("soft_delete")
        await self.session.refresh(patient)
        logger.info(
            "patient_deleted",
            extra={"patient_id": str(patient.patient_id)},
        )
        return patient

    async def find_active_by_phone(self, phone_number: str) -> Patient | None:
        """Newest active patient with this normalized phone, or None."""
        stmt = (
            select(Patient)
            .where(Patient.phone_number == phone_number, Patient.deleted_at.is_(None))
            .order_by(Patient.created_at.desc())
            .limit(1)
        )
        try:
            result = await self.session.execute(stmt)
        except (OperationalError, SQLAlchemyError) as exc:
            raise DatabaseUnavailable("Database unavailable") from exc
        return result.scalar_one_or_none()

    def _maybe_simulate_failure(self) -> None:
        settings = get_settings()
        if settings.is_development and settings.simulate_db_failure:
            raise DatabaseUnavailable("SIMULATE_DB_FAILURE is enabled")

    async def _commit(self, action: str) -> None:
        try:
            await self.session.commit()
        except IntegrityError as exc:
            await self.session.rollback()
            raise ValidationFailed("Invalid input", details=_integrity_details(exc)) from exc
        except (OperationalError, SQLAlchemyError) as exc:
            await self.session.rollback()
            logger.exception("patient_%s_db_error", action)
            raise DatabaseUnavailable("Database unavailable") from exc


def _log_payload(patient: Patient) -> dict:
    """Final stored payload for the brief's required create/update log line."""
    return PatientOut.model_validate(patient).model_dump(mode="json")


def _integrity_details(exc: IntegrityError) -> list[dict[str, str]]:
    """Best-effort field mapping from a Postgres CHECK / constraint error."""
    raw = str(exc.orig) if exc.orig is not None else str(exc)
    lowered = raw.lower()
    field_hints = (
        ("phone_number", "phone_number"),
        ("emergency_contact_phone", "emergency_contact_phone"),
        ("date_of_birth", "date_of_birth"),
        ("zip_code", "zip_code"),
        ("first_name", "first_name"),
        ("last_name", "last_name"),
        ("email", "email"),
        ("state", "state"),
        ("insurance_member_id", "insurance_member_id"),
    )
    for needle, field in field_hints:
        if needle in lowered:
            return [{"field": field, "message": "Value failed a database constraint"}]
    return [{"field": "body", "message": "Value failed a database constraint"}]
