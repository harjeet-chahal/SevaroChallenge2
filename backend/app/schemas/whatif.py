"""What-if previews and baseline comparisons (Phase 4). Read-only projections."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import AwareDatetime, Field

from app.schemas.common import ApiModel, EntityId
from app.schemas.coverage import HospitalCoverage
from app.schemas.dispatch import RuleCheck, SolverRun, WorkloadChange


class SplitShiftAction(ApiModel):
    kind: Literal["split_shift"] = "split_shift"
    physician_id: EntityId
    start: AwareDatetime | None = None
    """Defaults to the earliest valid start."""
    duration_minutes: int = Field(default=120, ge=1, le=24 * 60)
    hospital_ids: list[EntityId] | None = None
    """Routing scope. Defaults to the credentialed gap hospitals."""


class AssignConsultAction(ApiModel):
    kind: Literal["assign_consult"] = "assign_consult"
    consult_id: EntityId
    physician_id: EntityId


ProposedAction = Annotated[SplitShiftAction | AssignConsultAction, Field(discriminator="kind")]


class SimulateRequest(ApiModel):
    as_of: AwareDatetime | None = None
    action: ProposedAction
    horizon_minutes: int | None = Field(default=None, ge=90, le=720)


class HospitalProjection(ApiModel):
    hospital_id: EntityId
    hospital_name: str
    before: HospitalCoverage
    after: HospitalCoverage
    """Projected if accepted. Never confirmed coverage."""
    deficit_physician_minutes_before: float
    deficit_physician_minutes_after: float
    reduction: float
    deficit_now_before: int | None
    deficit_now_after: int | None
    first_shortfall_before: AwareDatetime | None
    first_shortfall_after: AwareDatetime | None


class WhatIfResult(ApiModel):
    as_of: AwareDatetime
    data_version: int
    label: str = "Projected if accepted — not confirmed coverage"
    action: SplitShiftAction | AssignConsultAction
    allowed: bool
    violations: list[RuleCheck]
    checks: list[RuleCheck]
    horizon_minutes: int
    projections: list[HospitalProjection]
    workload: WorkloadChange | None = None
    effects_not_modeled: list[str]
    explanations: list[str]


class MetricPair(ApiModel):
    metric: str
    label: str
    baseline: float | None
    optimized: float | None
    better: Literal["lower", "higher"]
    outcome: Literal["optimized_better", "tie", "baseline_better", "not_comparable"]
    note: str | None = None


class ComparisonSection(ApiModel):
    title: str
    baseline_method: str
    optimized_method: str
    metrics: list[MetricPair]
    summary: str
    details: list[str] = Field(default_factory=list)


class OptimizationComparison(ApiModel):
    as_of: AwareDatetime
    data_version: int
    policy_version: str
    dispatch: ComparisonSection
    staffing: ComparisonSection
    trap: ComparisonSection | None
    solvers: list[SolverRun]
    notes: list[str]
