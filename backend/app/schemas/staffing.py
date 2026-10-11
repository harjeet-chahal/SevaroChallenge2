"""Split-shift staffing recommendations (Phase 4, Optimizer B). Proposals only.

No offer is created, approved or sent here. A recommended split shift becomes an offer
only through the clinical-lead approval workflow (Phase 5).
"""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, Field

from app.schemas.common import ApiModel, EntityId
from app.schemas.dispatch import RuleCheck, SolverRun

VoluntaryStatus = Literal[
    "applied",
    "not_eligible",
    "no_shortage_overlap",
    "no_offer_fits",
    "outside_tolerance",
    "not_needed",
    "disabled",
]


class VoluntaryMatch(ApiModel):
    """A physician's voluntary availability as the scheduling system sees it, and whether it
    changed the recommendation. Availability is a preference, never an assignment: it only
    counts after every split-shift rule has passed."""

    availability_id: EntityId
    start_at: AwareDatetime
    end_at: AwareDatetime
    overlaps_shortage: bool
    """The window overlaps a forecast deficit at a short hospital this physician can cover."""
    overlap_minutes: float
    """Minutes of that shortage (any of their short hospitals) inside the window."""
    shortage_start: AwareDatetime | None = None
    shortage_end: AwareDatetime | None = None
    offer_within_window: bool = False
    """The ranked/recommended offer starts and ends inside the volunteered window."""
    status: VoluntaryStatus
    message: str


class CostEstimate(ApiModel):
    """Estimated staffing cost of split-shift offers: paid offer time × hourly rate.

    ``basis`` is ``simulated`` (projected if accepted) unless it is computed from a shift
    that was actually completed (``confirmed``)."""

    basis: Literal["simulated", "confirmed"]
    paid_minutes: int
    hourly_rate: float
    currency: str
    amount: float
    covered_physician_minutes: float
    """Deficit physician-minutes the offer removes (planning window, modeled)."""
    cost_per_covered_hour: float | None = None
    """``amount`` per physician-hour of deficit removed: the cost-effectiveness measure."""
    note: str


class CostComparison(ApiModel):
    """One alternative staffing choice priced with the same cost model."""

    label: str
    physician_names: list[str]
    cost: CostEstimate
    deficit_after: float | None = None
    """Deficit physician-minutes left over the planning window with that choice."""
    saving: float
    """Alternative amount − recommended amount (negative: the recommendation costs more)."""
    basis: Literal["simulated", "confirmed"] = "simulated"
    explanation: str


class PlanCost(ApiModel):
    recommended: CostEstimate
    comparisons: list[CostComparison] = Field(default_factory=list)
    label: str = (
        "Simulated — projected if the offer is accepted. Not confirmed savings: a saving is "
        "confirmed only from a completed shift."
    )
    assumptions: list[str] = Field(default_factory=list)


class RankedOffer(ApiModel):
    start_at: AwareDatetime
    end_at: AwareDatetime
    minutes: int
    online_at: AwareDatetime
    hospital_ids: list[EntityId]


class RankedCandidate(ApiModel):
    """One off-shift physician's place in the ranking for a coverage need."""

    rank: int | None
    """1 = ask first. None: cannot be asked under the rules (listed for transparency)."""
    rank_without_voluntary: int | None
    """Where the same physician would rank if nobody's voluntary availability counted."""
    movement: int = 0
    """Positive = moved up because of voluntary availability (rank_without - rank)."""
    physician_id: EntityId
    display_name: str
    eligible: bool
    in_plan: bool
    """Part of the optimizer's recommended plan."""
    voluntary: VoluntaryMatch | None = None
    voluntary_preference_applied: bool = False
    offer: RankedOffer | None = None
    coverage_physician_minutes: float = 0.0
    """Deficit physician-minutes at the need hospitals this physician's offer removes."""
    coverage_share_of_best: float | None = None
    minutes_to_come_online: int | None = None
    hours_worked_trailing_7d: float | None = None
    remaining_weekly_hours: float | None = None
    cost: CostEstimate | None = None
    summary: str
    reasons: list[str] = Field(default_factory=list)


class NeedRanking(ApiModel):
    """Ranked physicians for one coverage need (one short hospital, or an intervention's
    need hospitals)."""

    hospital_ids: list[EntityId]
    hospital_names: list[str]
    shortage_start: AwareDatetime | None = None
    shortage_end: AwareDatetime | None = None
    entries: list[RankedCandidate]
    method: list[str] = Field(default_factory=list)


class VoluntarySummary(ApiModel):
    active_windows: int
    """Voluntary availability windows currently shared by off-shift physicians."""
    applied: bool
    """True when voluntary availability changed the recommended plan."""
    coverage_tolerance: float
    reference_physicians: list[str] = Field(default_factory=list)
    """Who the plan would contact without voluntary availability."""
    explanation: list[str] = Field(default_factory=list)


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
    voluntary: VoluntaryMatch | None = None
    """Voluntary availability this physician shared (None: none shared)."""


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
    voluntary: VoluntaryMatch | None = None
    cost: CostEstimate | None = None


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
    rankings: list[NeedRanking] = Field(default_factory=list)
    """Ranked physicians per short hospital (who to ask first, and why)."""
    voluntary: VoluntarySummary | None = None
    cost: PlanCost | None = None
