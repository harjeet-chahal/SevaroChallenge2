"""One pure entry point for Phase 3: events + reference + time -> everything the UI needs.

    analysis = analyze(events, reference, as_of, config)

Deterministic: identical inputs give identical outputs (tested), regardless of event order.
"""

from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.engines.alert_detection import context, detect_all, rank_alerts
from app.engines.coverage_prediction import (
    HospitalCoverageModel,
    build_coverage_models,
    build_coverage_report,
)
from app.engines.demand import HospitalDemandModel, build_demand_models, build_demand_report
from app.engines.interventions.overlay import OverlayEntry, apply_workflow_overlay
from app.engines.replay import reconstruct_state
from app.engines.rules import RiskConfig
from app.schemas.alert import AlertList
from app.schemas.coverage import CoverageReport
from app.schemas.demand import DemandReport
from app.schemas.event import StoredEvent
from app.schemas.metrics import OperationalMetrics, PhysicianWorkload
from app.schemas.physician import Availability
from app.schemas.state import OperationalState, ReferenceData


@dataclass
class OperationalAnalysis:
    state: OperationalState
    reference: ReferenceData
    config: RiskConfig
    demand_models: dict[str, HospitalDemandModel]
    coverage_models: dict[str, HospitalCoverageModel]
    demand: DemandReport
    coverage: CoverageReport
    alerts: AlertList
    metrics: OperationalMetrics
    stranded: dict[str, list[str]] | None = None
    """hospital_id -> urgent consults no one on duty can take now, already counted in the
    coverage forecast. None: not evaluated (no ``stranded`` check was given)."""


StrandedCheck = Callable[["OperationalAnalysis"], Mapping[str, Sequence[str]]]
"""Given a first-pass analysis, the urgent consults per hospital that no one on duty can
take (the routing optimizer supplies it; this module does not depend on Phase 4)."""


def build_metrics(
    state: OperationalState, coverage: CoverageReport, demand: DemandReport, alerts: AlertList
) -> OperationalMetrics:
    on_shift = [p for p in state.physicians if p.on_shift]
    open_consults = [c for c in state.consultations if c.is_open]
    waits = [
        c.seconds_since_received for c in open_consults if c.seconds_since_received is not None
    ]
    gaps_now = [h for h in coverage.hospitals if h.metrics.deficit_now]
    projected = [
        h
        for h in coverage.hospitals
        if not h.metrics.deficit_now and h.metrics.first_shortfall_at is not None
    ]
    earliest = min(
        projected, key=lambda h: (h.metrics.first_shortfall_at, h.hospital_id), default=None
    )
    pm = [h.metrics.deficit_physician_minutes for h in coverage.hospitals]
    return OperationalMetrics(
        as_of=state.as_of,
        data_version=state.data_version,
        physicians={
            "on_shift": len(on_shift),
            "busy": sum(p.availability is Availability.BUSY for p in on_shift),
            "available": sum(p.availability is Availability.AVAILABLE for p in on_shift),
            "unavailable": sum(p.availability is Availability.UNAVAILABLE for p in on_shift),
            "with_uncertain_signals": sum(
                any(f.severity.value != "info" for f in p.flags) for p in on_shift
            ),
        },
        consults={
            "open": len(open_consults),
            "unassigned": sum(c.assigned_physician_id is None for c in open_consults),
            "assigned": sum(c.assigned_physician_id is not None for c in open_consults),
            "closed": len(state.consultations) - len(open_consults),
            "with_routing_failures": sum(c.routing_failures > 0 for c in open_consults),
        },
        open_consults_by_stage=dict(sorted(Counter(c.stage.value for c in open_consults).items())),
        longest_open_wait_seconds=max(waits) if waits else None,
        alerts_by_severity=alerts.counts_by_severity,
        alerts_by_rule=alerts.counts_by_rule,
        coverage={
            "hospitals": len(coverage.hospitals),
            "hospitals_without_requirement": sum(
                not h.requirement_defined for h in coverage.hospitals
            ),
            "gap_now": len(gaps_now),
            "gap_projected": len(projected),
            "deficit_physician_minutes_total": round(sum(pm), 4),
            "median_hospital_deficit_physician_minutes": round(statistics.median(pm), 4)
            if pm
            else None,
            "horizon_minutes": coverage.horizon_minutes,
        },
        earliest_projected_gap_at=earliest.metrics.first_shortfall_at if earliest else None,
        earliest_projected_gap_hospital_id=earliest.hospital_id if earliest else None,
        demand={
            "hospitals_spiking": sum(bool(h.current.spike) for h in demand.hospitals),
            "hospitals_missing_baseline": sum(h.current.spike is None for h in demand.hospitals),
            "arrivals_last_window": sum(h.current.arrivals for h in demand.hospitals),
        },
        workload=[
            PhysicianWorkload(
                physician_id=p.physician_id,
                display_name=p.display_name,
                on_shift=p.on_shift,
                availability=p.availability.value,
                consults_this_shift=p.consults_this_shift,
                calls_this_shift=p.calls_this_shift,
                open_consults=len(p.open_consult_ids),
                credentialed_hospitals=len(p.credentialed_hospital_ids),
            )
            for p in state.physicians
            if p.on_shift
        ],
    )


def analyze_state(
    state: OperationalState,
    reference: ReferenceData,
    config: RiskConfig,
    *,
    horizon_minutes: int | None = None,
    step_minutes: int | None = None,
    stranded: StrandedCheck | None = None,
) -> OperationalAnalysis:
    """``stranded``: when given, a second pass counts each urgent consult no one on duty can
    take as one more physician needed at its hospital, for the whole forecast horizon (it is
    re-checked every time the clock moves), then rebuilds the forecast and the alerts."""
    as_of = state.as_of
    horizon = horizon_minutes or config.coverage.horizon_minutes
    step = step_minutes or config.coverage.chart_step_minutes
    hospitals = {h.id: h for h in state.hospitals}
    demand_models = build_demand_models(
        state.consultations,
        [(h.id, h.timezone) for h in state.hospitals],
        reference.baseline_volume,
        as_of,
        window_minutes=config.demand.window_minutes,
        requirement_increase=config.demand.requirement_increase,
    )
    demand = build_demand_report(
        demand_models, hospitals, as_of, as_of + timedelta(minutes=horizon), config.demand
    )
    coverage_models = build_coverage_models(
        state, reference, demand_models, config.coverage, horizon
    )
    coverage = build_coverage_report(
        coverage_models, as_of, config.coverage, horizon, step, state.data_version
    )
    ctx = context(state, config, coverage, demand, state.hospitals)
    alerts = rank_alerts(ctx, detect_all(ctx), state.data_version)
    result = OperationalAnalysis(
        state=state,
        reference=reference,
        config=config,
        demand_models=demand_models,
        coverage_models=coverage_models,
        demand=demand,
        coverage=coverage,
        alerts=alerts,
        metrics=build_metrics(state, coverage, demand, alerts),
    )
    if stranded is None:
        return result
    found = {
        hid: list(ids) for hid, ids in stranded(result).items() if ids and hid in coverage_models
    }
    result.stranded = found
    if not found:
        return result
    horizon_end = as_of + timedelta(minutes=horizon)
    for hid, ids in found.items():
        coverage_models[hid].add_stranded(ids, horizon_end)
    coverage = build_coverage_report(
        coverage_models, as_of, config.coverage, horizon, step, state.data_version
    )
    ctx = context(state, config, coverage, demand, state.hospitals)
    alerts = rank_alerts(ctx, detect_all(ctx), state.data_version)
    result.coverage = coverage
    result.alerts = alerts
    result.metrics = build_metrics(state, coverage, demand, alerts)
    return result


def analyze(
    events: Sequence[StoredEvent],
    reference: ReferenceData,
    as_of: datetime,
    config: RiskConfig | None = None,
    *,
    data_version: int = 0,
    horizon_minutes: int | None = None,
    step_minutes: int | None = None,
    overlay: Sequence[OverlayEntry] = (),
    stranded: StrandedCheck | None = None,
) -> OperationalAnalysis:
    """``overlay``: accepted/activated split shifts from the Phase 5 workflow, applied
    time-aware on top of the replay so staffing, forecasts, alerts and optimizers all see
    the same derived state."""
    state = reconstruct_state(events, as_of, reference, data_version=data_version)
    if overlay:
        state, reference = apply_workflow_overlay(state, reference, overlay)
    return analyze_state(
        state,
        reference,
        config or RiskConfig(),
        horizon_minutes=horizon_minutes,
        step_minutes=step_minutes,
        stranded=stranded,
    )
