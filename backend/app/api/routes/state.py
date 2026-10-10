from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query
from pydantic import AwareDatetime

from app.api.deps import AppSettings, DbSession
from app.core.errors import NotFoundError
from app.schemas.consultation import ConsultationState, ConsultStage
from app.schemas.physician import PhysicianState
from app.schemas.state import OperationalState
from app.services.state import StateService

router = APIRouter(tags=["state"])

AsOf = Annotated[
    AwareDatetime | None,
    Query(
        description=(
            "Reconstruct at this time (ISO-8601 with offset). Defaults to the simulation clock."
        )
    ),
]


@router.get(
    "/state", response_model=OperationalState, summary="Full reconstructed operational state"
)
def get_state(db: DbSession, settings: AppSettings, as_of: AsOf = None) -> OperationalState:
    return StateService(db, settings).state(as_of)


@router.get("/physicians", response_model=list[PhysicianState])
def list_physicians(
    db: DbSession,
    settings: AppSettings,
    as_of: AsOf = None,
    on_shift: Annotated[bool | None, Query()] = None,
) -> list[PhysicianState]:
    physicians = StateService(db, settings).state(as_of).physicians
    if on_shift is not None:
        physicians = [p for p in physicians if bool(p.on_shift) == on_shift]
    return physicians


@router.get("/physicians/{physician_id}", response_model=PhysicianState)
def get_physician(
    db: DbSession, settings: AppSettings, physician_id: str, as_of: AsOf = None
) -> PhysicianState:
    for p in StateService(db, settings).state(as_of).physicians:
        if p.physician_id == physician_id:
            return p
    raise NotFoundError(f"Physician '{physician_id}' not found")


@router.get("/consultations", response_model=list[ConsultationState])
def list_consultations(
    db: DbSession,
    settings: AppSettings,
    as_of: AsOf = None,
    is_open: Annotated[bool | None, Query(alias="open")] = None,
    hospital_id: str | None = None,
    physician_id: str | None = None,
    stage: ConsultStage | None = None,
) -> list[ConsultationState]:
    consults = StateService(db, settings).state(as_of).consultations
    return [
        c
        for c in consults
        if (is_open is None or c.is_open == is_open)
        and (hospital_id is None or c.hospital_id == hospital_id)
        and (physician_id is None or c.assigned_physician_id == physician_id)
        and (stage is None or c.stage is stage)
    ]


@router.get("/consultations/{consult_id}", response_model=ConsultationState)
def get_consultation(
    db: DbSession, settings: AppSettings, consult_id: str, as_of: AsOf = None
) -> ConsultationState:
    for c in StateService(db, settings).state(as_of).consultations:
        if c.consult_id == consult_id:
            return c
    raise NotFoundError(f"Consultation '{consult_id}' not found")
