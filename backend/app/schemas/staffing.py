"""Split-shift staffing recommendations (Phase 4, Optimizer B). Proposals only.

No offer is created, approved or sent here. A recommended split shift becomes an offer
only through the clinical-lead approval workflow (Phase 5).
"""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, Field

from app.schemas.common import ApiModel, EntityId
from app.schemas.dispatch import RuleCheck, SolverRun


class CandidateEligibility(ApiModel):
    """Every off-shift physician considered, with each split-shift rule passed or failed."""

    physician_id: EntityId
    display_name: str
    roster_role: str | None
    eligible: bool
    failed_rules: list[str]
    checks: list[RuleCheck]
    gap_hospital_ids: list[EntityId]
    """Credentialed hospitals that have a deficit in the planning window."""
    earliest_valid_start: AwareDatetime | None
    latest_valid_end: AwareDatetime | None
    max_offer_minutes: int | None
    remaining_weekly_hours: float | None
    minutes_to_come_online: int | None
    online_time_assumed: bool = False
    proposed_start: AwareDatetime | None = None
    proposed_minutes: int | None = None
    missing_data: list[str] = Field(default_factory=list)
    summary: str


class HospitalEffect(ApiModel):
    hospital_id: EntityId
    hospital_name: str
    deficit_physician_minutes_before: float
    deficit_physician_minutes_after: float
    reduction: float
    horizon_minutes: int


class TrapProtection(ApiModel):
    """How the joining physician is protected from the split-shift trap (simulated only)."""

    routing_scope_hospital_ids: list[EntityId]
    excluded_credentialed_hospital_ids: list[EntityId]
    seeded_consult_count: int
    seed_policy: str
    sync_capacity: int
    rationale: list[str]


class ShiftRecommendation(ApiModel):
    physician_id: EntityId
    display_name: str
    offer_start: AwareDatetime
    offer_end: AwareDatetime
    offer_minutes: int
    online_at: AwareDatetime
    """Offer start + estimated time to come online: when coverage is modeled to begin."""
    effective_minutes: int
    hospital_ids: list[EntityId]
    hospital_names: list[str]
    effects: list[HospitalEffect]
    reduction_physician_minutes: float
    excess_physician_minutes: float
    """Coverage above requirement this offer adds (inside the planning window)."""
    protection: TrapProtection
    explanation: list[str]
    status: Literal["proposed"] = "proposed"
    requires_approval: Literal[True] = True


class StaffingTotals(ApiModel):
    planning_horizon_minutes: int
    deficit_physician_minutes_before: float
    deficit_physician_minutes_after: float
    reduction: float
    physicians_used: int
    offered_minutes: int
    excess_physician_minutes: float
    fully_covered: bool


class TrapRoutingOutcome(ApiModel):
    policy: Literal["unrestricted_least_loaded", "protected"]
    modeled_arrivals: int
    routed_to_joiner: int
    routed_to_joiner_at_gap_hospitals: int
    routed_to_joiner_elsewhere: int
    joiner_final_consults: int
    peer_median_consults: float | None
    max_consults_any_physician: int
    unrouted: int
    by_hospital: dict[str, dict[str, int]]
    """hospital_id -> {"arrivals", "to_joiner"}."""


class TrapAnalysis(ApiModel):
    """Modeled demonstration of the split-shift trap for the top recommendation.

    Arrivals are modeled deterministically from the hospital's baseline hourly mean (not
    forecast patients). Busy time is not modeled: it isolates the brief's rule 3-4 effect.
    """

    physician_id: EntityId
    display_name: str
    window_start: AwareDatetime
    window_end: AwareDatetime
    unrestricted: TrapRoutingOutcome
    protected: TrapRoutingOutcome
    conclusion: str
    assumptions: list[str]


class StaffingResult(ApiModel):
    as_of: AwareDatetime
    data_version: int
    policy_version: str
    label: str = "Proposed — no offer has been sent. Requires clinical-lead approval."
    planning_horizon_end: AwareDatetime
    solver: SolverRun
    gap_hospital_ids: list[EntityId]
    candidates: list[CandidateEligibility]
    recommendations: list[ShiftRecommendation]
    totals: StaffingTotals
    trap: TrapAnalysis | None
    infeasibility: list[str] = Field(default_factory=list)
    rules: list[str]
    assumptions: list[str]
    explanations: list[str]
