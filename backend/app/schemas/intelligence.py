"""NEUROGRID intelligence layer contracts (P1/P2 analyses on top of Phases 3-5).

Everything here is *derived* from the same replayed state, coverage models and workflow
records the dashboard already uses. Figures labelled ``projected`` or ``modeled`` are
forecasts, never observed facts. Scores are transparent sums of computed quantities, not
calibrated probabilities and not clinical risk scores.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any, Literal

from pydantic import AwareDatetime, Field

from app.schemas.common import ApiModel, EntityId, Severity

# ---------------------------------------------------------------- availability --


class AvailabilityClass(StrEnum):
    """NEUROGRID availability classes. Derived from the Phase 2 precedence decision."""

    OFF_SHIFT = "OFF_SHIFT"
    AVAILABLE = "AVAILABLE"
    BUSY_CALL = "BUSY_CALL"
    BUSY_VIDEO = "BUSY_VIDEO"
    PROBABLY_BUSY_EXTERNAL = "PROBABLY_BUSY_EXTERNAL"
    INTERRUPTIBLE_MEETING = "INTERRUPTIBLE_MEETING"
    UNAVAILABLE = "UNAVAILABLE"
    UNCERTAIN = "UNCERTAIN"
    UNKNOWN = "UNKNOWN"


class EvidenceConfidence(StrEnum):
    """Evidence labels. Not statistically calibrated probabilities."""

    CONFIRMED = "CONFIRMED"
    LIKELY = "LIKELY"
    UNCERTAIN = "UNCERTAIN"
    STALE = "STALE"


class PhysicianAvailabilityView(ApiModel):
    physician_id: EntityId
    display_name: str
    on_shift: bool | None
    availability_class: AvailabilityClass
    confidence: EvidenceConfidence
    decision_rule: str
    auto_routable: bool
    """Eligible for automatic routing under the brief's rules (on shift, not busy, not
    ringing, no hang-up in the last 2 minutes). Credentialing is per hospital."""
    coordinator_reachable: bool
    """A coordinator could reasonably contact them (e.g. an interruptible meeting)."""
    needs_confirmation: bool
    """Signals are stale or contradictory: confirm before relying on this physician."""
    routing_exclusions: list[str] = Field(default_factory=list)
    rationale: list[str] = Field(default_factory=list)
    signal_times: dict[str, AwareDatetime | None] = Field(default_factory=dict)
    evidence_event_ids: list[EntityId] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)
    open_consult_ids: list[EntityId] = Field(default_factory=list)
    unfinished_note_consult_ids: list[EntityId] = Field(default_factory=list)


class AvailabilityReport(ApiModel):
    as_of: AwareDatetime
    data_version: int
    physicians: list[PhysicianAvailabilityView]
    counts_by_class: dict[str, int]
    rules: list[str]


# ---------------------------------------------------------------- network / fragility --


class GraphNode(ApiModel):
    id: str
    kind: Literal["hospital", "physician"]
    entity_id: EntityId
    label: str
    status: str
    """hospital: short | fragile | resilient | no_requirement.
    physician: availability class."""
    risk: Literal["critical", "warning", "ok", "info"]
    attributes: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(ApiModel):
    id: str
    physician_id: EntityId
    hospital_id: EntityId
    credentialed: Literal[True] = True
    """Permanent credentialing edge. Operational usability is separate (``operational``)."""
    operational: Literal[
        "routable_now",
        "counted_busy",
        "counted_unverified",
        "joins_later",
        "off_shift",
        "unavailable",
        "outside_scope",
    ]
    critical_dependency: bool = False
    """Removing this physician creates or deepens a shortfall at this hospital."""


class HospitalImpact(ApiModel):
    hospital_id: EntityId
    hospital_name: str
    added_deficit_physician_minutes: float
    first_shortfall_before: AwareDatetime | None
    first_shortfall_after: AwareDatetime | None
    newly_uncovered: bool
    """No shortfall in the horizon before, one after."""


class PhysicianCriticality(ApiModel):
    physician_id: EntityId
    display_name: str
    on_shift: bool | None
    availability_class: AvailabilityClass
    shift_end: AwareDatetime | None
    credentialed_hospital_count: int
    relevant: bool
    """Counts toward coverage somewhere inside the horizon (on shift or joining)."""
    added_deficit_physician_minutes: float
    hospitals_affected: list[HospitalImpact]
    newly_uncovered_hospital_ids: list[EntityId]
    sole_coverage_hospital_ids: list[EntityId]
    """Hospitals where this physician is the only counted physician right now."""
    criticality_score: float
    criticality_factors: dict[str, float]
    rank: int
    explanation: str


class HospitalResilience(ApiModel):
    hospital_id: EntityId
    hospital_name: str
    timezone: str
    credentialed_total: int
    """Credentialing degree: all physicians credentialed here (any roster)."""
    required_now: int | None
    counted_now: int
    routable_now: int
    spare_now: int | None
    """counted_now - required_now: independent backups beyond the requirement."""
    min_spare_in_horizon: int | None
    shortfall_minutes: float
    fragile_minutes: float
    """Minutes with zero spare: requirement met exactly, a single loss creates a gap."""
    deficit_physician_minutes: float
    single_point_dependencies: list[EntityId]
    """Physicians whose individual removal creates or deepens a shortfall here."""
    status: Literal["short", "fragile", "resilient", "no_requirement"]
    explanation: str


class AllocationCheck(ApiModel):
    """Pool (non-exclusive) coverage vs exclusive allocation at one instant."""

    at: AwareDatetime
    label: str
    required_total: int
    pool_covered: int
    """Σ_h min(required_h, counted_h): each physician may count at every credentialed site."""
    exclusive_covered: int
    """Maximum bipartite matching: each physician fills at most one required position."""
    exclusive_shortfall: int
    unmatched_hospital_ids: list[EntityId]
    assignment: dict[str, list[str]]
    """hospital_id -> physicians matched to its required positions."""


class MultiFailureResult(ApiModel):
    scenario: str
    label: str
    removed_physician_ids: list[EntityId]
    added_deficit_physician_minutes: float
    hospitals_newly_short: list[EntityId]
    hospitals_affected: list[HospitalImpact]
    explanation: str


class FragilityReport(ApiModel):
    as_of: AwareDatetime
    data_version: int
    horizon_minutes: int
    baseline_deficit_physician_minutes: float
    nodes: list[GraphNode]
    edges: list[GraphEdge]
    physicians: list[PhysicianCriticality]
    hospitals: list[HospitalResilience]
    allocation: list[AllocationCheck]
    multi_failure: list[MultiFailureResult]
    graph_metrics: dict[str, Any]
    score_weights: dict[str, float]
    method: list[str]
    assumptions: list[str]


# ---------------------------------------------------------------- coverage genome --


class RootCause(StrEnum):
    TOTAL_CAPACITY_SHORTAGE = "TOTAL_CAPACITY_SHORTAGE"
    CREDENTIALING_BOTTLENECK = "CREDENTIALING_BOTTLENECK"
    SHIFT_COLLISION = "SHIFT_COLLISION"
    ROUTING_ELIGIBILITY_FAILURE = "ROUTING_ELIGIBILITY_FAILURE"
    WORKLOAD_CONCENTRATION = "WORKLOAD_CONCENTRATION"
    AVAILABILITY_UNCERTAINTY = "AVAILABILITY_UNCERTAINTY"
    DOCUMENTATION_HANDOFF_RISK = "DOCUMENTATION_HANDOFF_RISK"
    MULTI_FACTOR = "MULTI_FACTOR"


class GenomeFactor(ApiModel):
    cause: RootCause
    weight: float
    """Share of the explanation carried by this factor (computed, sums to 1 per diagnosis)."""
    evidence: list[str]


class GenomeDiagnosis(ApiModel):
    diagnosis_id: str
    hospital_id: EntityId
    hospital_name: str
    problem: Literal["coverage_gap_now", "coverage_gap_projected", "unroutable_consults"]
    problem_at: AwareDatetime
    severity: Severity
    primary_cause: RootCause
    factors: list[GenomeFactor]
    counts: dict[str, int]
    excluded_by_reason: dict[str, int]
    limiting_constraint: str
    recommended_intervention: str
    explanation: str
    related_alert_ids: list[str] = Field(default_factory=list)


class StrategicSuggestion(ApiModel):
    kind: Literal[
        "credentialing_expansion", "shift_overlap", "backup_placement", "dependency_reduction"
    ]
    title: str
    detail: str
    basis: list[str]
    label: Literal["planning suggestion — not an authorization"] = (
        "planning suggestion — not an authorization"
    )


class GenomeReport(ApiModel):
    as_of: AwareDatetime
    data_version: int
    horizon_minutes: int
    diagnoses: list[GenomeDiagnosis]
    strategic: list[StrategicSuggestion]
    method: list[str]


# ---------------------------------------------------------------- scarcity --


class ScarcityHospital(ApiModel):
    hospital_id: EntityId
    hospital_name: str
    first_shortfall_at: AwareDatetime | None
    deficit_physician_minutes: float
    urgency: Literal["now", "within_90", "planning_window"]
    alternative_candidate_ids: list[EntityId]
    sole_candidate: bool
    reduction_if_assigned: float
    """Deficit physician-minutes this candidate's best valid offer removes here."""


class ScarcityEntry(ApiModel):
    physician_id: EntityId
    display_name: str
    eligible: bool
    failed_rules: list[str]
    hospitals: list[ScarcityHospital]
    dependent_hospital_count: int
    sole_candidate_hospital_count: int
    minutes_to_come_online: int | None
    earliest_valid_start: AwareDatetime | None
    max_offer_minutes: int | None
    scarcity_score: float
    recommendation: Literal["allocate", "preserve", "allocate_if_needed", "not_eligible"]
    opportunity_cost: str
    explanation: str


class ScarcityReport(ApiModel):
    as_of: AwareDatetime
    data_version: int
    planning_horizon_minutes: int
    gap_hospital_ids: list[EntityId]
    entries: list[ScarcityEntry]
    uncovered_hospital_ids: list[EntityId]
    """Gap hospitals with no eligible off-shift candidate at all."""
    no_feasible_candidate: bool
    escalation_recommended: bool
    policy: list[str]


# ---------------------------------------------------------------- last safe moment --


class LeadTime(ApiModel):
    approval_minutes: int
    response_minutes_expected: int
    response_minutes_conservative: int
    online_minutes: int
    expected_total_minutes: int
    conservative_total_minutes: int
    online_time_assumed: bool = False


class RescueTiming(ApiModel):
    physician_id: EntityId
    display_name: str
    lead: LeadTime
    earliest_valid_start: AwareDatetime | None
    """Earliest offer start the hard rules allow (rest, overlap, weekly hours...)."""
    activation_expected_at: AwareDatetime | None
    """If the workflow starts now: when coverage is expected to begin."""
    latest_initiation_expected: AwareDatetime | None
    latest_initiation_conservative: AwareDatetime | None
    covers_shortfall_start: bool
    """Coverage can begin by the shortfall start (with conservative lead time)."""
    eligible_at_start: bool
    sendable_now: bool
    """Send-time rules (open offers, weekly limit) pass now."""
    eligibility_crossing: str | None = None
    """Ineligible now but eligible later (e.g. rest completes before the shortfall)."""
    blocking: list[str] = Field(default_factory=list)


class LastSafeMoment(ApiModel):
    shortfall_id: str
    hospital_id: EntityId
    hospital_name: str
    timezone: str
    shortfall_at: AwareDatetime
    shortfall_ends_at: AwareDatetime | None
    minutes_until_shortfall: float
    deficit_physician_minutes: float
    worst_deficit: int
    phase: Literal["green", "amber", "red", "missed", "no_candidate"]
    latest_initiation_at: AwareDatetime | None
    """Best candidate, conservative lead time. None when no candidate can cover."""
    remaining_minutes: float | None
    best_physician_id: EntityId | None
    candidates: list[RescueTiming]
    mitigation: list[str]
    uncertainty: list[str]
    explanation: str


class LastSafeMomentReport(ApiModel):
    as_of: AwareDatetime
    data_version: int
    planning_horizon_minutes: int
    items: list[LastSafeMoment]
    earliest_deadline_at: AwareDatetime | None
    assumptions: list[str]


# ---------------------------------------------------------------- coverage debt --


class DebtSample(ApiModel):
    at: AwareDatetime
    required: int | None
    counted: int
    deficit: int | None
    kind: Literal["historical", "projected"]


class HospitalDebt(ApiModel):
    hospital_id: EntityId
    hospital_name: str
    historical_debt_physician_minutes: float
    projected_debt_physician_minutes: float
    projected_debt_if_uncertain_excluded: float
    fragile_minutes_projected: float
    samples: list[DebtSample]


class CoverageDebtReport(ApiModel):
    as_of: AwareDatetime
    data_version: int
    lookback_minutes: int
    horizon_minutes: int
    step_minutes: int
    network_historical: float
    network_projected: float
    network_projected_if_uncertain_excluded: float
    network_fragile_minutes: float
    hospitals: list[HospitalDebt]
    method: list[str]


# ---------------------------------------------------------------- handoff --


class HandoffConsult(ApiModel):
    consult_id: EntityId
    hospital_id: EntityId | None
    stage: str
    consult_type: str | None
    seconds_in_stage: int
    unfinished_note: bool


class HandoffCoverageChange(ApiModel):
    hospital_id: EntityId
    hospital_name: str
    counted_before: int
    counted_after: int
    required_after: int | None
    deficit_after: int | None


class HandoffTransition(ApiModel):
    at: AwareDatetime
    kind: Literal["departing", "arriving"]
    physician_id: EntityId
    display_name: str
    certainty: Literal["scheduled", "assumed", "rescue_shift"]
    open_consults: list[HandoffConsult]
    unfinished_notes: int
    coverage_changes: list[HandoffCoverageChange]
    risk: Literal["critical", "warning", "ok"]
    notes: list[str]


class HandoffDeadline(ApiModel):
    consult_id: EntityId
    hospital_id: EntityId | None
    rule_code: str
    stage: str
    severity_now: Severity
    critical_at: AwareDatetime | None
    minutes_to_critical: float | None


class HandoffReport(ApiModel):
    as_of: AwareDatetime
    data_version: int
    horizon_minutes: int
    transitions: list[HandoffTransition]
    pending_routing_failures: list[dict[str, Any]]
    pending_rescues: list[dict[str, Any]]
    deadlines: list[HandoffDeadline]
    notes: list[str]


# ---------------------------------------------------------------- problems (fingerprint) --


class ProblemGroup(ApiModel):
    fingerprint: str
    """Deterministic hash of (kind, scope). Stable while the underlying issue persists."""
    kind: Literal[
        "hospital_staffing",
        "consult_delay",
        "physician_workload",
        "physician_signal",
        "demand_surge",
    ]
    tier: int
    """Lexicographic priority tier (1 = most urgent; see RULES.md §Priority)."""
    priority: int
    severity: Severity
    title: str
    summary: str
    hospital_id: EntityId | None = None
    physician_id: EntityId | None = None
    member_alert_ids: list[str]
    critical_alert_ids: list[str]
    root_cause: RootCause | None = None
    recommended_action: str
    factors: dict[str, float]
    explanation: str


class ProblemReport(ApiModel):
    as_of: AwareDatetime
    data_version: int
    groups: list[ProblemGroup]
    alerts_total: int
    tier_policy: list[str]


# ---------------------------------------------------------------- time machine --


class TimeMachineHospital(ApiModel):
    hospital_id: EntityId
    required: int | None
    confirmed: int
    uncertain: int
    deficit: int | None
    spike: bool | None


class TimeMachineFrame(ApiModel):
    at: AwareDatetime
    offset_minutes: float
    kind: Literal["now", "step", "boundary", "horizon_end"]
    observed: bool
    """Only the ``now`` frame reflects observed state; every other frame is projected."""
    network_required: int
    network_deficit: int
    hospitals_short: int
    hospitals: list[TimeMachineHospital]
    labels: list[str] = Field(default_factory=list)


class ShiftLaneSegment(ApiModel):
    start: AwareDatetime
    end: AwareDatetime | None
    kind: Literal["scheduled", "assumed", "rescue_pending", "rescue_active"]
    label: str


class ShiftLane(ApiModel):
    physician_id: EntityId
    display_name: str
    availability_class: AvailabilityClass
    credentialed_hospital_ids: list[EntityId]
    segments: list[ShiftLaneSegment]


class DemandBand(ApiModel):
    hospital_id: EntityId
    at: AwareDatetime
    expected_arrivals: float
    """Baseline-mean arrivals in the next step (Poisson rate)."""
    p10_trailing_hour: float
    p50_trailing_hour: float
    p90_trailing_hour: float
    p90_threshold: float | None
    share_runs_above_threshold: float
    """Fraction of seeded Poisson runs whose trailing-60-min arrivals exceed the hourly p90.
    A sensitivity indicator under a stated assumption, not a calibrated probability."""


class TimeMachineReport(ApiModel):
    as_of: AwareDatetime
    data_version: int
    horizon_minutes: int
    step_minutes: int
    frames: list[TimeMachineFrame]
    lanes: list[ShiftLane]
    demand: list[DemandBand]
    stochastic: dict[str, Any]
    freshness: dict[str, Any]
    hospitals: list[dict[str, str]]
    notes: list[str]


# ---------------------------------------------------------------- rescue simulator --


class OptionOutcome(ApiModel):
    network_deficit_before: float
    network_deficit_after: float
    target_deficit_before: float
    target_deficit_after: float
    resolved_hospital_ids: list[EntityId]
    residual_hospital_ids: list[EntityId]
    new_shortfall_hospital_ids: list[EntityId]
    single_points_before: int
    single_points_after: int
    activation_at: AwareDatetime | None
    activation_delay_minutes: float | None
    per_hospital: list[dict[str, Any]]


class RescueOption(ApiModel):
    option_id: str
    kind: Literal[
        "do_nothing",
        "escalation",
        "reassignment",
        "split_shift",
        "shift_extension",
        "combination",
    ]
    label: str
    feasible: bool
    simulation_only: bool
    """Needs an integration or authority the prototype does not have (e.g. extending a
    scheduled shift). Never offered as a submittable proposal."""
    requires_approval: bool
    physician_ids: list[EntityId] = Field(default_factory=list)
    hospital_ids: list[EntityId] = Field(default_factory=list)
    start_at: AwareDatetime | None = None
    end_at: AwareDatetime | None = None
    blocking_reasons: list[str] = Field(default_factory=list)
    outcome: OptionOutcome | None = None
    workload: dict[str, Any] | None = None
    lexicographic_key: list[float] = Field(default_factory=list)
    rank: int | None = None
    recommended: bool = False
    why: list[str] = Field(default_factory=list)
    uncertainty: list[str] = Field(default_factory=list)
    proposal: dict[str, Any] | None = None
    """Body for POST /api/interventions when the option can be proposed."""


class RescueSimulation(ApiModel):
    as_of: AwareDatetime
    data_version: int
    horizon_minutes: int
    target_hospital_ids: list[EntityId]
    target_label: str
    options: list[RescueOption]
    objective: list[str]
    label: str = "Projected — nothing has been changed. Simulated on an isolated copy."


# ---------------------------------------------------------------- load guardian --


class LoadGuardianReport(ApiModel):
    as_of: AwareDatetime
    data_version: int
    available: bool
    physician_id: EntityId | None = None
    display_name: str | None = None
    unrestricted: dict[str, Any] | None = None
    protected: dict[str, Any] | None = None
    workload_limit: int | None = None
    scope_hospital_ids: list[EntityId] = Field(default_factory=list)
    excluded_hospital_ids: list[EntityId] = Field(default_factory=list)
    forgone_coverage: list[dict[str, Any]] = Field(default_factory=list)
    """Coverage the joiner could add at excluded hospitals if unrestricted (computed):
    shows whether protection leaves a shortfall elsewhere."""
    release_conditions: list[str] = Field(default_factory=list)
    conclusion: str
    label: str = (
        "Proposed policy — simulated in NEUROGRID; would require Sevaro routing integration "
        "and authorization."
    )


# ---------------------------------------------------------------- chaos lab --


class ChaosScenarioInfo(ApiModel):
    scenario_id: str
    title: str
    category: Literal["state", "workflow", "ingestion"]
    description: str
    injects: str


class ChaosAssertion(ApiModel):
    name: str
    passed: bool
    expected: str
    actual: str


class ChaosDelta(ApiModel):
    metric: str
    before: Any
    after: Any


class ChaosResult(ApiModel):
    run_id: str
    scenario_id: str
    title: str
    branch: str
    """Ephemeral branch database. Deleted after the run; the baseline is never written."""
    started_at: AwareDatetime
    as_of: AwareDatetime
    target: dict[str, Any]
    injected: list[str]
    deltas: list[ChaosDelta]
    alerts_new: list[str]
    alerts_resolved: list[str]
    assertions: list[ChaosAssertion]
    passed: bool
    baseline_unchanged: bool
    duration_ms: float
    notes: list[str]


# ---------------------------------------------------------------- import preview --


class ImportPreview(ApiModel):
    filename: str
    valid: bool
    received: int
    accepted: int
    duplicates: int
    conflicting_duplicates: int
    rejected: int
    unknown_event_types: dict[str, int]
    outcomes: list[dict[str, Any]]
    errors: list[dict[str, Any]]
    clock_before: AwareDatetime
    clock_after: AwareDatetime
    deltas: list[ChaosDelta]
    alerts_new: list[str]
    alerts_resolved: list[str]
    note: str


# ---------------------------------------------------------------- contract verification --


class ContractVerification(ApiModel):
    intervention_id: str
    contract_phase: str
    verdict: Literal[
        "not_applicable",
        "pending",
        "resolved",
        "partially_resolved",
        "failed",
    ]
    checked_at: AwareDatetime
    data_version: int
    success_condition: str
    target_hospital_ids: list[EntityId]
    interval_start: AwareDatetime | None
    interval_end: AwareDatetime | None
    target_deficit_physician_minutes: float | None
    baseline_deficit_physician_minutes: float | None
    new_critical_elsewhere: list[EntityId]
    findings: list[str]
    next_steps: list[str]


# ---------------------------------------------------------------- evaluation --


class EvaluationRow(ApiModel):
    metric: str
    monitoring_only: Any
    reactive: Any
    neurogrid: Any
    note: str


class EvaluationReport(ApiModel):
    as_of: AwareDatetime
    data_version: int
    rows: list[EvaluationRow]
    timings_ms: dict[str, float]
    notes: list[str]
