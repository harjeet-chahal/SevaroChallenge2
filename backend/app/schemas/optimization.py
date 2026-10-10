"""Optimizer-ready snapshot for Phase 4 (OR-Tools matching / staffing).

Data only: nothing here assigns consults or makes offers. Phase 4 solvers consume this
instead of re-deriving state, so the optimizer and the dashboard always agree.
"""

from __future__ import annotations

from pydantic import AwareDatetime, Field

from app.schemas.common import ApiModel, EntityId


class DeficitInterval(ApiModel):
    start: AwareDatetime
    end: AwareDatetime
    required: int
    available: int
    available_confirmed: int
    deficit: int


class OptHospital(ApiModel):
    hospital_id: EntityId
    timezone: str
    required_now: int | None
    deficit_now: int | None
    deficit_physician_minutes: float
    deficit_intervals: list[DeficitInterval]
    spike_active: bool | None


class OptPhysician(ApiModel):
    physician_id: EntityId
    roster: str
    roster_role: str | None
    on_shift: bool | None
    availability: str
    activity: str
    credentialed_hospital_ids: list[EntityId]
    shift_start: AwareDatetime | None
    shift_end: AwareDatetime | None
    shift_end_known: bool
    consults_this_shift: int
    calls_this_shift: int
    open_consult_ids: list[EntityId]
    open_note_consult_ids: list[EntityId]
    phone_ringing: bool
    last_call_ended_at: AwareDatetime | None
    uncertainty_flags: list[str]
    split_shift_opt_in: bool | None = None
    last_shift_ended_at: AwareDatetime | None = None
    next_shift_starts_at: AwareDatetime | None = None
    hours_worked_trailing_7d: float | None = None
    minutes_to_come_online: int | None = None
    offers_declined_30d: int | None = None


class OptConsult(ApiModel):
    consult_id: EntityId
    hospital_id: EntityId | None
    consult_type: str | None
    consult_category: str | None
    stage: str
    assigned_physician_id: EntityId | None
    seconds_since_received: int | None
    seconds_in_stage: int
    routing_failures: int
    max_alert_severity: str | None
    next_threshold_at: AwareDatetime | None
    """When the next documented stage standard (warning or critical) will be crossed."""
    credentialed_on_shift_physician_ids: list[EntityId]


class CoverageEffect(ApiModel):
    hospital_id: EntityId
    deficit_physician_minutes_before: float
    deficit_physician_minutes_after: float
    reduction: float


class CandidateIntervention(ApiModel):
    """Hypothetical: what adding this physician's coverage would do. Not an offer."""

    kind: str = "add_physician_coverage"
    physician_id: EntityId
    available_from: AwareDatetime
    available_until: AwareDatetime
    effects: list[CoverageEffect]
    total_reduction: float
    eligibility_evaluated: bool = False
    notes: list[str] = Field(default_factory=list)


class OptimizationInput(ApiModel):
    as_of: AwareDatetime
    horizon_end: AwareDatetime
    data_version: int
    hospitals: list[OptHospital]
    physicians: list[OptPhysician]
    consults: list[OptConsult]
    candidate_interventions: list[CandidateIntervention]
    modeling_notes: list[str]
