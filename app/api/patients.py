"""REST routes for patients. No SQL or business rules here."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import validators as v
from app.db.session import get_session
from app.schemas.envelope import ApiResponse, success
from app.schemas.patient import PatientCreate, PatientOut, PatientUpdate
from app.services.patient_service import PatientService

router = APIRouter(prefix="/patients", tags=["patients"])


def _service(session: Annotated[AsyncSession, Depends(get_session)]) -> PatientService:
    return PatientService(session)


def _parse_patient_id(patient_id: str) -> uuid.UUID:
    """Reject malformed UUIDs with 400 (not FastAPI's default 422)."""
    try:
        return uuid.UUID(patient_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid patient id") from exc


def _to_out(patient: object) -> dict:
    return PatientOut.model_validate(patient).model_dump(mode="json")


@router.get(
    "",
    response_model=ApiResponse[list[PatientOut]],
    responses={400: {"description": "Bad filter"}},
)
async def list_patients(
    service: Annotated[PatientService, Depends(_service)],
    last_name: Annotated[str | None, Query()] = None,
    date_of_birth: Annotated[str | None, Query()] = None,
    phone_number: Annotated[str | None, Query()] = None,
    limit: Annotated[int, Query()] = 50,
    offset: Annotated[int, Query()] = 0,
) -> dict:
    """List active patients. Newest first. Soft-deleted rows are omitted."""
    dob = None
    phone = None
    name = None
    try:
        if last_name is not None:
            name = v.collapse_spaces(last_name)
            if not name:
                raise ValueError("last_name filter is empty")
        if date_of_birth is not None:
            dob = v.normalize_dob(date_of_birth)
        if phone_number is not None:
            phone = v.normalize_phone(phone_number, field="phone_number")
        if limit < 1 or limit > 200:
            raise ValueError("limit must be between 1 and 200")
        if offset < 0:
            raise ValueError("offset must be 0 or greater")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    patients = await service.list(
        last_name=name,
        date_of_birth=dob,
        phone_number=phone,
        limit=limit,
        offset=offset,
    )
    return success([_to_out(item) for item in patients])


@router.get(
    "/{patient_id}",
    response_model=ApiResponse[PatientOut],
    responses={400: {"description": "Bad UUID"}, 404: {"description": "Not found"}},
)
async def get_patient(
    patient_id: str,
    service: Annotated[PatientService, Depends(_service)],
) -> dict:
    """Get one active patient by UUID."""
    patient = await service.get(_parse_patient_id(patient_id))
    return success(_to_out(patient))


@router.post(
    "",
    response_model=ApiResponse[PatientOut],
    status_code=status.HTTP_201_CREATED,
    responses={400: {"description": "Malformed JSON"}, 422: {"description": "Validation error"}},
)
async def create_patient(
    payload: PatientCreate,
    service: Annotated[PatientService, Depends(_service)],
) -> JSONResponse:
    """Create a patient. Server-side validation is authoritative."""
    patient = await service.create(payload)
    return JSONResponse(status_code=201, content=success(_to_out(patient)))


@router.put(
    "/{patient_id}",
    response_model=ApiResponse[PatientOut],
    responses={
        400: {"description": "Bad UUID or empty body"},
        404: {"description": "Not found"},
        422: {"description": "Validation error"},
    },
)
async def update_patient(
    patient_id: str,
    payload: PatientUpdate,
    service: Annotated[PatientService, Depends(_service)],
) -> dict:
    """Partial update. Omit a field to leave it unchanged."""
    if not payload.model_fields_set:
        raise HTTPException(status_code=400, detail="Empty body")
    patient = await service.update(_parse_patient_id(patient_id), payload)
    return success(_to_out(patient))


@router.delete(
    "/{patient_id}",
    response_model=ApiResponse[PatientOut],
    responses={400: {"description": "Bad UUID"}, 404: {"description": "Not found"}},
)
async def delete_patient(
    patient_id: str,
    service: Annotated[PatientService, Depends(_service)],
) -> dict:
    """Soft-delete. The row stays; deleted_at is set. Repeat delete is 404."""
    patient = await service.soft_delete(_parse_patient_id(patient_id))
    return success(_to_out(patient))
