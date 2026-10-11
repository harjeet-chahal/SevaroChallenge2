"""Solve the dispatch problem: OR-Tools min-cost flow, a labelled fallback, and the
least-loaded baseline that models the brief's routing rules 3-5.

Network (all capacities 1 unless noted):

    source --(supply = #consults)--> consult --edge cost--> physician --k-th unit--> sink
                                       \\------ unassigned penalty U(c) ------------> sink

Every consult has an explicit "unassigned" arc, so the flow is always feasible and an
unassignable consult is reported, never forced onto an ineligible physician (ineligible
pairs have no arc at all).

Lexicographic costs (implementation choice), with n consults and W the largest edge cost:

    S      = n·W + 1                              one waiting minute outweighs all edge costs
    U(c)   = T[tier(c)] + (wait(c) + 1)·S         unassigned penalty (> W, so assigning wins)
    T[0]   = 0,  T[k+1] = n·(T[k] + (cap+1)·S + W) + 1

so leaving one consult of a higher urgency tier unassigned is never traded for any number
of lower-tier assignments, and within a tier the longer-waiting consult wins contention.
Workload/fairness edge costs then pick *who* takes each consult. A final tie-break term
(scaled below one unit) prefers whoever answered longest ago (brief rule 4; the recency
cost only spans the last 50 minutes), then the lower physician id, so ties are stable.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime

from app.engines.optimization.routing.problem import DispatchProblem
from app.engines.optimization.solvers import load_min_cost_flow
from app.schemas.dispatch import SolverRun

MAX_SAFE_COST = 2**62
FLOW_COST_LIMIT = 2**60
"""OR-Tools min-cost flow refuses (BAD_COST_RANGE) once max arc cost × node count passes
about 3.7e18 (measured); 2**60 keeps a margin."""
WAIT_BUCKETS = (1, 5, 15, 60, 10**9)


@dataclass
class Penalties:
    unassigned: dict[str, int]
    wait_bucket_minutes: int
    scale: int
    exact: bool = True
    """False when the problem is too large for exact lexicographic costs in int64: a
    higher-tier consult then still beats a lower-tier one one-for-one, not any number."""


def penalties(problem: DispatchProblem) -> Penalties:
    """Unassigned penalties U(c), coarsening waiting time only if int64 would overflow, and
    falling back to approximate (still tier-ordered) penalties for very large problems."""
    consults = problem.consults
    n = max(1, len(consults))
    w = problem.max_edge_cost
    tiers = sorted({c.tier for c in consults})
    rank = {t: i for i, t in enumerate(tiers)}
    cap = problem.config.weights.wait_cap_minutes
    k_scale = n * max(1, len(problem.physicians)) + 1
    # OR-Tools scales arc costs by the node count internally, and the objective sums n terms.
    nodes = n + len(problem.physicians) + 2

    def fits(u: dict[str, int]) -> bool:
        if not u:
            return True
        top = max(u.values()) * k_scale
        return top * (nodes + 1) < FLOW_COST_LIMIT and top * n < MAX_SAFE_COST

    for bucket in WAIT_BUCKETS:
        s = n * w + 1
        wmax = cap // bucket
        bases = [0]
        for _ in tiers[1:]:
            bases.append(n * (bases[-1] + (wmax + 1) * s + w) + 1)
        u = {c.consult_id: bases[rank[c.tier]] + (c.wait_key // bucket + 1) * s for c in consults}
        if fits(u):
            return Penalties(u, bucket, s)
    s = w + 1
    wmax = cap
    bases = [0]
    for _ in tiers[1:]:
        bases.append(bases[-1] + (wmax + 1) * s + w + 1)
    u = {c.consult_id: bases[rank[c.tier]] + (c.wait_key + 1) * s for c in consults}
    return Penalties(u, 1, s, exact=False)


def objective(problem: DispatchProblem, pairs: dict[str, str], pen: Penalties) -> int:
    """Same cost function for every method: edge costs + unassigned penalties + fairness."""
    total = 0
    per_physician: dict[str, int] = {}
    for c in problem.consults:
        pid = pairs.get(c.consult_id)
        if pid is None:
            total += pen.unassigned[c.consult_id]
        else:
            total += problem.edges[(c.consult_id, pid)].cost
            k = per_physician.get(pid, 0)
            total += k * problem.config.weights.per_additional_sync_consult
            per_physician[pid] = k + 1
    return total


def _capacity(problem: DispatchProblem) -> int:
    return problem.config.routing.sync_capacity


def solve_min_cost_flow(problem: DispatchProblem) -> tuple[dict[str, str], SolverRun] | None:
    """Exact min-cost flow. Returns None if OR-Tools is not installed."""
    module = load_min_cost_flow()
    if module is None:
        return None
    started = time.perf_counter()
    pen = penalties(problem)
    consults = problem.consults
    n = len(consults)
    if n == 0:
        return {}, SolverRun(
            optimizer="dispatch",
            solver="ortools.SimpleMinCostFlow",
            status="OPTIMAL",
            proven_optimal=True,
            wall_time_ms=0.0,
            objective=0,
            notes=["No consult needs dispatch at this time."],
        )
    physicians = sorted({pid for (_, pid) in problem.edges})
    p_rank = {pid: i for i, pid in enumerate(sorted(physicians, key=problem.recency_key))}
    k_scale = n * max(0, len(physicians) - 1) + 1
    fair = problem.config.weights.per_additional_sync_consult
    flow = module.SimpleMinCostFlow()
    source, sink = 0, 1
    c_node = {c.consult_id: 2 + i for i, c in enumerate(consults)}
    p_node = {pid: 2 + n + i for i, pid in enumerate(physicians)}
    arcs: dict[int, tuple[str, str]] = {}
    for c in consults:
        flow.add_arc_with_capacity_and_unit_cost(source, c_node[c.consult_id], 1, 0)
        flow.add_arc_with_capacity_and_unit_cost(
            c_node[c.consult_id], sink, 1, k_scale * pen.unassigned[c.consult_id]
        )
    for (cid, pid), edge in sorted(problem.edges.items()):
        arc = flow.add_arc_with_capacity_and_unit_cost(
            c_node[cid], p_node[pid], 1, k_scale * edge.cost + p_rank[pid]
        )
        arcs[arc] = (cid, pid)
    for pid in physicians:
        for k in range(_capacity(problem)):
            flow.add_arc_with_capacity_and_unit_cost(p_node[pid], sink, 1, k_scale * fair * k)
    flow.set_node_supply(source, n)
    flow.set_node_supply(sink, -n)
    status = flow.solve()
    elapsed = (time.perf_counter() - started) * 1000
    if status != flow.OPTIMAL:
        names = {
            getattr(flow, k): k
            for k in ("NOT_SOLVED", "INFEASIBLE", "UNBALANCED", "BAD_RESULT", "BAD_COST_RANGE")
            if hasattr(flow, k)
        }
        raise RuntimeError(f"min-cost flow failed: {names.get(status, status)}")
    pairs = {arcs[a][0]: arcs[a][1] for a in arcs if flow.flow(a) > 0}
    notes = (
        [f"Exact optimum of the lexicographic cost (scaled objective {flow.optimal_cost()})."]
        if pen.exact
        else [
            f"{n} consults is too many for exact lexicographic costs: approximate priorities "
            "were used (a more urgent consult still beats a less urgent one, one for one)."
        ]
    )
    if pen.wait_bucket_minutes > 1:
        notes.append(f"Waiting time bucketed to {pen.wait_bucket_minutes} min to fit int64.")
    return pairs, SolverRun(
        optimizer="dispatch",
        solver="ortools.SimpleMinCostFlow",
        status="OPTIMAL",
        proven_optimal=True,
        wall_time_ms=round(elapsed, 3),
        objective=objective(problem, pairs, pen),
        notes=notes,
    )


def solve_greedy(problem: DispatchProblem) -> tuple[dict[str, str], SolverRun]:
    """Labelled fallback when OR-Tools is unavailable: urgency order, cheapest eligible edge.
    Same hard constraints (only existing edges); optimality is NOT claimed."""
    started = time.perf_counter()
    pen = penalties(problem)
    left = {pid: _capacity(problem) for (_, pid) in problem.edges}
    pairs: dict[str, str] = {}
    for c in sorted(problem.consults, key=lambda c: (-c.tier, -c.wait_key, c.consult_id)):
        for edge in problem.edges_for(c.consult_id):
            if left.get(edge.physician_id, 0) > 0:
                pairs[c.consult_id] = edge.physician_id
                left[edge.physician_id] -= 1
                break
    return pairs, SolverRun(
        optimizer="dispatch",
        solver="fallback_greedy",
        status="FALLBACK",
        proven_optimal=False,
        fallback_used=True,
        wall_time_ms=round((time.perf_counter() - started) * 1000, 3),
        objective=objective(problem, pairs, pen),
        notes=["OR-Tools unavailable: greedy heuristic used. Hard constraints still enforced."],
    )


def solve_baseline(problem: DispatchProblem) -> dict[str, str]:
    """The brief's routing rules applied one consult at a time in arrival order.

    Rule 3: low-volume physicians first. Rule 4: fewest consults this shift; ties to whoever
    answered least recently (approximated by the earliest last-call end; never = first),
    then physician id. Rule 5: no eligible physician -> unassigned (routing failure).
    Hard constraints are identical to the optimizer's (the same edge set).
    """
    counts = {pid: v.consults_this_shift for pid, v in problem.physicians.items()}
    left = {pid: _capacity(problem) for pid in problem.physicians}
    never = datetime.min.replace(tzinfo=UTC)
    pairs: dict[str, str] = {}
    for c in sorted(problem.consults, key=lambda c: c.queue_key):
        open_edges = [e for e in problem.edges_for(c.consult_id) if left[e.physician_id]]
        # Overflow (outside a split-shift scope) only when no regular option is left.
        options = [e.physician_id for e in open_edges if not e.overflow] or [
            e.physician_id for e in open_edges
        ]
        if not options:
            continue

        def key(pid: str) -> tuple:
            v = problem.physicians[pid]
            return (
                counts[pid] > v.threshold,
                counts[pid],
                v.last_call_ended_at or never,
                pid,
            )

        chosen = min(options, key=key)
        pairs[c.consult_id] = chosen
        counts[chosen] += 1
        left[chosen] -= 1
    return pairs
