"""Persist Vapi call transcripts and link them to patients."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import DatabaseUnavailable, NotFound
from app.db.models import CallLog, Patient

logger = logging.getLogger(__name__)


class CallLogService:
    """Upsert call_logs from end-of-call reports and register/update links."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def link_patient(
        self,
        vapi_call_id: str,
        patient_id: uuid.UUID,
        *,
        collected_payload: dict[str, Any] | None = None,
    ) -> CallLog:
        """Attach a patient to this call as soon as register/update succeeds."""
        row = await self._get_by_vapi_id(vapi_call_id)
        if row is None:
            row = CallLog(
                vapi_call_id=vapi_call_id,
                patient_id=patient_id,
                status="in_progress",
                collected_payload=collected_payload,
            )
            self.session.add(row)
        else:
            row.patient_id = patient_id
            if collected_payload is not None:
                row.collected_payload = collected_payload
        await self._commit("link_patient")
        await self.session.refresh(row)
        logger.info(
            "call_log_linked",
            extra={
                "vapi_call_id": vapi_call_id,
                "patient_id": str(patient_id),
            },
        )
        return row

    async def upsert_from_report(self, report: dict[str, Any]) -> CallLog | None:
        """Create or update a call_logs row from a parsed end-of-call report.

        Always returns a row when vapi_call_id is present. Returns None if the
        report has no call id (still ACK upstream so Vapi does not retry forever).
        """
        vapi_call_id = report.get("vapi_call_id")
        if not isinstance(vapi_call_id, str) or not vapi_call_id.strip():
            logger.warning("call_log_upsert_missing_call_id")
            return None
        vapi_call_id = vapi_call_id.strip()

        row = await self._get_by_vapi_id(vapi_call_id)
        if row is None:
            row = CallLog(vapi_call_id=vapi_call_id)
            self.session.add(row)

        if report.get("caller_number"):
            row.caller_number = str(report["caller_number"])[:20]
        if report.get("ended_reason") is not None:
            row.ended_reason = str(report["ended_reason"])[:100]
        if report.get("summary") is not None:
            row.summary = str(report["summary"])
        if report.get("transcript") is not None:
            row.transcript = str(report["transcript"])
        if report.get("recording_url") is not None:
            row.recording_url = str(report["recording_url"])
        if report.get("started_at") is not None:
            row.started_at = report["started_at"]
        if report.get("ended_at") is not None:
            row.ended_at = report["ended_at"]

        row.status = _resolve_status(
            ended_reason=row.ended_reason,
            patient_id=row.patient_id,
        )
        await self._commit("upsert_from_report")
        await self.session.refresh(row)
        logger.info(
            "call_log_upserted",
            extra={
                "vapi_call_id": vapi_call_id,
                "status": row.status,
                "patient_id": str(row.patient_id) if row.patient_id else None,
            },
        )
        return row

    async def list_for_patient(self, patient_id: uuid.UUID) -> list[CallLog]:
        """Newest-first call logs for an active patient. 404 if patient missing."""
        patient = await self.session.get(Patient, patient_id)
        if patient is None or patient.deleted_at is not None:
            raise NotFound("Patient not found")
        stmt = (
            select(CallLog)
            .where(CallLog.patient_id == patient_id)
            .order_by(CallLog.created_at.desc())
        )
        try:
            result = await self.session.execute(stmt)
        except (OperationalError, SQLAlchemyError) as exc:
            raise DatabaseUnavailable("Database unavailable") from exc
        return list(result.scalars().all())

    async def _get_by_vapi_id(self, vapi_call_id: str) -> CallLog | None:
        stmt = select(CallLog).where(CallLog.vapi_call_id == vapi_call_id).limit(1)
        try:
            result = await self.session.execute(stmt)
        except (OperationalError, SQLAlchemyError) as exc:
            raise DatabaseUnavailable("Database unavailable") from exc
        return result.scalar_one_or_none()

    async def _commit(self, action: str) -> None:
        try:
            await self.session.commit()
        except IntegrityError:
            await self.session.rollback()
            # Race: another request inserted the same vapi_call_id. Re-load and retry once.
            logger.warning("call_log_%s_integrity_retry", action)
            raise
        except (OperationalError, SQLAlchemyError) as exc:
            await self.session.rollback()
            logger.exception("call_log_%s_db_error", action)
            raise DatabaseUnavailable("Database unavailable") from exc


def _resolve_status(*, ended_reason: str | None, patient_id: uuid.UUID | None) -> str:
    """Hangup with no save -> incomplete; linked patient -> completed; errors -> failed."""
    reason = (ended_reason or "").lower()
    if any(token in reason for token in ("error", "failed", "pipeline-error")):
        return "failed"
    if patient_id is not None:
        return "completed"
    return "incomplete"
