"""Demand-spike evaluation: trailing-window arrivals vs the hospital's hourly p90 baseline."""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, Field

from app.schemas.common import ApiModel, EntityId

BaselineStatus = Literal["ok", "missing", "day_type_mismatch", "ambiguous_day_type"]


class DemandEvaluation(ApiModel):
    hospital_id: EntityId
    at: AwareDatetime
    window_start: AwareDatetime
    """Exclusive: arrivals strictly after this instant count."""
    window_end: AwareDatetime
    """Inclusive."""
    arrivals: int = Field(ge=0)
    """Distinct consults received in the window (duplicates never counted twice)."""
    consult_ids: list[EntityId] = Field(default_factory=list)
    local_hour: int
    local_hour_label: str
    """e.g. '18:00–19:00 EDT' — the hospital-local hour whose baseline applies."""
    baseline_status: BaselineStatus
    baseline_day_type: str | None = None
    baseline_mean: float | None = None
    baseline_p90: float | None = None
    spike: bool | None
    """arrivals > p90. None when the baseline cannot be used."""
    requirement_adjustment: int | None
    excess_over_p90: float | None = None
    known_arrivals_only: bool = False
    """True for future instants: only arrivals already visible are counted (a lower bound)."""
    comparison: str
    """The exact comparison performed, in words."""


class HospitalDemand(ApiModel):
    hospital_id: EntityId
    hospital_name: str
    timezone: str
    current: DemandEvaluation
    spike_ends_at: AwareDatetime | None = None
    """If spiking now: when known arrivals age out enough to end it (no new arrivals assumed)."""
    consults_without_received_time: int = 0


class DemandReport(ApiModel):
    as_of: AwareDatetime
    window_minutes: int
    requirement_increase: int
    rule: str
    method: str
    hospitals: list[HospitalDemand]
