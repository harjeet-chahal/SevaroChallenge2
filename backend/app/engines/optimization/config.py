"""Policy for the Phase 4 optimizers: brief rules, assumptions and implementation choices.

Every value is tagged in its docstring/comment as one of:
- BRIEF: copied from the challenge brief (routing rules 1-5, split-shift eligibility,
  notification limits),
- ASSUMPTION: the brief is silent or ambiguous; a reasonable reading, configurable,
- CHOICE: an implementation choice (weights, tie-breaks, solver limits).

Override any value with a JSON file (OPTIMIZATION_POLICY_FILE) without code changes.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.schemas.consultation import ConsultStage as S


class RoutingPolicy(BaseModel):
    call_cooldown_seconds: int = 120
    """BRIEF rule 2: remove anyone who ended a call less than 2 minutes ago."""
    exclude_ringing_for_other_call: bool = True
    """BRIEF rule 2: remove anyone whose phone is already ringing for another call."""
    low_volume_day_max: int = 6
    """BRIEF rule 3: low volume = 6 or fewer consults this shift on days ..."""
    low_volume_night_max: int = 4
    """... and 4 or fewer on nights."""
    night_role_labels: list[str] = Field(default_factory=lambda: ["night"])
    day_role_labels: list[str] = Field(default_factory=lambda: ["day"])
    """ASSUMPTION: day/night is read from the roster role. Without a day/night role (none on
    the on-shift roster; "Float"), it is inferred from the shift start in the network's main
    time zone (the zone most hospitals use): a start from ``night_shift_from_hour`` until
    ``night_shift_until_hour`` is a night shift. No start known: day threshold, flagged."""
    night_shift_from_hour: int = Field(default=17, ge=0, le=23)
    night_shift_until_hour: int = Field(default=5, ge=0, le=23)
    routable_unassigned_stages: list[S] = Field(default_factory=lambda: [S.TRIAGED])
    """ASSUMPTION: routing starts after triage (the brief's first standard is "Triaged, not yet
    assigned"). Received-but-untriaged consults are listed as skipped, with the reason."""
    sync_capacity: int = 1
    """CHOICE: new consults start with a synchronous call/video, so a physician takes at most
    one new consult per dispatch round. Async open consults (notes, imaging) never consume it."""
    reassign_unavailable_assignee: bool = True
    """ASSUMPTION: recommend (never execute) moving a consult whose assigned physician is
    unavailable or off shift. The brief lets the coordinator reassign consults."""
    reassignable_stages: list[S] = Field(
        default_factory=lambda: [
            S.ASSIGNED,
            S.PROVIDER_CONTACTED,
            S.IMAGING_PENDING,
            S.IMAGING_REVIEW,
        ]
    )
    """ASSUMPTION: notes stay with their author, so Note Pending/Documentation are not moved."""


class DispatchWeights(BaseModel):
    """CHOICE: bounded edge-cost weights (each component is capped; total <= max_edge_cost)."""

    per_consult_this_shift: int = 20
    consult_load_cap: int = 300
    per_open_consult: int = 15
    open_load_cap: int = 150
    not_low_volume: int = 200
    """Implements BRIEF rule 3 (low-volume physicians get priority) as a cost."""
    recency_window_minutes: int = 50
    """BRIEF rule 4 tie-break (least recently answered) as cost = max(0, window - idle min)."""
    shift_ending_minutes: int = 60
    per_minute_near_shift_end: int = 2
    unknown_shift_end: int = 30
    unverified_availability: int = 100
    inferred_agent: int = 30
    reassignment_disruption: int = 150
    per_additional_sync_consult: int = 100
    """Convex fairness cost when sync_capacity > 1: the k-th new consult for one physician in
    the same round costs k × this (spreads simultaneous work)."""
    wait_cap_minutes: int = 240


class TrapPolicy(BaseModel):
    """CHOICE (the brief requires *a* justified approach): protect a physician who joins
    mid-shift by (1) restricting their routing scope to the hospitals whose gap they fill,
    subject to credentialing, and (2) seeding their consult count instead of using a raw 0."""

    restrict_scope_to_gap_hospitals: bool = True
    seed_policy: Literal["median_peer", "low_volume_threshold", "none"] = "median_peer"
    scope_when_no_gap: Literal["all_credentialed", "none"] = "all_credentialed"
    model_window_minutes: int = 120
    """Length of the modeled-arrival trap demonstration (uses baseline hourly means)."""
    seed_peer_overlap_minutes: int = Field(default=30, ge=0)
    """CHOICE: a peer counts toward the seeded count only if still working this long after
    the joiner comes online (someone leaving minutes later does not share the calls)."""
    overflow_outside_scope: bool = True
    """CHOICE: the routing scope is not a wall. A consult at one of the joiner's other
    credentialed hospitals may still go to them if it already has an alert of at least
    ``overflow_min_severity`` (it is past a time limit). Such an edge costs more than any
    regular edge, so the solver uses it only when no one else can take the consult."""
    overflow_min_severity: Literal["warning", "critical"] = "warning"


class StaffingPolicy(BaseModel):
    rest_hours: float = 10
    """BRIEF: at least 10 hours since last shift ended, measured at the offered start."""
    weekly_hour_limit: float = 60
    """BRIEF: hours worked in the trailing 7 days plus offered hours <= 60."""
    min_offer_minutes: int = 120
    """BRIEF: offers are at least 2 hours long."""
    max_open_offers_per_physician: int = 1
    max_offers_per_physician_per_week: int = 3
    """BRIEF notification constraints, checked against the system's own offer log."""
    online_time_counts_against_value: bool = True
    """BRIEF: the estimated time to come online counts against the value of the offer, so
    modeled coverage starts at offer start + time-to-online."""
    assumed_online_minutes_if_missing: int = 30
    """ASSUMPTION: when time-to-online is missing, assume this (flagged) rather than zero."""
    duration_options_minutes: list[int] = Field(default_factory=lambda: [120, 180, 240, 360])
    """CHOICE: finite offer lengths for CP-SAT (all >= the 2-hour minimum)."""
    fit_lengths_to_gap: bool = True
    """CHOICE: besides ``duration_options_minutes``, also offer the shortest valid length
    (2 h of coverage plus the time to come online) and lengths that end exactly when a gap
    ends, so an offer does not run past the need."""
    login_buffer_minutes: int = Field(default=10, ge=0)
    """CHOICE: just-in-time offers start so the physician is online this many minutes before
    the gap starts (the time to come online is only an estimate)."""
    max_start_options: int = 6
    planning_horizon_minutes: int = 240
    """CHOICE: offers last >= 2h, so offer starts and lengths are planned and valued over a
    longer window than the 90-minute dashboard forecast, using the same Phase 3 coverage
    engine. It does not decide which hospitals count as short (see below)."""
    shortage_lookahead_minutes: int | None = None
    """DECISION (team, see docs/official-scenario-audit.md): a hospital counts as short for
    split-shift purposes only if its coverage gap starts within this many minutes. None =
    the dashboard's coverage forecast window (90 min by default, the brief's minimum), so
    the dashboard and the split-shift rules always agree on which hospitals are short."""
    count_at_all_scope_hospitals: bool = True
    """BRIEF coverage model: a physician counts toward every hospital they are credentialed at.
    Set false to force each proposed physician to cover exactly one hospital (exclusive)."""
    max_new_physicians: int = 3
    require_full_coverage: bool = False
    """If true, CP-SAT must remove every deficit (can be INFEASIBLE)."""
    missing_data_fails: bool = True
    """Missing opt-in, rest, hours or schedule data fails the rule (never passes silently)."""


class VoluntaryPolicy(BaseModel):
    """How a physician's voluntary availability (submitted from the off-shift portal) affects
    split-shift recommendations. It is a preference, never a rule: only offers that already
    pass every split-shift rule (opt-in, credentials, rest, hours, overlap, length, offer
    limits, declines) can benefit from it, and it never assigns anyone a shift."""

    enabled: bool = True
    coverage_tolerance: float = Field(default=0.15, ge=0, le=0.5)
    """CHOICE: an offer that lies inside a physician's volunteered window is preferred over
    the plan without voluntary availability, as long as each affected hospital keeps at least
    (1 - tolerance) of the deficit reduction that plan achieves and the same number of
    physicians is contacted. Rationale: an unsolicited offer can be declined or expire after
    10 minutes (and uses one of the physician's 3 weekly offers); a volunteer has already said
    yes to that time, so a small coverage difference buys a much more certain answer. 0 =
    voluntary availability only breaks exact ties."""
    fit_offers_to_window: bool = True
    """CHOICE: also generate offer options that start and end inside each volunteered
    window (every option is still re-checked against every rule)."""


class CostPolicy(BaseModel):
    """Estimated staffing cost of a split-shift offer. The optimizer's existing cost measure
    is paid offer time (the ``offered_minutes`` stage) plus excess coverage; this turns paid
    offer time into an amount so plans can be compared. The same rate applies to every
    physician: volunteering never makes a physician cheaper."""

    hourly_rate: float = Field(default=200.0, ge=0)
    """ASSUMPTION: illustrative split-shift rate. The dataset has no pay data, so this is not
    Sevaro's pay scale; override it with OPTIMIZATION_POLICY_FILE."""
    currency: str = "USD"
    paid_includes_time_to_online: bool = True
    """BRIEF: the time to come online counts against what the offer is worth, so the whole
    offer (including logging in) is paid while only the time after it covers the gap."""


class SolverLimits(BaseModel):
    staffing_time_limit_seconds: float = 3.0
    staffing_deterministic_time: float = 5.0
    random_seed: int = 0
    num_workers: int = 1
    """One worker + fixed seed + deterministic time limit: identical input, identical result."""
    allow_fallback: bool = True
    """If OR-Tools is missing: true = clearly labelled greedy fallback, false = explicit error."""


class OptimizationConfig(BaseModel):
    routing: RoutingPolicy = Field(default_factory=RoutingPolicy)
    weights: DispatchWeights = Field(default_factory=DispatchWeights)
    trap: TrapPolicy = Field(default_factory=TrapPolicy)
    staffing: StaffingPolicy = Field(default_factory=StaffingPolicy)
    voluntary: VoluntaryPolicy = Field(default_factory=VoluntaryPolicy)
    cost: CostPolicy = Field(default_factory=CostPolicy)
    solver: SolverLimits = Field(default_factory=SolverLimits)
    policy_version: str = "phase4-v1"

    def signature(self) -> str:
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()[:16]


def _merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = dict(base)
    for key, value in override.items():
        out[key] = (
            _merge(out[key], value)
            if isinstance(value, dict) and isinstance(out.get(key), dict)
            else value
        )
    return out


def load_optimization_config(path: Path | None = None) -> OptimizationConfig:
    if path is None:
        return OptimizationConfig()
    data = json.loads(path.read_text(encoding="utf-8"))
    return OptimizationConfig.model_validate(
        _merge(OptimizationConfig().model_dump(mode="json"), data)
    )
