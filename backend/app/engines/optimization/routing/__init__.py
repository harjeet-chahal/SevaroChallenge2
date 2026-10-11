"""Optimizer A — consult dispatch (OR-Tools min-cost flow). Recommendations only."""

from __future__ import annotations

from collections.abc import Mapping

from app.engines.analysis import OperationalAnalysis
from app.engines.optimization.config import OptimizationConfig
from app.engines.optimization.routing.problem import (
    DispatchProblem,
    build_dispatch_problem,
    edge_cost,
)
from app.engines.optimization.routing.render import (
    physician_rows,
    policy_used,
    render_plan,
    skipped_rows,
)
from app.engines.optimization.routing.solve import (
    objective,
    penalties,
    solve_baseline,
    solve_greedy,
    solve_min_cost_flow,
)
from app.engines.optimization.solvers import SolverUnavailableError
from app.schemas.dispatch import DispatchPlan, DispatchResult, SolverRun


def solve_dispatch(
    problem: DispatchProblem,
) -> tuple[dict[str, str], SolverRun, str]:
    try:
        solved = solve_min_cost_flow(problem)
    except RuntimeError as exc:  # e.g. BAD_COST_RANGE on a very large problem
        pairs, run = solve_greedy(problem)
        run.notes.append(f"The exact solver could not run ({exc}); greedy fallback used.")
        return pairs, run, "fallback_greedy"
    if solved is not None:
        pairs, run = solved
        return pairs, run, "min_cost_flow"
    if not problem.config.solver.allow_fallback:
        raise SolverUnavailableError("OR-Tools (min-cost flow) is not installed")
    pairs, run = solve_greedy(problem)
    return pairs, run, "fallback_greedy"


def run_dispatch(
    analysis: OperationalAnalysis,
    cfg: OptimizationConfig,
    *,
    scopes: Mapping[str, frozenset[str]] | None = None,
    seeded_counts: Mapping[str, int] | None = None,
) -> tuple[DispatchResult, DispatchPlan, DispatchProblem]:
    """Optimized plan (as a full result) plus the least-loaded baseline on the same problem."""
    problem = build_dispatch_problem(analysis, cfg, scopes=scopes, seeded_counts=seeded_counts)
    pen = penalties(problem)
    pairs, run, method = solve_dispatch(problem)
    plan = render_plan(problem, pairs, method, pen)
    baseline = render_plan(problem, solve_baseline(problem), "least_loaded_baseline", pen)
    explanations = []
    if not problem.consults:
        explanations.append("No open consult needs routing right now.")
    else:
        explanations.append(
            f"{len(plan.recommendations)} of {len(problem.consults)} consults needing routing "
            f"have a proposed physician; {len(plan.unassigned)} cannot be placed now."
        )
    urgent_left = [u for u in plan.unassigned if u.urgency_tier >= 3]
    if urgent_left:
        explanations.append(
            "Urgent consults without an eligible physician: "
            + ", ".join(u.consult_id for u in urgent_left)
            + ". Escalate and review split-shift coverage."
        )
    result = DispatchResult(
        as_of=analysis.state.as_of,
        data_version=analysis.state.data_version,
        policy_version=cfg.policy_version,
        solver=run,
        plan=plan,
        physicians=physician_rows(problem),
        skipped=skipped_rows(problem),
        policy=policy_used(problem),
        explanations=explanations,
    )
    return result, baseline, problem


__all__ = [
    "DispatchProblem",
    "build_dispatch_problem",
    "edge_cost",
    "objective",
    "penalties",
    "run_dispatch",
    "solve_baseline",
    "solve_dispatch",
    "solve_greedy",
    "solve_min_cost_flow",
]
