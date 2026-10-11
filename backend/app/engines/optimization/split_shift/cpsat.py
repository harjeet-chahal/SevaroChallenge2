"""Split-shift staffing with OR-Tools CP-SAT: lexicographic objectives over finite options.

Variables: x[o] = 1 if option o (physician, start, length) is proposed.

Constraints:
  at most one option per physician; at most ``max_new_physicians`` options in total;
  for every hospital h and elementary time piece t (cut at every scheduled change point and
  every option's online/end time, so coverage is constant on each piece):
      y[h,t] = sum of x[o] for options covering (h, t)
      d[h,t] >= base_deficit[h,t] - y[h,t],  0 <= d[h,t] <= base_deficit[h,t]
  optional: sum d == 0 (require_full_coverage) — may be INFEASIBLE, reported as such.
  exclusive mode: each chosen option counts at exactly one of its hospitals.

Objectives, solved in order, each stage fixing the previous optimum (implementation choice):
  1. remaining deficit physician-seconds  (primary, the brief's gap measure)
  2. physicians used
  3. excess coverage (coverage added beyond the deficit)
  4. offered minutes
  5. lateness (minutes from now to offer start)
  6. stable tie-break (option rank: physician id, start, length)

Only options that already passed every eligibility rule exist, so no stage can trade a
safety rule for coverage.

Voluntary availability (``VoluntaryConstraint``): after the plan above (the *reference*),
a second solve keeps the reference's number of physicians and keeps each hospital's
deficit within a tolerance of the reference, then:
  1. maximizes the deficit physician-seconds covered by voluntary options (offers inside a
     window the physician volunteered), then the usual stages from deficit onwards.
The reference is itself feasible, so this solve is always feasible when the reference is.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.engines.optimization.solvers import load_cp_model
from app.engines.optimization.split_shift.candidates import Option, PlanningContext

STAGES = ("deficit", "physicians", "excess", "offered_minutes", "lateness", "tie_break")
VOLUNTARY_STAGES = ("voluntary", "deficit", "excess", "offered_minutes", "lateness", "tie_break")


@dataclass(frozen=True)
class VoluntaryConstraint:
    """Re-solve around a reference plan so volunteers can replace, never add or drop."""

    option_indices: frozenset[int]
    """Options whose whole offer lies inside the physician's volunteered window."""
    physicians: int
    """Exactly as many physicians as the reference plan contacts."""
    max_deficit_seconds: dict[str, int]
    """Per hospital: the reference deficit plus the allowed tolerance (physician-seconds)."""


@dataclass
class Piece:
    hospital_id: str
    start: object
    end: object
    seconds: int
    base_deficit: int
    covering: list[int]


@dataclass
class StaffingSolution:
    chosen: list[Option]
    assigned_hospitals: dict[int, tuple[str, ...]]
    status: str
    proven_optimal: bool
    stages: list[dict] = field(default_factory=list)
    wall_time_ms: float = 0.0
    deficit_seconds: int | None = None
    best_bound: int | None = None
    solver: str = "ortools.CpSolver"
    fallback_used: bool = False
    notes: list[str] = field(default_factory=list)


def build_pieces(ctx: PlanningContext, options: list[Option]) -> list[Piece]:
    pieces: list[Piece] = []
    for hid in sorted(ctx.models):
        model = ctx.models[hid]
        relevant = [o for o in options if hid in o.hospitals]
        cuts = [t for o in relevant for t in (o.online_at, o.end)]
        for a, b, deficit in model.deficit_profile(cuts):
            covering = [o.index for o in relevant if o.online_at <= a and b <= o.end]
            if deficit == 0 and not covering:
                continue
            pieces.append(Piece(hid, a, b, round((b - a).total_seconds()), deficit, covering))
    return pieces


def _rank(options: list[Option]) -> dict[int, int]:
    ordered = sorted(options, key=lambda o: (o.physician_id, o.start, o.minutes))
    return {o.index: i for i, o in enumerate(ordered)}


def solve_cpsat(
    ctx: PlanningContext, options: list[Option], voluntary: VoluntaryConstraint | None = None
) -> StaffingSolution | None:
    cp_model = load_cp_model()
    if cp_model is None:
        return None
    started = time.perf_counter()
    st, limits = ctx.cfg.staffing, ctx.cfg.solver
    pieces = build_pieces(ctx, options)
    m = cp_model.CpModel()
    x = {o.index: m.new_bool_var(f"x_{o.index}") for o in options}
    by_physician: dict[str, list[int]] = {}
    for o in options:
        by_physician.setdefault(o.physician_id, []).append(o.index)
    for idxs in by_physician.values():
        m.add_at_most_one(x[i] for i in idxs)
    if x:
        m.add(sum(x.values()) <= st.max_new_physicians)

    # z[o, h]: option o counts at hospital h (non-exclusive: z == x for all its hospitals).
    z: dict[tuple[int, str], object] = {}
    for o in options:
        if st.count_at_all_scope_hospitals or len(o.hospitals) == 1:
            for h in o.hospitals:
                z[(o.index, h)] = x[o.index]
        else:
            vars_ = []
            for h in o.hospitals:
                v = m.new_bool_var(f"z_{o.index}_{h}")
                z[(o.index, h)] = v
                vars_.append(v)
            m.add(sum(vars_) == x[o.index])

    deficit_terms, excess_terms, required_terms, voluntary_terms = [], [], [], []
    by_hospital: dict[str, list] = {}
    gap_hospitals = set(ctx.gap_hospitals)
    for k, piece in enumerate(pieces):
        y = sum(z[(i, piece.hospital_id)] for i in piece.covering)
        d = m.new_int_var(0, piece.base_deficit, f"d_{k}")
        if piece.covering:
            m.add(d >= piece.base_deficit - y)
            excess_terms.append(piece.seconds * (y - piece.base_deficit + d))
        else:
            m.add(d == piece.base_deficit)
        deficit_terms.append(piece.seconds * d)
        by_hospital.setdefault(piece.hospital_id, []).append(piece.seconds * d)
        if piece.hospital_id in gap_hospitals:
            required_terms.append(piece.seconds * d)
        if voluntary is not None and piece.base_deficit > 0:
            mine = [i for i in piece.covering if i in voluntary.option_indices]
            if mine:
                # Deficit covered by volunteers here: at most the deficit, at most their count.
                v = m.new_int_var(0, piece.base_deficit, f"v_{k}")
                m.add(v <= sum(z[(i, piece.hospital_id)] for i in mine))
                voluntary_terms.append(piece.seconds * v)
    if voluntary is not None:
        if x:
            m.add(sum(x.values()) == voluntary.physicians)
        for hid, limit in voluntary.max_deficit_seconds.items():
            if by_hospital.get(hid):
                m.add(sum(by_hospital[hid]) <= limit)
    deficit_expr = sum(deficit_terms) if deficit_terms else 0
    if st.require_full_coverage and required_terms:
        # Only the hospitals short within the look-ahead must be fully covered; later gaps
        # are not acted on yet, so they cannot make the plan infeasible.
        m.add(sum(required_terms) == 0)

    rank = _rank(options)
    objectives = {
        "voluntary": -sum(voluntary_terms) if voluntary_terms else 0,
        "deficit": deficit_expr,
        "physicians": sum(x.values()) if x else 0,
        "excess": sum(excess_terms) if excess_terms else 0,
        "offered_minutes": sum(o.minutes * x[o.index] for o in options) if options else 0,
        "lateness": sum(
            int((o.start - ctx.as_of).total_seconds() // 60) * x[o.index] for o in options
        )
        if options
        else 0,
        "tie_break": sum(rank[o.index] * x[o.index] for o in options) if options else 0,
    }

    solver = cp_model.CpSolver()
    solver.parameters.num_workers = limits.num_workers
    solver.parameters.random_seed = limits.random_seed
    stage_names = VOLUNTARY_STAGES if voluntary is not None else STAGES
    per_stage = limits.staffing_time_limit_seconds / len(stage_names)
    solver.parameters.max_time_in_seconds = per_stage
    solver.parameters.max_deterministic_time = limits.staffing_deterministic_time / len(stage_names)

    stages: list[dict] = []
    status_name = "OPTIMAL"
    proven = True
    best_bound = None
    deficit_value = None
    values: dict[int, int] | None = None
    for name in stage_names:
        expr = objectives[name]
        m.minimize(expr)
        if values is not None:
            m.clear_hints()
            for i, v in values.items():
                m.add_hint(x[i], v)
        code = solver.solve(m)
        stage_status = solver.status_name(code)
        record = {
            "name": name,
            "status": stage_status,
            "objective": None,
            "wall_time_ms": round(solver.wall_time * 1000, 3),
        }
        if code in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            value = round(solver.objective_value)
            record["objective"] = value
            values = {i: int(solver.value(var)) for i, var in x.items()}
            if name == "deficit":
                deficit_value = value
                best_bound = round(solver.best_objective_bound)
            if code == cp_model.FEASIBLE:
                proven = False
                status_name = "FEASIBLE"
                m.add(expr <= value)
            else:
                m.add(expr == value)
            stages.append(record)
            continue
        stages.append(record)
        if name == stage_names[0]:
            status_name = stage_status if stage_status != "UNKNOWN" else "UNKNOWN"
            proven = False
            values = None
        else:
            proven = False
            status_name = "FEASIBLE" if values is not None else stage_status
        break

    chosen = [o for o in options if values and values.get(o.index)]
    assigned: dict[int, tuple[str, ...]] = {}
    for o in chosen:
        if st.count_at_all_scope_hospitals or len(o.hospitals) == 1:
            assigned[o.index] = o.hospitals
        else:
            assigned[o.index] = tuple(h for h in o.hospitals if solver.value(z[(o.index, h)]))
    notes = [f"{len(options)} eligible offer options, {len(pieces)} hospital-time pieces."]
    if voluntary is not None:
        notes = [
            f"Voluntary re-solve: {len(voluntary.option_indices)} offer option(s) inside a "
            f"volunteered window; {voluntary.physicians} physician(s), each hospital's deficit "
            "within the tolerance of the reference plan."
        ]
    if status_name == "INFEASIBLE" and st.require_full_coverage:
        notes.append(
            "Full coverage was required and no combination of eligible offers achieves it."
        )
    return StaffingSolution(
        chosen=chosen,
        assigned_hospitals=assigned,
        status=status_name,
        proven_optimal=proven and status_name == "OPTIMAL",
        stages=stages,
        wall_time_ms=round((time.perf_counter() - started) * 1000, 3),
        deficit_seconds=deficit_value,
        best_bound=best_bound,
        notes=notes,
    )


def solve_greedy(ctx: PlanningContext, options: list[Option]) -> StaffingSolution:
    """Labelled fallback (no OR-Tools): repeatedly add the option with the largest deficit
    reduction (ties: fewer minutes, earlier start, physician id). Not proven optimal."""
    started = time.perf_counter()
    st = ctx.cfg.staffing
    pieces = build_pieces(ctx, options)
    chosen: list[Option] = []
    used: set[str] = set()

    def remaining(selected: list[Option]) -> int:
        ids = {o.index for o in selected}
        return sum(
            p.seconds * max(0, p.base_deficit - sum(1 for i in p.covering if i in ids))
            for p in pieces
        )

    current = remaining(chosen)
    while len(chosen) < st.max_new_physicians:
        best = None
        for o in options:
            if o.physician_id in used:
                continue
            value = remaining([*chosen, o])
            key = (value, o.minutes, o.start, o.physician_id)
            if value < current and (best is None or key < best[0]):
                best = (key, o)
        if best is None:
            break
        chosen.append(best[1])
        used.add(best[1].physician_id)
        current = best[0][0]
    return StaffingSolution(
        chosen=chosen,
        assigned_hospitals={o.index: o.hospitals for o in chosen},
        status="FALLBACK",
        proven_optimal=False,
        wall_time_ms=round((time.perf_counter() - started) * 1000, 3),
        deficit_seconds=current,
        solver="fallback_greedy",
        fallback_used=True,
        notes=["OR-Tools CP-SAT unavailable: greedy heuristic used. Eligibility still enforced."],
    )


def solve_greedy_voluntary(
    ctx: PlanningContext,
    options: list[Option],
    reference: StaffingSolution,
    voluntary: VoluntaryConstraint,
) -> StaffingSolution:
    """Labelled fallback for the voluntary re-solve (no OR-Tools): swap reference offers for
    voluntary ones one at a time, keeping every hospital within its deficit limit, while the
    deficit covered by volunteers grows. Never adds or drops a physician."""
    started = time.perf_counter()
    pieces = build_pieces(ctx, options)

    def per_hospital(selected: list[Option]) -> dict[str, int]:
        ids = {o.index for o in selected}
        out: dict[str, int] = {}
        for p in pieces:
            left = max(0, p.base_deficit - sum(i in ids for i in p.covering))
            out[p.hospital_id] = out.get(p.hospital_id, 0) + p.seconds * left
        return out

    def volunteer_cover(selected: list[Option]) -> int:
        ids = {o.index for o in selected if o.index in voluntary.option_indices}
        return sum(
            p.seconds * min(p.base_deficit, sum(i in ids for i in p.covering)) for p in pieces
        )

    chosen = list(reference.chosen)
    while True:
        best = None
        for i, old in enumerate(chosen):
            if old.index in voluntary.option_indices:
                continue
            others = {c.physician_id for j, c in enumerate(chosen) if j != i}
            for o in options:
                if o.index not in voluntary.option_indices or o.physician_id in others:
                    continue
                trial = [*chosen[:i], o, *chosen[i + 1 :]]
                deficits = per_hospital(trial)
                if any(
                    deficits.get(h, 0) > lim for h, lim in voluntary.max_deficit_seconds.items()
                ):
                    continue
                key = (
                    -volunteer_cover(trial),
                    sum(deficits.values()),
                    o.minutes,
                    o.start,
                    o.physician_id,
                )
                if best is None or key < best[0]:
                    best = (key, trial)
        if best is None or volunteer_cover(best[1]) <= volunteer_cover(chosen):
            break
        chosen = best[1]
    return StaffingSolution(
        chosen=chosen,
        assigned_hospitals={o.index: o.hospitals for o in chosen},
        status="FALLBACK",
        proven_optimal=False,
        wall_time_ms=round((time.perf_counter() - started) * 1000, 3),
        deficit_seconds=sum(per_hospital(chosen).values()),
        solver="fallback_greedy",
        fallback_used=True,
        notes=["Voluntary preference applied by greedy swaps (OR-Tools unavailable)."],
    )
