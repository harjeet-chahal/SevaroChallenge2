"""Phase 5 interventions: proposed by coordinators, decided by clinical leads, acted on.

Three types share one persisted record and one validated state machine
(``app/engines/interventions/machine.py``):

- ``reassign_consult``: the coordinator moves a consult (coordinator authority, no
  clinical approval). Applying it records a simulated Synapse assignment event.
- ``escalation``: the coordinator hands a problem to the clinical lead, who authorizes
  (approves) or rejects it and later marks it resolved.
- ``split_shift``: a staffing request for one coverage need. It needs clinical-lead
  approval before any offer is sent; offers then follow their own lifecycle.

Everything here is computed by the backend. The frontend renders it and calls the
transition endpoints; ``allowed_actions`` tells it which transitions the caller's role may
perform right now, so no button can claim an action the server would refuse.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import AwareDatetime, Field

from app.schemas.common import ActorRef, ApiModel, EntityId, Severity
from app.schemas.dispatch import Exclusion, RuleCheck
from app.schemas.offer import ShiftOffer
from app.schemas.staffing import (
    CandidateEligibility,
    CostComparison,
    CostEstimate,
    HospitalEffect,
    NeedRanking,
    PlanCost,
    TrapAnalysis,
    VoluntaryMatch,
)


class InterventionType(StrEnum):
    REASSIGN_CONSULT = "reassign_consult"
    ESCALATION = "escalation"
    SPLIT_SHIFT = "split_shift"


class InterventionStatus(StrEnum):
    PROPOSED = "proposed"
    """Reassignment drafted by the coordinator, not yet applied."""
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    """Split shift: approved, offers not sent yet. Escalation: authorized by the clinical lead."""
    REJECTED = "rejected"
    OFFER_SENT = "offer_sent"
    ACCEPTED = "accepted"
    """A physician accepted; preparing to come online (not active capacity yet)."""
    DECLINED = "declined"
    EXPIRED = "expired"
    ACTIVATED = "activated"
    """The physician is online and counted as active, routable capacity."""
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    NO_LONGER_REQUIRED = "no_longer_required"


TERMINAL_STATUSES: frozenset[InterventionStatus] = frozenset(
    {
        InterventionStatus.REJECTED,
        InterventionStatus.DECLINED,
        InterventionStatus.EXPIRED,
        InterventionStatus.COMPLETED,
        InterventionStatus.CANCELLED,
        InterventionStatus.NO_LONGER_REQUIRED,
    }
)


InterventionAction = Literal[
    "approve",
    "reject",
    "send_offers",
    "apply",
    "resolve",
    "cancel",
]


class ProblemSnapshot(ApiModel):
    """What was wrong when the intervention was proposed (copied from the alert/forecast)."""

    alert_id: str | None = None
    rule_code: str | None = None
    title: str
    summary: str
    severity: Severity | None = None
    priority: int | None = None
    hospital_ids: list[EntityId] = Field(default_factory=list)
    hospital_names: list[str] = Field(default_factory=list)
    hospital_timezone: str | None = None
    consult_id: EntityId | None = None
    consult_type: str | None = None
    physician_id: EntityId | None = None
    physician_name: str | None = None
    elapsed_seconds: int | None = None
    warning_after_seconds: int | None = None
    critical_after_seconds: int | None = None
    impact_at: AwareDatetime | None = None
    captured_at: AwareDatetime
    data_version: int


class AlternativeAction(ApiModel):
    type: InterventionType | Literal["monitor"]
    label: str
    available: bool
    reason: str


class InterventionRecommendation(ApiModel):
    """Why this intervention, how it was chosen and what it cannot promise."""

    summary: str
    why: list[str] = Field(default_factory=list)
    algorithm: str
    """Which engine/policy produced the recommendation (e.g. OR-Tools CP-SAT staffing)."""
    policy_version: str
    solver_status: str | None = None
    alternatives: list[AlternativeAction] = Field(default_factory=list)
    uncertainty: list[str] = Field(default_factory=list)
    restrictions: list[str] = Field(default_factory=list)
    approver_role: Literal["clinical_lead", "coordinator"]
    ranking: NeedRanking | None = None
    """Split shift: physicians ranked for this need at proposal time (who to ask first)."""
    cost: PlanCost | None = None
    """Split shift: estimated cost of the primary offer and of the alternatives (simulated)."""


class OfferPlanItem(ApiModel):
    """One physician the split shift would be offered to, with the exact offer evaluated."""

    physician_id: EntityId
    display_name: str
    role: Literal["primary", "backup"]
    hospital_ids: list[EntityId]
    hospital_names: list[str]
    start_at: AwareDatetime
    end_at: AwareDatetime
    duration_minutes: int
    minutes_to_online: int
    online_time_assumed: bool = False
    expected_online_at: AwareDatetime
    coverage_minutes: int
    """Useful minutes after the time to come online (what the offer is worth)."""
    routing_scope_hospital_ids: list[EntityId]
    excluded_credentialed_hospital_ids: list[EntityId] = Field(default_factory=list)
    seeded_consult_count: int
    protection_rationale: list[str] = Field(default_factory=list)
    eligible: bool
    checks: list[RuleCheck]
    """Every split-shift rule evaluated for this exact offer (start, length, hospitals)."""
    projected_effects: list[HospitalEffect] = Field(default_factory=list)
    """Deficit before/after if *this* offer alone is accepted (modeled, not confirmed)."""
    voluntary: VoluntaryMatch | None = None
    """The physician's voluntary availability for this offer, if they shared any."""
    cost: CostEstimate | None = None
    """Estimated cost of this offer if accepted (simulated)."""


class HospitalImpact(ApiModel):
    hospital_id: EntityId
    hospital_name: str
    deficit_before: float
    deficit_after: float
    """Physician-minutes over ``horizon_minutes``."""
    shortfall_now_before: int
    shortfall_now_after: int
    first_shortfall_before: AwareDatetime | None = None
    first_shortfall_after: AwareDatetime | None = None


class CoverageImpact(ApiModel):
    label: str
    """'Projected if accepted — not confirmed coverage', 'Measured at activation', ..."""
    horizon_minutes: int
    hospitals: list[HospitalImpact]
    total_before: float
    total_after: float
    computed_at: AwareDatetime
    data_version: int
    notes: list[str] = Field(default_factory=list)


class ReassignmentPlan(ApiModel):
    consult_id: EntityId
    hospital_id: EntityId | None
    hospital_name: str | None
    consult_type: str | None
    stage: str
    current_physician_id: EntityId | None
    current_physician_name: str | None
    target_physician_id: EntityId
    target_physician_name: str
    eligible: bool
    checks: list[RuleCheck]
    """The target's routing checks (brief rules 1-2) at proposal time."""
    excluded: list[Exclusion] = Field(default_factory=list)
    """Every other physician considered for this consult, and why not."""
    alternatives: list[EntityId] = Field(default_factory=list)
    workload_note: str | None = None


class EscalationDetail(ApiModel):
    reason: str
    requested_decision: str
    """What the clinical lead is asked to authorize."""
    blocking_facts: list[str] = Field(default_factory=list)
    """Why the normal fixes are not available (e.g. nobody eligible, no split-shift candidate)."""


class ApprovalView(ApiModel):
    id: int
    decision: Literal["approve", "reject"]
    decided_by: ActorRef
    decided_at: AwareDatetime
    recorded_at: AwareDatetime
    note: str | None = None
    data_version: int
    revalidation: list[str] = Field(default_factory=list)
    """What was re-checked at decision time, in plain sentences."""


class Intervention(ApiModel):
    id: EntityId
    type: InterventionType
    status: InterventionStatus
    status_reason: str | None = None
    title: str
    rationale: str | None = None
    """The coordinator's free-text note. Never included in physician-facing offers."""
    dataset_import_id: str | None = None
    problem: ProblemSnapshot
    recommendation: InterventionRecommendation
    candidates: list[CandidateEligibility] = Field(default_factory=list)
    """Split shift: every off-shift physician evaluated, with each rule passed or failed."""
    offer_plan: list[OfferPlanItem] = Field(default_factory=list)
    required_physicians: int = 1
    reassignment: ReassignmentPlan | None = None
    escalation: EscalationDetail | None = None
    impact: CoverageImpact | None = None
    trap: TrapAnalysis | None = None
    proposed_by: ActorRef
    proposed_at: AwareDatetime
    updated_at: AwareDatetime
    created_data_version: int
    version: int
    """Optimistic-concurrency counter; increments on every transition."""
    approval: ApprovalView | None = None
    offers: list[ShiftOffer] = Field(default_factory=list)
    allowed_actions: list[InterventionAction] = Field(default_factory=list)
    is_terminal: bool
    confirmed_cost: CostEstimate | None = None
    """Cost of split shifts actually completed under this intervention (None until then)."""
    confirmed_savings: list[CostComparison] = Field(default_factory=list)
    """Confirmed cost against each alternative's projected cost (only once completed)."""


class InterventionPage(ApiModel):
    total: int
    items: list[Intervention]
    counts_by_status: dict[str, int]


class InterventionCreate(ApiModel):
    """Body a coordinator submits. The server re-derives and re-validates everything."""

    type: InterventionType
    alert_id: str | None = Field(default=None, max_length=200)
    rationale: str | None = Field(default=None, max_length=2000)
    expected_data_version: int | None = None
    """The data version the coordinator was looking at; a newer one triggers revalidation."""
    # split_shift
    physician_ids: list[EntityId] = Field(default_factory=list, max_length=4)
    """Primary first, then optional backups. Empty = the optimizer's top recommendation."""
    hospital_ids: list[EntityId] = Field(default_factory=list)
    """The coverage need. Empty = the hospitals of the recommendation or alert."""
    start_at: AwareDatetime | None = None
    duration_minutes: int | None = Field(default=None, gt=0, le=24 * 60)
    # reassign_consult / escalation
    consult_id: EntityId | None = None
    target_physician_id: EntityId | None = None
    hospital_id: EntityId | None = None
    reason: str | None = Field(default=None, max_length=2000)


class InterventionPreview(ApiModel):
    """Dry run of a proposal at the current data version: nothing is stored."""

    valid: bool
    blocking_reasons: list[str]
    warnings: list[str]
    data_version: int
    intervention: Intervention | None


class DecisionRequest(ApiModel):
    decision: Literal["approve", "reject"]
    note: str | None = Field(default=None, max_length=2000)
    expected_version: int | None = None


class CancelRequest(ApiModel):
    reason: str | None = Field(default=None, max_length=1000)


class ResolveRequest(ApiModel):
    note: str | None = Field(default=None, max_length=2000)


class InterventionImpact(ApiModel):
    """Before/after view of one intervention (projected at proposal, live now)."""

    intervention_id: EntityId
    status: InterventionStatus
    proposed: CoverageImpact | None
    at_activation: CoverageImpact | None
    current: CoverageImpact | None
    trap: TrapAnalysis | None
    routing: dict[str, Any] | None = None
    """Live routing view of an activated split-shift physician (scope, counts, proposals)."""
    notes: list[str] = Field(default_factory=list)


class WorkflowSummary(ApiModel):
    workflow_version: int
    data_version: int
    simulation_time: AwareDatetime | None
    pending_approvals: int
    offers_awaiting_response: int
    accepted_preparing: int
    active_split_shifts: int
    open_interventions: int
