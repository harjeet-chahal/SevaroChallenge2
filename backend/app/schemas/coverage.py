"""Coverage requirements, demand baselines and the modeled coverage forecast.

Forecast figures are *modeled* from schedules, credentials and current signals. They are
not measured outcomes.
"""

from __future__ import annotations

from datetime import time
from typing import Literal

from pydantic import AwareDatetime, Field

from app.schemas.common import ApiModel, EntityId


class CoverageRequirement(ApiModel):
    """Minimum available, credentialed physicians for a hospital during a local time block."""

    hospital_id: EntityId
    block_start_local: time
    block_end_local: time
    """Local to the hospital's time zone. A block may wrap past midnight."""
    min_available_physicians: int = Field(ge=0)
    day_type: str | None = None


class BaselineVolume(ApiModel):
    """Historical consult volume for one hospital-hour (hospital local time)."""

    hospital_id: EntityId
    hour_local: int = Field(ge=0, le=23)
    mean_consults: float = Field(ge=0)
    p90_consults: float = Field(ge=0)
    day_type: str | None = None


Certainty = Literal["confirmed", "uncertain"]


class CoverageContributor(ApiModel):
    """How one physician relates to one hospital's coverage within the horizon."""

    physician_id: EntityId
    display_name: str
    status: Literal["counted", "joins_later", "excluded", "proposed", "pending_activation"]
    """``proposed`` appears only in what-if projections (never in the live forecast).
    ``pending_activation``: an accepted split shift not active yet (uncertain, Phase 5)."""
    certainty: Certainty | None = None
    counts_from: AwareDatetime | None = None
    counts_until: AwareDatetime | None = None
    """None while counted means the shift end is unknown (never fabricated)."""
    reasons: list[str] = Field(default_factory=list)


class CoverageSegment(ApiModel):
    """A half-open interval [start, end) over which required and available coverage are constant."""

    start: AwareDatetime
    end: AwareDatetime
    required_base: int | None
    """From coverage_requirements for the local time block. None = no requirement defined."""
    spike_adjustment: int | None
    """+N while a demand spike is active, 0 if not, None if it cannot be evaluated."""
    required: int | None
    available_confirmed: int
    available_uncertain: int
    available: int
    deficit: int | None
    """max(0, required - available). None when no requirement is defined."""
    deficit_if_uncertain_excluded: int | None
    counted_physician_ids: list[EntityId] = Field(default_factory=list)
    uncertain_physician_ids: list[EntityId] = Field(default_factory=list)


class CoveragePoint(ApiModel):
    """Chart sample. ``kind`` says why the point exists; boundary points are exact."""

    at: AwareDatetime
    kind: Literal["now", "boundary", "interval", "horizon_end"]
    required: int | None
    available_confirmed: int
    available_uncertain: int
    deficit: int | None
    spike_active: bool | None


class CoverageAnnotation(ApiModel):
    at: AwareDatetime
    kind: Literal[
        "shift_end",
        "shift_start",
        "requirement_change",
        "spike_start",
        "spike_end",
        "dst_transition",
    ]
    label: str
    physician_id: EntityId | None = None


class CoverageRiskMetrics(ApiModel):
    required_now: int | None
    available_now: int
    deficit_now: int | None
    first_shortfall_at: AwareDatetime | None
    minutes_until_shortfall: float | None
    shortfall_minutes: float
    """Total minutes within the horizon with a deficit > 0."""
    worst_deficit: int
    deficit_physician_minutes: float
    """Integral of max(0, R(t) - A(t)) over the horizon, in physician-minutes (modeled)."""
    deficit_physician_minutes_if_uncertain_excluded: float
    confidence: Literal["confirmed", "uncertain", "unknown"]
    uncertainty_reasons: list[str] = Field(default_factory=list)


class HospitalCoverage(ApiModel):
    hospital_id: EntityId
    hospital_name: str
    timezone: str
    as_of: AwareDatetime
    horizon_end: AwareDatetime
    requirement_defined: bool
    metrics: CoverageRiskMetrics
    segments: list[CoverageSegment]
    points: list[CoveragePoint]
    annotations: list[CoverageAnnotation]
    contributors: list[CoverageContributor]
    explanations: list[str]


class CoverageReport(ApiModel):
    as_of: AwareDatetime
    horizon_minutes: int
    horizon_end: AwareDatetime
    chart_step_minutes: int
    data_version: int = 0
    method: str
    assumptions: list[str]
    hospitals: list[HospitalCoverage]
