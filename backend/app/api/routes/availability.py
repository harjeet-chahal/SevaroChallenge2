"""Voluntary availability endpoints (off-shift portal → coordinator scheduling).

Physicians (``X-Demo-Role: physician`` + ``X-Demo-Actor-Id``) share, update and withdraw
their own "I'm available" windows. Coordinators and clinical leads read them; the
split-shift ranking (``GET /api/optimization/split-shifts``) and proposals use them as a
preference after every rule. Submitting availability never assigns a shift.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, status

from app.api.deps import AppSettings, DbSession, DemoActor
from app.schemas.availability import (
    AvailabilityCreate,
    AvailabilityPage,
    AvailabilityUpdate,
    PhysicianAvailabilityPage,
    VolunteerAvailability,
)
from app.services.availability import AvailabilityService

router = APIRouter(prefix="/availability", tags=["availability"])


@router.get("", response_model=AvailabilityPage, summary="All shared availability (staff)")
def list_availability(
    actor: DemoActor,
    db: DbSession,
    settings: AppSettings,
    scope: Literal["active", "all"] = "active",
) -> AvailabilityPage:
    """``active``: windows that are shared and not over yet; ``all``: history included."""
    return AvailabilityService(db, settings).list_all(actor, scope)


@router.get(
    "/mine",
    response_model=PhysicianAvailabilityPage,
    summary="The calling physician's availability windows",
)
def my_availability(
    actor: DemoActor, db: DbSession, settings: AppSettings
) -> PhysicianAvailabilityPage:
    return AvailabilityService(db, settings).mine(actor)


@router.post(
    "",
    response_model=VolunteerAvailability,
    status_code=status.HTTP_201_CREATED,
    summary="Share an 'I'm available' window (physician)",
)
def create_availability(
    body: AvailabilityCreate, actor: DemoActor, db: DbSession, settings: AppSettings
) -> VolunteerAvailability:
    """Not a shift assignment: the window becomes a ranking preference for coordinators."""
    return AvailabilityService(db, settings).create(body, actor)


@router.get("/{availability_id}", response_model=VolunteerAvailability)
def get_availability(
    availability_id: str, actor: DemoActor, db: DbSession, settings: AppSettings
) -> VolunteerAvailability:
    return AvailabilityService(db, settings).get(availability_id, actor)


@router.put("/{availability_id}", response_model=VolunteerAvailability)
def update_availability(
    availability_id: str,
    body: AvailabilityUpdate,
    actor: DemoActor,
    db: DbSession,
    settings: AppSettings,
) -> VolunteerAvailability:
    return AvailabilityService(db, settings).update(availability_id, body, actor)


@router.post("/{availability_id}/withdraw", response_model=VolunteerAvailability)
def withdraw_availability(
    availability_id: str, actor: DemoActor, db: DbSession, settings: AppSettings
) -> VolunteerAvailability:
    """Withdraw a window; the voluntary preference disappears from recommendations."""
    return AvailabilityService(db, settings).withdraw(availability_id, actor)
