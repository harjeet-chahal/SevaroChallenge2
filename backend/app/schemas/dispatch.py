"""Consultation dispatch recommendations (Phase 4, Optimizer A). Proposals only.

Nothing here assigns a consult. Every recommendation is a proposal for a human to act on,
and the existing assignment of a consult is never changed silently: a consult that already
has a working assignee is not part of the problem at all.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, Field

from app.schemas.common import ApiModel, EntityId

SolverStatus = Literal[
    "OPTIMAL", "FEASIBLE", "INFEASIBLE", "NOT_SOLVED", "MODEL_INVALID", "UNKNOWN", "FALLBACK"
]


class SolverRun(ApiModel):
    """What actually ran. ``fallback_used`` is true only when OR-Tools was unavailable."""

    optimizer: str
    solver: str
    status: SolverStatus
    proven_optimal: bool
    fallback_used: bool = False
    wall_time_ms: float
    objective: int | None = None
    best_bound: int | None = None
    time_limit_seconds: float | None = None
    stages: list[dict] = Field(default_factory=list)
    """Lexicographic stages (CP-SAT): name, status, objective, wall time."""
    notes: list[str] = Field(default_factory=list)


class RuleCheck(ApiModel):
    """One rule evaluated for one physician. ``passed=None`` is never used: missing data fails."""

    code: str
    label: str
    passed: bool
    value: str | None = None
    """The observed value the rule was evaluated against (as text, with units)."""
    threshold: str | None = None
    message: str
    source: Literal["brief", "assumption", "implementation_choice"]
    missing_data: bool = False


class DispatchPhysician(ApiModel):
    """Routing view of one on-shift physician at the decision time.

    ``counts_for_coverage`` (Phase 3 coverage engine), ``eligible_for_dispatch`` (brief
    routing rules 1-2, any hospital) and ``effective_routing_capacity`` (new synchronous
    consults this round) are deliberately separate: a physician on a video call still
    counts toward coverage but cannot take a new call right now.
    """

    physician_id: EntityId
    display_name: str
    availability: str
    activity: str
    on_shift: bool | None
    counts_for_coverage: bool
    coverage_hospital_ids: list[EntityId]
    eligible_for_dispatch: bool
    effective_routing_capacity: int
    routing_scope_hospital_ids: list[EntityId]
    """Credentialed hospitals, narrowed by any routing-scope restriction."""
    consults_this_shift: int
    open_consults: int
    open_async_consults: int
    """Open consults in asynchronous stages (imaging, notes). They do not use sync capacity."""
    low_volume: bool | None
    """Brief rule 3. None when the day/night role is unknown (day threshold used, flagged)."""
    low_volume_threshold: int
    minutes_since_last_call: float | None
    minutes_to_shift_end: int | None
    checks: list[RuleCheck]
    uncertainty: list[str] = Field(default_factory=list)


class CostComponent(ApiModel):
    name: str
    value: int
    detail: str


class WorkloadChange(ApiModel):
    consults_this_shift_before: int
    consults_this_shift_after: int
    open_consults_before: int
    open_consults_after: int


class Exclusion(ApiModel):
    physician_id: EntityId
    display_name: str
    reasons: list[str]


class DispatchRecommendation(ApiModel):
    """A proposed routing decision. ``executed`` is always false in Phase 4."""

    consult_id: EntityId
    hospital_id: EntityId | None
    hospital_name: str | None
    consult_type: str | None
    consult_category: str | None
    stage: str
    kind: Literal["assign", "reassign", "confirm_ringing"]
    physician_id: EntityId
    physician_name: str
    current_physician_id: EntityId | None = None
    priority: int
    """1 = most urgent, in dispatch order."""
    urgency_tier: int
    urgency_label: str
    waiting_minutes: float | None
    eligibility_evidence: list[str]
    cost_breakdown: list[CostComponent]
    edge_cost: int
    workload: WorkloadChange
    alternatives: list[EntityId]
    """Other eligible physicians for this consult, best first by edge cost."""
    excluded: list[Exclusion]
    uncertainty: list[str] = Field(default_factory=list)
    explanation: list[str]
    executed: Literal[False] = False


class UnassignedConsult(ApiModel):
    consult_id: EntityId
    hospital_id: EntityId | None
    hospital_name: str | None
    consult_type: str | None
    stage: str
    urgency_tier: int
    urgency_label: str
    waiting_minutes: float | None
    reason_code: Literal[
        "no_credentialed_on_shift",
        "no_eligible_physician",
        "capacity_used_by_higher_priority",
        "missing_hospital",
    ]
    explanation: list[str]
    excluded: list[Exclusion]
    competing_consult_ids: list[EntityId] = Field(default_factory=list)


class SkippedConsult(ApiModel):
    """Open consults deliberately left out of the dispatch problem, with the reason."""

    consult_id: EntityId
    stage: str
    assigned_physician_id: EntityId | None
    reason: str


class DispatchPolicyUsed(ApiModel):
    rules: list[str]
    assumptions: list[str]
    implementation_choices: list[str]
    weights: dict[str, int]
    urgency_tiers: list[str]


class DispatchPlan(ApiModel):
    """One dispatch plan (optimized or baseline) on the same snapshot."""

    method: Literal["min_cost_flow", "least_loaded_baseline", "fallback_greedy"]
    recommendations: list[DispatchRecommendation]
    unassigned: list[UnassignedConsult]
    objective_cost: int
    """Evaluated with the same cost function for every method, so plans are comparable."""


class DispatchResult(ApiModel):
    as_of: AwareDatetime
    data_version: int
    policy_version: str
    label: str = "Proposed — not executed. A coordinator decides."
    solver: SolverRun
    plan: DispatchPlan
    physicians: list[DispatchPhysician]
    skipped: list[SkippedConsult]
    policy: DispatchPolicyUsed
    explanations: list[str]
