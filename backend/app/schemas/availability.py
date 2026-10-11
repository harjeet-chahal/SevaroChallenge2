"""Voluntary availability: an off-shift physician's "I'm available" window.

Submitting availability never assigns a shift. It tells the scheduling system that this
physician could cover an extra shift in that window; the coordinator's split-shift
ranking prefers them there, but every split-shift rule still applies, a clinical lead
still approves any offer, and the physician still accepts or declines it.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal

from pydantic import AwareDatetime, Field

from app.schemas.common import ApiModel, EntityId


class AvailabilityStatus(StrEnum):
    ACTIVE = "active"
    WITHDRAWN = "withdrawn"


class AvailabilityCreate(ApiModel):
    start_at: AwareDatetime
    end_at: AwareDatetime


class AvailabilityUpdate(ApiModel):
    start_at: AwareDatetime
    end_at: AwareDatetime
    expected_version: int | None = None
    """The version the physician was editing; a newer one gives 409 ``stale_version``."""


class VolunteerAvailability(ApiModel):
    id: EntityId
    physician_id: EntityId
    display_name: str
    status: AvailabilityStatus
    start_at: AwareDatetime
    end_at: AwareDatetime
    duration_minutes: int
    timezone: str
    """Display zone: the zone of the physician's first credentialed hospital."""
    created_at: AwareDatetime
    updated_at: AwareDatetime
    withdrawn_at: AwareDatetime | None = None
    version: int
    phase: Literal["upcoming", "current", "past", "withdrawn"]
    """Relative to the simulation clock."""
    can_update: bool = False
    can_withdraw: bool = False
    message: str


class PhysicianAvailabilityPage(ApiModel):
    """What the off-shift portal shows a physician about their own availability."""

    physician_id: EntityId
    display_name: str
    timezone: str
    simulation_time: AwareDatetime
    opted_in: bool | None
    min_useful_window_minutes: int
    """Shortest window that can hold a valid offer: 2 h of coverage plus the physician's
    time to come online. Shorter windows are accepted but cannot be matched to an offer."""
    max_window_minutes: int
    items: list[VolunteerAvailability]
    notes: list[str] = Field(default_factory=list)


class AvailabilityPage(ApiModel):
    total: int
    items: list[VolunteerAvailability]
