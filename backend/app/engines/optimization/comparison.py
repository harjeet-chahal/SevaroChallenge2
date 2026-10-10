"""Baseline vs optimized, on the identical snapshot and identical hard constraints.

Outcomes are reported as they are: ties are ties, and a metric where the baseline does
better is shown as ``baseline_better`` (the optimizer trades some metrics for higher
priority ones by design — e.g. a stroke consult over raw load balance).
"""

from __future__ import annotations

import statistics

from app.engines.optimization.routing.problem import DispatchProblem
from app.engines.optimization.split_shift import StaffingInternals, evaluate_plan, staffing_baseline
from app.schemas.dispatch import DispatchPlan, DispatchResult
from app.schemas.staffing import StaffingResult
from app.schemas.whatif import ComparisonSection, MetricPair


def _pair(
    metric: str,
    label: str,
    baseline: float | None,
    optimized: float | None,
    better: str,
    note: str | None = None,
) -> MetricPair:
    if baseline is None or optimized is None:
        outcome = "not_comparable"
    elif abs(baseline - optimized) < 1e-9:
        outcome = "tie"
    elif (optimized < baseline) == (better == "lower"):
        outcome = "optimized_better"
    else:
        outcome = "baseline_better"
    return MetricPair(
        metric=metric,
        label=label,
        baseline=baseline,
        optimized=optimized,
        better=better,
        outcome=outcome,
        note=note,
    )


def _summary(metrics: list[MetricPair], subject: str) -> str:
    better = [m.label for m in metrics if m.outcome == "optimized_better"]
    worse = [m.label for m in metrics if m.outcome == "baseline_better"]
    ties = sum(m.outcome == "tie" for m in metrics)
    if not better and not worse:
        return f"{subject}: the optimizer ties the baseline on every metric."
    parts = []
    if better:
        parts.append(f"better on {', '.join(better)}")
    if worse:
        parts.append(f"worse on {', '.join(worse)}")
    if ties:
        parts.append(f"tied on {ties}")
    return f"{subject}: optimized is " + "; ".join(parts) + "."


def _violations(problem: DispatchProblem, plan: DispatchPlan) -> int:
    count = 0
    load: dict[str, int] = {}
    for r in plan.recommendations:
        if (r.consult_id, r.physician_id) not in problem.edges:
            count += 1
        load[r.physician_id] = load.get(r.physician_id, 0) + 1
    cap = problem.config.routing.sync_capacity
    return count + sum(max(0, v - cap) for v in load.values())


def _loads(problem: DispatchProblem, plan: DispatchPlan) -> list[int]:
    extra: dict[str, int] = {}
    for r in plan.recommendations:
        extra[r.physician_id] = extra.get(r.physician_id, 0) + 1
    return [
        p.actual_consults_this_shift + extra.get(pid, 0)
        for pid, p in problem.physicians.items()
        if p.on_shift
    ]


def dispatch_section(
    result: DispatchResult, baseline: DispatchPlan, problem: DispatchProblem, coverage_pm: float
) -> ComparisonSection:
    opt = result.plan
    urgent = {
        c.consult_id for c in problem.consults if c.category == "stroke" or c.severity == "critical"
    }

    def urgent_left(plan: DispatchPlan) -> int:
        return sum(u.consult_id in urgent for u in plan.unassigned)

    def stdev(values: list[int]) -> float | None:
        return round(statistics.pstdev(values), 3) if values else None

    lo, lb = _loads(problem, opt), _loads(problem, baseline)
    metrics = [
        _pair(
            "assigned",
            "consults placed",
            len(baseline.recommendations),
            len(opt.recommendations),
            "higher",
        ),
        _pair(
            "urgent_unassigned",
            "urgent consults left unassigned",
            urgent_left(baseline),
            urgent_left(opt),
            "lower",
            "urgent = stroke or a critical alert",
        ),
        _pair(
            "max_workload",
            "highest consults this shift after",
            max(lb, default=None),
            max(lo, default=None),
            "lower",
        ),
        _pair("workload_stdev", "workload spread (std dev)", stdev(lb), stdev(lo), "lower"),
        _pair(
            "objective_cost",
            "objective cost (same cost function)",
            baseline.objective_cost,
            opt.objective_cost,
            "lower",
        ),
        _pair(
            "constraint_violations",
            "hard-constraint violations",
            _violations(problem, baseline),
            _violations(problem, opt),
            "lower",
        ),
        _pair(
            "coverage_gap_pm",
            "coverage gap physician-minutes",
            coverage_pm,
            coverage_pm,
            "lower",
            "dispatch does not change coverage: physicians count, not consults",
        ),
    ]
    details = []
    for r in opt.recommendations:
        b = next((x for x in baseline.recommendations if x.consult_id == r.consult_id), None)
        if b is None:
            details.append(
                f"{r.consult_id}: optimized → {r.physician_name}; baseline leaves it unassigned."
            )
        elif b.physician_id != r.physician_id:
            details.append(
                f"{r.consult_id}: optimized → {r.physician_name}; baseline → {b.physician_name}."
            )
    for b in baseline.recommendations:
        if not any(r.consult_id == b.consult_id for r in opt.recommendations):
            details.append(
                f"{b.consult_id}: baseline → {b.physician_name}; optimized leaves it unassigned."
            )
    if not details:
        details.append("Both methods produce the same assignments.")
    return ComparisonSection(
        title="Consultation routing",
        baseline_method="Least-loaded routing (brief rules 3–4) in arrival order, same hard "
        "constraints",
        optimized_method=f"{result.solver.solver} (lexicographic: urgency, waiting, workload)",
        metrics=metrics,
        summary=_summary(metrics, "Routing"),
        details=details,
    )


def staffing_section(result: StaffingResult, internals: StaffingInternals) -> ComparisonSection:
    ctx = internals.ctx
    base_choice = staffing_baseline(ctx, internals.options)
    base_after, base_excess = evaluate_plan(
        ctx, base_choice, {o.index: o.hospitals for o in base_choice}
    )
    t = result.totals
    metrics = [
        _pair(
            "deficit_after",
            f"deficit physician-minutes left ({ctx.horizon_minutes} min)",
            round(sum(base_after.values()), 4),
            t.deficit_physician_minutes_after,
            "lower",
        ),
        _pair(
            "physicians_used", "physicians contacted", len(base_choice), t.physicians_used, "lower"
        ),
        _pair(
            "offered_minutes",
            "offered minutes",
            sum(o.minutes for o in base_choice),
            t.offered_minutes,
            "lower",
        ),
        _pair(
            "excess_pm",
            "excess coverage physician-minutes",
            base_excess,
            t.excess_physician_minutes,
            "lower",
        ),
    ]
    details = [
        f"No action: {t.deficit_physician_minutes_before:g} deficit physician-minutes.",
        "Baseline offers: "
        + (
            ", ".join(f"{o.name} {o.minutes} min at {', '.join(o.hospitals)}" for o in base_choice)
            or "none"
        )
        + ".",
        "Optimized offers: "
        + (
            ", ".join(
                f"{r.display_name} {r.offer_minutes} min at {', '.join(r.hospital_ids)}"
                for r in result.recommendations
            )
            or "none"
        )
        + ".",
    ]
    return ComparisonSection(
        title="Split-shift staffing",
        baseline_method="Earliest-online physician first, longest valid offer, same eligibility",
        optimized_method=f"{result.solver.solver} (lexicographic: deficit, physicians, excess, "
        "hours, start)",
        metrics=metrics,
        summary=_summary(metrics, "Staffing"),
        details=details,
    )


def trap_section(result: StaffingResult) -> ComparisonSection | None:
    trap = result.trap
    if trap is None:
        return None
    u, p = trap.unrestricted, trap.protected
    metrics = [
        _pair(
            "to_joiner",
            f"modeled consults to {trap.display_name}",
            u.routed_to_joiner,
            p.routed_to_joiner,
            "lower",
        ),
        _pair(
            "to_joiner_elsewhere",
            "…of which at hospitals without a gap",
            u.routed_to_joiner_elsewhere,
            p.routed_to_joiner_elsewhere,
            "lower",
        ),
        _pair(
            "max_consults",
            "highest consults any physician",
            u.max_consults_any_physician,
            p.max_consults_any_physician,
            "lower",
        ),
        _pair("unrouted", "modeled consults with nobody eligible", u.unrouted, p.unrouted, "lower"),
    ]
    return ComparisonSection(
        title="Split-shift trap",
        baseline_method="Unrestricted least-loaded routing, joiner starts at 0 consults",
        optimized_method="Protected: gap-hospital scope + seeded consult count",
        metrics=metrics,
        summary=_summary(metrics, "Trap protection"),
        details=[trap.conclusion, *trap.assumptions],
    )
