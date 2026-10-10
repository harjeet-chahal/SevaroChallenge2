"""What-if preview: ``simulate_intervention(current_state, proposed_action, forecast_config)``.

Pure and read-only. The Phase 3 coverage engine is run twice — as is, and with the proposed
action applied to a copy of the model — so "before" and "after" come from the same code as
the dashboard. The result is labelled "Projected if accepted" and is never stored, so a
proposal can never appear as confirmed coverage. Effects the model cannot compute (patient
wait times, acceptance) are listed instead of being invented.

A proposed action that breaks any hard rule is rejected with the violated rules and no
projection: what-if analysis cannot be used to preview an unsafe action as if it were fine.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import timedelta

from app.engines.analysis import OperationalAnalysis
from app.engines.coverage_prediction import (
    HospitalCoverageModel,
    build_coverage_models,
    build_hospital_coverage,
)
from app.engines.optimization.config import OptimizationConfig
from app.engines.optimization.routing import build_dispatch_problem
from app.engines.optimization.split_shift import (
    build_planning_context,
    evaluate_candidate,
    offer_checks,
    proposed_window,
)
from app.engines.optimization.split_shift.candidates import Option
from app.engines.timeline import fmt_local
from app.schemas.coverage import CoverageContributor
from app.schemas.dispatch import RuleCheck, WorkloadChange
from app.schemas.whatif import (
    AssignConsultAction,
    HospitalProjection,
    SplitShiftAction,
    WhatIfResult,
)

NOT_MODELED = [
    "Patient wait-time changes are not projected: the model does not forecast arrivals or "
    "service times, so no wait-time reduction is claimed.",
    "Acceptance is not assumed: this shows coverage if the offer is accepted and the "
    "physician comes online as estimated.",
]


@dataclass(frozen=True)
class ForecastConfig:
    optimization: OptimizationConfig
    horizon_minutes: int | None = None
    """Defaults to the analysis horizon (the dashboard forecast)."""
    step_minutes: int | None = None


def _violation(code: str, label: str, message: str) -> RuleCheck:
    return RuleCheck(
        code=code, label=label, passed=False, message=message, source="implementation_choice"
    )


def _models(analysis: OperationalAnalysis, horizon: int) -> dict[str, HospitalCoverageModel]:
    if horizon == analysis.coverage.horizon_minutes:
        return analysis.coverage_models
    return build_coverage_models(
        analysis.state,
        analysis.reference,
        analysis.demand_models,
        analysis.config.coverage,
        horizon,
    )


def _projection(
    model: HospitalCoverageModel, after_model: HospitalCoverageModel, horizon: int, step: int
) -> HospitalProjection:
    before = build_hospital_coverage(model, step_minutes=step, horizon_minutes=horizon)
    after = build_hospital_coverage(after_model, step_minutes=step, horizon_minutes=horizon)
    b, a = before.metrics, after.metrics
    return HospitalProjection(
        hospital_id=model.hospital.id,
        hospital_name=model.hospital.name,
        before=before,
        after=after,
        deficit_physician_minutes_before=b.deficit_physician_minutes,
        deficit_physician_minutes_after=a.deficit_physician_minutes,
        reduction=round(b.deficit_physician_minutes - a.deficit_physician_minutes, 4),
        deficit_now_before=b.deficit_now,
        deficit_now_after=a.deficit_now,
        first_shortfall_before=b.first_shortfall_at,
        first_shortfall_after=a.first_shortfall_at,
    )


def _split_shift(
    analysis: OperationalAnalysis, action: SplitShiftAction, fc: ForecastConfig
) -> WhatIfResult:
    cfg = fc.optimization
    state = analysis.state
    horizon = fc.horizon_minutes or analysis.coverage.horizon_minutes
    step = fc.step_minutes or analysis.coverage.chart_step_minutes
    p = next((x for x in state.physicians if x.physician_id == action.physician_id), None)
    base = {
        "as_of": state.as_of,
        "data_version": state.data_version,
        "action": action,
        "horizon_minutes": horizon,
        "effects_not_modeled": NOT_MODELED,
    }
    if p is None:
        v = _violation("unknown_physician", "Known physician", f"{action.physician_id} not found")
        return WhatIfResult(
            **base,
            allowed=False,
            violations=[v],
            checks=[v],
            projections=[],
            explanations=[v.message],
        )
    if p.roster != "off_shift":
        v = _violation(
            "not_off_shift_roster",
            "Off-shift roster physician",
            f"{p.display_name} is not on the off-shift roster; split shifts are offered only "
            "to off-shift physicians",
        )
        return WhatIfResult(
            **base,
            allowed=False,
            violations=[v],
            checks=[v],
            projections=[],
            explanations=[v.message],
        )
    ctx = build_planning_context(analysis, cfg)
    profile = next((x for x in analysis.reference.physicians if x.id == p.physician_id), None)
    cand = evaluate_candidate(p, profile, ctx)
    start = action.start or cand.eligibility.earliest_valid_start or state.as_of
    scope = tuple(sorted(action.hospital_ids)) if action.hospital_ids else cand.scope
    checks = offer_checks(
        p,
        profile,
        start,
        action.duration_minutes,
        scope,
        ctx,
        cand.online_minutes,
        cand.eligibility.online_time_assumed,
    )
    if start < state.as_of:
        checks.append(
            _violation("start_in_past", "Starts now or later", "the offered start is in the past")
        )
    violations = [c for c in checks if not c.passed]
    if violations:
        return WhatIfResult(
            **base,
            allowed=False,
            violations=violations,
            checks=checks,
            projections=[],
            explanations=[
                f"Not allowed: {p.display_name} — "
                + "; ".join(v.message for v in violations)
                + ".",
                "No projection is shown for an offer that breaks a rule.",
            ],
        )
    option = Option(
        index=0,
        physician_id=p.physician_id,
        name=p.display_name,
        start=start,
        minutes=action.duration_minutes,
        online_at=start + timedelta(minutes=cand.online_minutes),
        end=start + timedelta(minutes=action.duration_minutes),
        hospitals=scope,
    )
    window = proposed_window(option)
    models = _models(analysis, horizon)
    projections = []
    for hid in scope:
        model = models[hid]
        contributor = CoverageContributor(
            physician_id=p.physician_id,
            display_name=p.display_name,
            status="proposed",
            certainty="uncertain",
            counts_from=window.start,
            counts_until=window.end,
            reasons=[
                "Projected if accepted — proposed split shift, not confirmed coverage",
                f"online {cand.online_minutes} min after the offered start",
            ],
        )
        after_model = replace(
            model,
            windows=[*model.windows, window],
            contributors=[
                *(c for c in model.contributors if c.physician_id != p.physician_id),
                contributor,
            ],
        )
        projections.append(_projection(model, after_model, horizon, step))
    tz = ctx.tz_for(scope)
    explanations = [
        f"Projected if accepted: {p.display_name} {fmt_local(option.start, tz)}–"
        f"{fmt_local(option.end, tz)}, online {fmt_local(option.online_at, tz)}.",
        *(
            f"{x.hospital_name}: deficit {x.deficit_physician_minutes_before:g} → "
            f"{x.deficit_physician_minutes_after:g} physician-minutes over {horizon} min."
            for x in projections
        ),
        "This preview does not create, approve or send an offer.",
    ]
    return WhatIfResult(
        **base,
        allowed=True,
        violations=[],
        checks=checks,
        projections=projections,
        explanations=explanations,
    )


def _assign(
    analysis: OperationalAnalysis, action: AssignConsultAction, fc: ForecastConfig
) -> WhatIfResult:
    state = analysis.state
    horizon = fc.horizon_minutes or analysis.coverage.horizon_minutes
    step = fc.step_minutes or analysis.coverage.chart_step_minutes
    base = {
        "as_of": state.as_of,
        "data_version": state.data_version,
        "action": action,
        "horizon_minutes": horizon,
        "effects_not_modeled": [NOT_MODELED[0]],
    }
    problem = build_dispatch_problem(analysis, fc.optimization)
    consult = next((c for c in problem.consults if c.consult_id == action.consult_id), None)
    violations: list[RuleCheck] = []
    if consult is None:
        skipped = next((s for s in problem.skipped if s[0] == action.consult_id), None)
        message = skipped[3] if skipped else f"{action.consult_id} is not an open consult"
        violations.append(_violation("not_dispatchable", "Consult needs routing", message))
    elif (action.consult_id, action.physician_id) not in problem.edges:
        excluded = next(
            (
                x
                for x in problem.exclusions.get(action.consult_id, [])
                if x.physician_id == action.physician_id
            ),
            None,
        )
        reasons = (
            excluded.reasons
            if excluded
            else ["not on shift or not credentialed at the consult's hospital"]
        )
        violations += [
            _violation("dispatch_eligibility", "Eligible for this consult", r) for r in reasons
        ]
    if violations:
        return WhatIfResult(
            **base,
            allowed=False,
            violations=violations,
            checks=violations,
            projections=[],
            explanations=["Not allowed: " + "; ".join(v.message for v in violations) + "."],
        )
    p = problem.physicians[action.physician_id]
    models = _models(analysis, horizon)
    projections = (
        [_projection(models[consult.hospital_id], models[consult.hospital_id], horizon, step)]
        if consult.hospital_id in models
        else []
    )
    return WhatIfResult(
        **base,
        allowed=True,
        violations=[],
        checks=[],
        projections=projections,
        workload=WorkloadChange(
            consults_this_shift_before=p.actual_consults_this_shift,
            consults_this_shift_after=p.actual_consults_this_shift + 1,
            open_consults_before=p.open_consults,
            open_consults_after=p.open_consults + 1,
        ),
        explanations=[
            f"{p.name} is eligible for {action.consult_id} (rules 1–2 pass).",
            "Coverage counts physicians, not consults: assigning a consult does not change "
            "the modeled coverage, so before and after are identical.",
            "This preview does not assign the consult.",
        ],
    )


def simulate_intervention(
    current_state: OperationalAnalysis,
    proposed_action: SplitShiftAction | AssignConsultAction,
    forecast_config: ForecastConfig,
) -> WhatIfResult:
    if isinstance(proposed_action, SplitShiftAction):
        return _split_shift(current_state, proposed_action, forecast_config)
    return _assign(current_state, proposed_action, forecast_config)
