"""Optimizer B — split-shift staffing (OR-Tools CP-SAT). Recommendations only.

    result, internals = run_staffing(analysis, config)

Eligibility first (every off-shift physician, every rule), then finite offer options that
pass every rule, then CP-SAT. The chosen plan is re-scored with the Phase 3 coverage
engine itself, so the reported before/after figures come from the same model as the
dashboard, not from the optimizer's own arithmetic.

Voluntary availability (off-shift portal): the plan above is the *reference*. When an
eligible physician has a valid offer inside a window they volunteered, CP-SAT re-solves
with the same number of physicians and each hospital within ``coverage_tolerance`` of the
reference's deficit reduction, maximizing the gap covered by volunteers (see cpsat.py and
ranking.py). Without volunteers the result is exactly the reference.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta

from app.engines.analysis import OperationalAnalysis
from app.engines.optimization.config import OptimizationConfig
from app.engines.optimization.solvers import SolverUnavailableError
from app.engines.optimization.split_shift.candidates import (
    PROPOSED_REASON,
    AvailabilityWindow,
    Candidate,
    Decline,
    Option,
    PlanningContext,
    build_planning_context,
    evaluate_candidate,
    evaluate_candidates,
    generate_options,
    offer_checks,
    proposed_window,
)
from app.engines.optimization.split_shift.cpsat import (
    StaffingSolution,
    VoluntaryConstraint,
    build_pieces,
    solve_cpsat,
    solve_greedy,
    solve_greedy_voluntary,
)
from app.engines.optimization.split_shift.ranking import (
    cost_estimate,
    money,
    paid_minutes,
    rank_for_need,
    voluntary_match,
)
from app.engines.optimization.split_shift.trap import (
    protection_for,
    seed_count,
    seed_peers,
    trap_analysis,
)
from app.engines.timeline import fmt_local
from app.schemas.dispatch import SolverRun
from app.schemas.staffing import (
    CostComparison,
    HospitalEffect,
    NeedRanking,
    PlanCost,
    ShiftRecommendation,
    StaffingResult,
    StaffingTotals,
    VoluntaryMatch,
    VoluntarySummary,
)

RULES_TEXT = [
    "Opted in to split-shift offers (brief).",
    "Credentialed at one or more hospitals with the gap; elsewhere does not help (brief).",
    "At least 10 hours since the last shift ended, measured at the offered start (brief).",
    "Trailing 7-day hours plus offered hours ≤ 60 (brief).",
    "The offer does not overlap a scheduled shift (brief).",
    "Offers are at least 2 hours; time to come online counts against the offer (brief).",
    "≤ 1 open offer per physician and ≤ 3 offers per week, from the system offer log (brief).",
    "A physician who declined an offer is not asked again for the same hospital until that "
    "offer would have ended (implementation choice).",
]


@dataclass
class StaffingInternals:
    ctx: PlanningContext
    candidates: list[Candidate]
    options: list[Option]
    solution: StaffingSolution
    reference: StaffingSolution | None = None
    """The plan without voluntary availability (None: identical to ``solution``)."""

    @property
    def reference_plan(self) -> list[Option]:
        return (self.reference or self.solution).chosen

    def rank(self, need: list[str]) -> NeedRanking:
        """Ranked physicians for one coverage need (see ranking.py)."""
        return rank_for_need(
            self.ctx, self.candidates, self.options, need, self.solution.chosen, self.reference_plan
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


def voluntary_constraint(
    ctx: PlanningContext, options: list[Option], reference: StaffingSolution
) -> VoluntaryConstraint | None:
    """Limits for the voluntary re-solve, or None when no volunteer can help: no offer lies
    inside a volunteered window and covers a deficit, or the reference contacts nobody."""
    if not ctx.cfg.voluntary.enabled or not reference.chosen:
        return None
    if reference.status not in ("OPTIMAL", "FEASIBLE", "FALLBACK"):
        return None
    ids = frozenset(o.index for o in options if ctx.window_for(o.physician_id, o.start, o.end))
    if not ids:
        return None
    pieces = build_pieces(ctx, options)
    if not any(p.base_deficit > 0 and ids & set(p.covering) for p in pieces):
        return None
    chosen = {o.index for o in reference.chosen}
    base: dict[str, int] = {}
    left: dict[str, int] = {}
    for p in pieces:
        covered = sum(
            1
            for i in p.covering
            if i in chosen and p.hospital_id in reference.assigned_hospitals.get(i, ())
        )
        base[p.hospital_id] = base.get(p.hospital_id, 0) + p.seconds * p.base_deficit
        left[p.hospital_id] = left.get(p.hospital_id, 0) + p.seconds * max(
            0, p.base_deficit - covered
        )
    tol = ctx.cfg.voluntary.coverage_tolerance
    volunteered = {h for o in options if o.index in ids for h in o.hospitals}
    return VoluntaryConstraint(
        option_indices=ids,
        physicians=len(reference.chosen),
        max_deficit_seconds={
            h: left[h] + (int(tol * (base[h] - left[h])) if h in volunteered else 0) for h in base
        },
    )


def solve_with_voluntary(
    ctx: PlanningContext, options: list[Option]
) -> tuple[StaffingSolution, StaffingSolution | None]:
    """(final solution, reference) — the reference is None when voluntary availability
    could not change anything (the final solution *is* the reference)."""
    reference = solve_staffing(ctx, options)
    constraint = voluntary_constraint(ctx, options, reference)
    if constraint is None:
        return reference, None
    if reference.fallback_used:
        second = solve_greedy_voluntary(ctx, options, reference, constraint)
    else:
        second = solve_cpsat(ctx, options, constraint) or solve_greedy_voluntary(
            ctx, options, reference, constraint
        )
    if not second.chosen and reference.chosen:
        return reference, None  # never worse than the reference (defensive)
    combined = StaffingSolution(
        chosen=second.chosen,
        assigned_hospitals=second.assigned_hospitals,
        status=second.status
        if reference.status == "OPTIMAL" or second.status == "FALLBACK"
        else reference.status,
        proven_optimal=reference.proven_optimal and second.proven_optimal,
        stages=[
            *reference.stages,
            *(
                {
                    **st,
                    "name": st["name"] if st["name"] == "voluntary" else f"voluntary:{st['name']}",
                }
                for st in second.stages
            ),
        ],
        wall_time_ms=round(reference.wall_time_ms + second.wall_time_ms, 3),
        deficit_seconds=second.deficit_seconds,
        best_bound=second.best_bound,
        solver=second.solver,
        fallback_used=reference.fallback_used or second.fallback_used,
        notes=[*reference.notes, *second.notes],
    )
    return combined, reference


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
        if dash is not None and ctx.analysis.coverage.horizon_minutes != ctx.horizon_minutes:
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
    match = voluntary_match(ctx, cand, hospitals, option=o)
    if match is not None:
        explanation.insert(1, f"Voluntary availability: {match.message}")
    cost = cost_estimate(ctx.cfg, paid_minutes(ctx.cfg, o.minutes, cand.online_minutes), reduction)
    explanation.insert(
        -1,
        f"Estimated cost {money(ctx.cfg, cost.amount)}: {cost.note}.",
    )
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
        voluntary=match,
        cost=cost,
    )


def _why_not(ctx: PlanningContext, c: Candidate, hid: str) -> str:
    if c.eligibility.failed_rules:
        return ", ".join(c.eligibility.failed_rules)
    if hid in ctx.declined_hospitals(c.physician_id):
        return "declined an offer for this hospital"
    return "eligible only for another short hospital"


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
                f"{c.state.display_name} ({_why_not(ctx, c, hid)})" for c in credentialed
            )
            lines.append(f"{name}: no credentialed off-shift physician can be asked — {fails}.")
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


def _plan_cost(
    ctx: PlanningContext,
    candidates: dict[str, Candidate],
    options: list[Option],
    chosen: list[Option],
    reduction: float,
    reference: StaffingSolution | None,
) -> PlanCost | None:
    """The recommended plan's estimated cost and the same cost model applied to the
    alternatives: the plan without voluntary availability and the manual heuristic."""
    if not chosen:
        return None
    cfg = ctx.cfg

    def paid(opts: list[Option]) -> int:
        return sum(
            paid_minutes(cfg, o.minutes, candidates[o.physician_id].online_minutes) for o in opts
        )

    recommended = cost_estimate(cfg, paid(chosen), reduction)
    before = sum(ctx.base_deficit.values())
    comparisons: list[CostComparison] = []

    def compare(label: str, opts: list[Option], assigned, why: str) -> None:
        after, _ = evaluate_plan(ctx, opts, assigned)
        left = round(sum(after.values()), 4)
        cost = cost_estimate(cfg, paid(opts), round(before - left, 4))
        saving = round(cost.amount - recommended.amount, 2)
        delta = cost.paid_minutes - recommended.paid_minutes
        if saving > 0:
            verdict = f"simulated saving {money(cfg, saving)} ({delta} fewer paid minutes)"
        elif saving < 0:
            verdict = (
                f"the recommendation costs {money(cfg, -saving)} more ({-delta} more paid minutes)"
            )
        else:
            verdict = "same paid time, no simulated saving"
        comparisons.append(
            CostComparison(
                label=label,
                physician_names=[o.name for o in opts],
                cost=cost,
                deficit_after=left,
                saving=saving,
                explanation=f"{why} {money(cfg, cost.amount)} vs {money(cfg, recommended.amount)}: "
                f"{verdict}. Deficit left {left:g} vs "
                f"{round(before - reduction, 4):g} physician-minutes.",
            )
        )

    if reference is not None and {
        (o.physician_id, o.start, o.minutes) for o in reference.chosen
    } != {(o.physician_id, o.start, o.minutes) for o in chosen}:
        compare(
            "Plan without voluntary availability",
            reference.chosen,
            reference.assigned_hospitals,
            "Who the optimizer would ask if nobody had volunteered:",
        )
    baseline = staffing_baseline(ctx, options)
    if baseline:
        compare(
            "Manual heuristic (earliest online, longest valid offer)",
            baseline,
            {o.index: o.hospitals for o in baseline},
            "A coordinator calling whoever is online soonest for the longest valid shift:",
        )
    return PlanCost(
        recommended=recommended,
        comparisons=comparisons,
        assumptions=[
            f"Cost = paid offer minutes × {money(cfg, cfg.cost.hourly_rate)}/h, an illustrative "
            "rate (the dataset has no pay data); the same rate for every physician, so "
            "volunteering never lowers a physician's cost.",
            "The whole offer is paid, including the time to come online."
            if cfg.cost.paid_includes_time_to_online
            else "Only the time after coming online is paid.",
            "All figures are simulated (projected if accepted). A saving is confirmed only from "
            "a completed shift, on the intervention that ran it.",
        ],
    )


def _voluntary_summary(
    ctx: PlanningContext,
    chosen: list[Option],
    reference: StaffingSolution | None,
    rankings: list[NeedRanking],
) -> VoluntarySummary:
    windows = sum(len(ws) for ws in ctx.availability.values())
    tol = ctx.cfg.voluntary.coverage_tolerance
    ref = reference.chosen if reference is not None else chosen
    applied = {(o.physician_id, o.start, o.minutes) for o in ref} != {
        (o.physician_id, o.start, o.minutes) for o in chosen
    }
    lines: list[str] = []
    if not ctx.cfg.voluntary.enabled:
        lines.append("Voluntary availability is switched off in the policy.")
    elif not windows:
        lines.append("No off-shift physician has shared voluntary availability.")
    else:
        lines.append(
            f"{windows} voluntary availability window(s) shared by off-shift physicians. They "
            "count only for offers that pass every split-shift rule and fit inside the window."
        )
        if applied:
            lines.append(
                f"Voluntary availability changed the plan: {', '.join(o.name for o in chosen)} "
                f"instead of {', '.join(o.name for o in ref) or 'nobody'} (same number of "
                f"physicians; each hospital keeps at least {1 - tol:.0%} of the deficit "
                "reduction of the plan without it)."
            )
        else:
            volunteers = {
                e.display_name
                for r in rankings
                for e in r.entries
                if e.voluntary is not None and e.voluntary.status != "applied"
            }
            lines.append(
                "The plan is unchanged"
                + (
                    f": {', '.join(sorted(volunteers))} — see each physician's voluntary status."
                    if volunteers
                    else "."
                )
            )
    return VoluntarySummary(
        active_windows=windows,
        applied=applied,
        coverage_tolerance=tol,
        reference_physicians=[o.name for o in ref],
        explanation=lines,
    )


def run_staffing(
    analysis: OperationalAnalysis,
    cfg: OptimizationConfig,
    offer_log: Mapping[str, tuple[int, int]] | None = None,
    declines: Mapping[str, list[Decline]] | None = None,
    availability: Mapping[str, list[AvailabilityWindow]] | None = None,
) -> tuple[StaffingResult, StaffingInternals]:
    """``offer_log``: physician_id -> (open offers or committed split shifts, offers sent
    in the rolling 7 days); ``declines``: physician_id -> declined offers; ``availability``:
    physician_id -> voluntary availability windows. All from the Phase 5 workflow tables."""
    ctx = build_planning_context(analysis, cfg)
    ctx.offer_log = dict(offer_log or {})
    ctx.declines = {pid: list(rows) for pid, rows in (declines or {}).items()}
    ctx.availability = {
        pid: [w for w in rows if w.end > ctx.as_of] for pid, rows in (availability or {}).items()
    }
    ctx.availability = {pid: rows for pid, rows in ctx.availability.items() if rows}
    candidates = evaluate_candidates(ctx)
    options = generate_options(candidates, ctx)
    solution, reference = solve_with_voluntary(ctx, options)
    chosen = sorted(solution.chosen, key=lambda o: (o.online_at, o.physician_id))
    after, excess = evaluate_plan(ctx, chosen, solution.assigned_hospitals)
    by_id = {c.physician_id: c for c in candidates}
    recommendations = [
        _recommendation(ctx, by_id[o.physician_id], o, solution.assigned_hospitals[o.index])
        for o in chosen
    ]
    chosen_by_physician = {o.physician_id: o for o in chosen}
    internals = StaffingInternals(ctx, candidates, options, solution, reference)
    rankings = [internals.rank([hid]) for hid in ctx.gap_hospitals]
    matches: dict[str, VoluntaryMatch] = {}
    for ranking in rankings:
        for entry in ranking.entries:
            if entry.voluntary is not None and (
                entry.physician_id not in matches or entry.voluntary.status == "applied"
            ):
                matches[entry.physician_id] = entry.voluntary
    rows = []
    for c in candidates:
        row = c.eligibility
        match = matches.get(c.physician_id) or voluntary_match(
            ctx, c, c.scope or c.state.credentialed_hospital_ids, option=None
        )
        if match is not None:
            row = row.model_copy(update={"voluntary": match})
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
            f"No hospital is short in the next {ctx.lookahead_minutes} min; no split shift is "
            "needed now."
        )
    else:
        explanations.append(
            f"Short in the next {ctx.lookahead_minutes} min: "
            f"{', '.join(ctx.hospital_name(h) for h in ctx.gap_hospitals)}. Deficit over the "
            f"{ctx.horizon_minutes}-min planning window, including later gaps: "
            f"{before_total:g} physician-minutes (modeled)."
        )
    for hid, consult_ids in ctx.stranded.items():
        if hid in ctx.gap_hospitals:
            explanations.append(
                f"{ctx.hospital_name(hid)} is short now: {', '.join(consult_ids)} "
                f"{'is' if len(consult_ids) == 1 else 'are'} waiting with no eligible on-shift "
                "physician (every credentialed physician is busy or excluded), so "
                f"{len(consult_ids)} more physician{' is' if len(consult_ids) == 1 else 's are'} "
                "needed there (re-checked as the clock moves)."
            )
    if ctx.later_gaps:
        explanations.append(
            "Gaps that start later in the planning window are not acted on yet (re-checked as "
            "the clock moves): "
            + ", ".join(
                f"{ctx.hospital_name(h)} from {fmt_local(at, ctx.tz_for([h]))}"
                for h, at in ctx.later_gaps.items()
            )
            + "."
        )
    if ctx.gap_hospitals:
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
        voluntary_applied = reference is not None and {
            (o.physician_id, o.start, o.minutes) for o in reference.chosen
        } != {(o.physician_id, o.start, o.minutes) for o in chosen}
        if voluntary_applied:
            volunteers = [o.name for o in chosen if ctx.window_for(o.physician_id, o.start, o.end)]
            explanations.append(
                f"Voluntary availability: {', '.join(volunteers)} "
                f"volunteered for this time and is asked instead of "
                f"{', '.join(o.name for o in reference.chosen)} (coverage within "
                f"{cfg.voluntary.coverage_tolerance:.0%})."
            )
        elif solution.status == "INFEASIBLE":
            explanations.append("No combination of eligible offers satisfies the requirements.")
        else:
            explanations.append("No eligible offer reduces the deficit.")
    assumptions = [
        f"A hospital counts as short only if its gap starts within {ctx.lookahead_minutes} min "
        "(the dashboard's coverage forecast window).",
        f"Offer starts and lengths are planned over {ctx.horizon_minutes} min (offers last "
        "≥ 2 h), computed with the same Phase 3 coverage engine as the dashboard.",
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
        "Voluntary availability is a preference after every rule: a volunteer's offer inside "
        "their window may replace another physician if each hospital keeps at least "
        f"{1 - cfg.voluntary.coverage_tolerance:.0%} of the deficit reduction (same number of "
        "physicians).",
        f"Estimated cost = paid offer minutes × {money(cfg, cfg.cost.hourly_rate)}/h "
        "(illustrative; same rate for every physician).",
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
        rankings=rankings,
        voluntary=_voluntary_summary(ctx, chosen, reference, rankings),
        cost=_plan_cost(
            ctx,
            by_id,
            options,
            chosen,
            round(before_total - after_total, 4),
            reference,
        ),
    )
    return result, internals


def describe_option(
    ctx: PlanningContext, cand: Candidate, option: Option, hospitals: tuple[str, ...]
) -> ShiftRecommendation:
    """Effects, trap protection and explanation for one concrete offer option (used by the
    Phase 5 workflow for coordinator-selected or backup physicians)."""
    return _recommendation(ctx, cand, option, hospitals)


__all__ = [
    "PROPOSED_REASON",
    "AvailabilityWindow",
    "Candidate",
    "Decline",
    "rank_for_need",
    "describe_option",
    "protection_for",
    "seed_count",
    "seed_peers",
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
    "solve_with_voluntary",
    "staffing_baseline",
]
