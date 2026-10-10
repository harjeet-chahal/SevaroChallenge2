"""Optimizer B — split-shift staffing (OR-Tools CP-SAT). Recommendations only.

    result, internals = run_staffing(analysis, config)

Eligibility first (every off-shift physician, every rule), then finite offer options that
pass every rule, then CP-SAT. The chosen plan is re-scored with the Phase 3 coverage
engine itself, so the reported before/after figures come from the same model as the
dashboard, not from the optimizer's own arithmetic.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta

from app.engines.analysis import OperationalAnalysis
from app.engines.coverage_prediction import Window, hypothetical_window
from app.engines.optimization.config import OptimizationConfig
from app.engines.optimization.solvers import SolverUnavailableError
from app.engines.optimization.split_shift.candidates import (
    Candidate,
    Option,
    PlanningContext,
    build_planning_context,
    evaluate_candidate,
    evaluate_candidates,
    generate_options,
    offer_checks,
)
from app.engines.optimization.split_shift.cpsat import (
    StaffingSolution,
    build_pieces,
    solve_cpsat,
    solve_greedy,
)
from app.engines.optimization.split_shift.trap import protection_for, trap_analysis
from app.engines.timeline import fmt_local
from app.schemas.dispatch import SolverRun
from app.schemas.staffing import (
    HospitalEffect,
    ShiftRecommendation,
    StaffingResult,
    StaffingTotals,
)

PROPOSED_REASON = "proposed split shift — projected if accepted, not confirmed"

RULES_TEXT = [
    "Opted in to split-shift offers (brief).",
    "Credentialed at one or more hospitals with the gap; elsewhere does not help (brief).",
    "At least 10 hours since the last shift ended, measured at the offered start (brief).",
    "Trailing 7-day hours plus offered hours ≤ 60 (brief).",
    "The offer does not overlap a scheduled shift (brief).",
    "Offers are at least 2 hours; time to come online counts against the offer (brief).",
    "≤ 1 open offer per physician and ≤ 3 offers per week, from the system offer log (brief).",
]


@dataclass
class StaffingInternals:
    ctx: PlanningContext
    candidates: list[Candidate]
    options: list[Option]
    solution: StaffingSolution


def proposed_window(option: Option) -> Window:
    return hypothetical_window(
        option.physician_id, option.name, option.online_at, option.end, PROPOSED_REASON
    )


def evaluate_plan(
    ctx: PlanningContext, chosen: list[Option], assigned: dict[int, tuple[str, ...]]
) -> tuple[dict[str, float], float]:
    """Remaining deficit physician-minutes per hospital (Phase 3 engine) and excess added."""
    after: dict[str, float] = {}
    for hid, model in ctx.models.items():
        extra = [proposed_window(o) for o in chosen if hid in assigned.get(o.index, ())]
        after[hid] = (
            round(model.deficit_physician_minutes(extra), 4) if extra else ctx.base_deficit[hid]
        )
    added = sum(_covered_minutes(ctx, o) * len(assigned.get(o.index, ())) for o in chosen)
    reduction = sum(ctx.base_deficit.values()) - sum(after.values())
    return after, round(max(0.0, added - reduction), 4)


def _covered_minutes(ctx: PlanningContext, o: Option) -> float:
    a = max(o.online_at, ctx.as_of)
    b = min(o.end, ctx.plan_end)
    return max(0.0, (b - a).total_seconds() / 60)


def solve_staffing(ctx: PlanningContext, options: list[Option]) -> StaffingSolution:
    solution = solve_cpsat(ctx, options)
    if solution is not None:
        return solution
    if not ctx.cfg.solver.allow_fallback:
        raise SolverUnavailableError("OR-Tools (CP-SAT) is not installed")
    return solve_greedy(ctx, options)


def staffing_baseline(ctx: PlanningContext, options: list[Option]) -> list[Option]:
    """Manual-style heuristic for comparison: call whoever can be online soonest, offer the
    longest valid shift at their earliest start, add people until the gap closes. Uses the
    same eligibility-checked options as the optimizer (identical safety constraints)."""
    by_physician: dict[str, list[Option]] = {}
    for o in options:
        by_physician.setdefault(o.physician_id, []).append(o)
    order = sorted(
        by_physician.values(),
        key=lambda opts: (min(o.online_at for o in opts), opts[0].physician_id),
    )
    pieces = build_pieces(ctx, options)
    chosen: list[Option] = []

    def remaining(selected: list[Option]) -> int:
        ids = {o.index for o in selected}
        return sum(
            p.seconds * max(0, p.base_deficit - sum(i in ids for i in p.covering)) for p in pieces
        )

    current = remaining(chosen)
    for opts in order:
        if current == 0 or len(chosen) >= ctx.cfg.staffing.max_new_physicians:
            break
        first = min(o.start for o in opts)
        pick = max((o for o in opts if o.start == first), key=lambda o: o.minutes)
        value = remaining([*chosen, pick])
        if value < current:
            chosen.append(pick)
            current = value
    return chosen


def _recommendation(
    ctx: PlanningContext, cand: Candidate, o: Option, hospitals: tuple[str, ...]
) -> ShiftRecommendation:
    tz = ctx.tz_for(hospitals)
    window = proposed_window(o)
    effects: list[HospitalEffect] = []
    for hid in hospitals:
        model = ctx.models[hid]
        before = ctx.base_deficit[hid]
        after = round(model.deficit_physician_minutes([window]), 4)
        effects.append(
            HospitalEffect(
                hospital_id=hid,
                hospital_name=model.hospital.name,
                deficit_physician_minutes_before=before,
                deficit_physician_minutes_after=after,
                reduction=round(before - after, 4),
                horizon_minutes=ctx.horizon_minutes,
            )
        )
        dash = ctx.analysis.coverage_models.get(hid)
        if dash is not None:
            b = round(dash.deficit_physician_minutes(), 4)
            a = round(dash.deficit_physician_minutes([window]), 4)
            effects.append(
                HospitalEffect(
                    hospital_id=hid,
                    hospital_name=model.hospital.name,
                    deficit_physician_minutes_before=b,
                    deficit_physician_minutes_after=a,
                    reduction=round(b - a, 4),
                    horizon_minutes=ctx.analysis.coverage.horizon_minutes,
                )
            )
    planning = [e for e in effects if e.horizon_minutes == ctx.horizon_minutes]
    reduction = round(sum(e.reduction for e in planning), 4)
    excess = round(max(0.0, _covered_minutes(ctx, o) * len(hospitals) - reduction), 4)
    protection = protection_for(o, ctx, sorted(cand.state.credentialed_hospital_ids))
    checks = offer_checks(
        cand.state,
        cand.profile,
        o.start,
        o.minutes,
        o.hospitals,
        ctx,
        cand.online_minutes,
        cand.eligibility.online_time_assumed,
    )
    names = [ctx.hospital_name(h) for h in hospitals]
    explanation = [
        f"Offer {o.name} {fmt_local(o.start, tz)}–{fmt_local(o.end, tz)} ({o.minutes} min) "
        f"for {', '.join(names)}; modeled online at {fmt_local(o.online_at, tz)} "
        f"({cand.online_minutes} min to come online counts against the offer).",
        *(
            f"{e.hospital_name}: deficit {e.deficit_physician_minutes_before:g} → "
            f"{e.deficit_physician_minutes_after:g} physician-minutes over the next "
            f"{e.horizon_minutes} min (this offer alone, modeled)."
            for e in planning
        ),
        "Passes every split-shift rule at this start: "
        + "; ".join(f"{c.label.lower()}: {c.value}" for c in checks)
        + ".",
        *protection.rationale,
        "Proposed only — no offer has been sent. Requires clinical-lead approval.",
    ]
    if cand.eligibility.online_time_assumed:
        explanation.insert(1, "Time to come online is missing; an assumed value is used.")
    return ShiftRecommendation(
        physician_id=o.physician_id,
        display_name=o.name,
        offer_start=o.start,
        offer_end=o.end,
        offer_minutes=o.minutes,
        online_at=o.online_at,
        effective_minutes=o.minutes - cand.online_minutes,
        hospital_ids=list(hospitals),
        hospital_names=names,
        effects=effects,
        reduction_physician_minutes=reduction,
        excess_physician_minutes=excess,
        protection=protection,
        explanation=explanation,
    )


def _infeasibility(
    ctx: PlanningContext,
    candidates: list[Candidate],
    after: dict[str, float],
    chosen: list[Option],
) -> list[str]:
    lines: list[str] = []
    for hid in ctx.gap_hospitals:
        if after.get(hid, 0) <= 0:
            continue
        name = ctx.hospital_name(hid)
        eligible_here = [c for c in candidates if c.eligibility.eligible and hid in c.scope]
        credentialed = [c for c in candidates if hid in c.state.credentialed_hospital_ids]
        if not credentialed:
            lines.append(f"{name}: no off-shift physician is credentialed here.")
        elif not eligible_here:
            fails = "; ".join(
                f"{c.state.display_name} ({', '.join(c.eligibility.failed_rules)})"
                for c in credentialed
            )
            lines.append(f"{name}: every credentialed off-shift physician fails a rule — {fails}.")
        else:
            first = min(
                c.earliest_start + timedelta(minutes=c.online_minutes)
                for c in eligible_here
                if c.earliest_start
            )
            lines.append(
                f"{name}: {after[hid]:g} physician-minutes remain — the earliest eligible "
                f"physician can be online at {fmt_local(first, ctx.tz_for([hid]))}, or offers "
                "are limited by length, hours or the next scheduled shift."
            )
    if len(chosen) >= ctx.cfg.staffing.max_new_physicians and any(v > 0 for v in after.values()):
        lines.append(
            f"The plan is capped at {ctx.cfg.staffing.max_new_physicians} new physicians "
            "(configurable)."
        )
    return lines


def run_staffing(
    analysis: OperationalAnalysis,
    cfg: OptimizationConfig,
    offer_log: Mapping[str, tuple[int, int]] | None = None,
) -> tuple[StaffingResult, StaffingInternals]:
    """``offer_log``: physician_id -> (open offers or committed split shifts, offers sent
    in the rolling 7 days), from the Phase 5 workflow tables."""
    ctx = build_planning_context(analysis, cfg)
    ctx.offer_log = dict(offer_log or {})
    candidates = evaluate_candidates(ctx)
    options = generate_options(candidates, ctx)
    solution = solve_staffing(ctx, options)
    chosen = sorted(solution.chosen, key=lambda o: (o.online_at, o.physician_id))
    after, excess = evaluate_plan(ctx, chosen, solution.assigned_hospitals)
    by_id = {c.physician_id: c for c in candidates}
    recommendations = [
        _recommendation(ctx, by_id[o.physician_id], o, solution.assigned_hospitals[o.index])
        for o in chosen
    ]
    chosen_by_physician = {o.physician_id: o for o in chosen}
    rows = []
    for c in candidates:
        row = c.eligibility
        o = chosen_by_physician.get(c.physician_id)
        if o is not None:
            row = row.model_copy(
                update={
                    "proposed_start": o.start,
                    "proposed_minutes": o.minutes,
                    "summary": row.summary + " Recommended in the optimal plan.",
                }
            )
        elif row.eligible:
            row = row.model_copy(
                update={"summary": row.summary + " Not needed in the optimal plan."}
            )
        rows.append(row)

    before_total = round(sum(ctx.base_deficit.values()), 4)
    after_total = round(sum(after.values()), 4)
    notes = list(solution.notes)
    if solution.deficit_seconds is not None and not solution.fallback_used:
        model_value = solution.deficit_seconds / 60
        if abs(model_value - after_total) > 0.01:
            notes.append(
                f"Check: CP-SAT deficit {model_value:g} differs from the coverage engine "
                f"{after_total:g}; the coverage engine figure is reported."
            )
        else:
            notes.append("Check passed: CP-SAT deficit equals the Phase 3 coverage engine result.")
    run = SolverRun(
        optimizer="staffing",
        solver=solution.solver,
        status=solution.status,
        proven_optimal=solution.proven_optimal,
        fallback_used=solution.fallback_used,
        wall_time_ms=solution.wall_time_ms,
        objective=solution.deficit_seconds,
        best_bound=solution.best_bound,
        time_limit_seconds=cfg.solver.staffing_time_limit_seconds,
        stages=solution.stages,
        notes=notes,
    )
    explanations: list[str] = []
    if not ctx.gap_hospitals:
        explanations.append(
            f"No hospital has a coverage gap in the next {ctx.horizon_minutes} min; no split "
            "shift is needed."
        )
    else:
        explanations.append(
            f"Gaps in the next {ctx.horizon_minutes} min at "
            f"{', '.join(ctx.hospital_name(h) for h in ctx.gap_hospitals)}: "
            f"{before_total:g} deficit physician-minutes (modeled)."
        )
        eligible = [c for c in candidates if c.eligibility.eligible]
        explanations.append(
            f"{len(candidates)} off-shift physicians considered; {len(eligible)} eligible"
            + (f" ({', '.join(c.state.display_name for c in eligible)})." if eligible else ".")
        )
        if recommendations:
            explanations.append(
                f"Recommended plan reduces the deficit to {after_total:g} physician-minutes "
                f"with {len(recommendations)} offer(s) (projected if accepted)."
            )
        elif solution.status == "INFEASIBLE":
            explanations.append("No combination of eligible offers satisfies the requirements.")
        else:
            explanations.append("No eligible offer reduces the deficit.")
    assumptions = [
        f"Planning window {ctx.horizon_minutes} min (offers last ≥ 2 h), computed with the same "
        "Phase 3 coverage engine as the dashboard.",
        "A proposed physician counts at each hospital in their routing scope (non-exclusive, "
        "as the brief defines coverage)"
        if cfg.staffing.count_at_all_scope_hospitals
        else "Each proposed physician counts at exactly one hospital (exclusive mode).",
        "Trailing 7-day hours are not reduced for work that may age out before the offer ends "
        "(conservative).",
        "Missing opt-in, rest, hours or schedule data fails the rule.",
        "Offer lengths considered: "
        f"{', '.join(str(m) for m in cfg.staffing.duration_options_minutes)} min, plus exactly "
        "up to the next scheduled shift when shorter.",
    ]
    trap = None
    if recommendations:
        top = chosen[0]
        trap = trap_analysis(ctx, top, recommendations[0].protection)
    result = StaffingResult(
        as_of=ctx.as_of,
        data_version=analysis.state.data_version,
        policy_version=cfg.policy_version,
        planning_horizon_end=ctx.plan_end,
        solver=run,
        gap_hospital_ids=ctx.gap_hospitals,
        candidates=rows,
        recommendations=recommendations,
        totals=StaffingTotals(
            planning_horizon_minutes=ctx.horizon_minutes,
            deficit_physician_minutes_before=before_total,
            deficit_physician_minutes_after=after_total,
            reduction=round(before_total - after_total, 4),
            physicians_used=len(chosen),
            offered_minutes=sum(o.minutes for o in chosen),
            excess_physician_minutes=excess,
            fully_covered=after_total == 0,
        ),
        trap=trap,
        infeasibility=_infeasibility(ctx, candidates, after, chosen),
        rules=RULES_TEXT,
        assumptions=assumptions,
        explanations=explanations,
    )
    return result, StaffingInternals(ctx, candidates, options, solution)


def describe_option(
    ctx: PlanningContext, cand: Candidate, option: Option, hospitals: tuple[str, ...]
) -> ShiftRecommendation:
    """Effects, trap protection and explanation for one concrete offer option (used by the
    Phase 5 workflow for coordinator-selected or backup physicians)."""
    return _recommendation(ctx, cand, option, hospitals)


__all__ = [
    "Candidate",
    "describe_option",
    "protection_for",
    "trap_analysis",
    "Option",
    "PlanningContext",
    "StaffingInternals",
    "build_planning_context",
    "evaluate_candidate",
    "evaluate_candidates",
    "evaluate_plan",
    "generate_options",
    "offer_checks",
    "proposed_window",
    "run_staffing",
    "solve_staffing",
    "staffing_baseline",
]
