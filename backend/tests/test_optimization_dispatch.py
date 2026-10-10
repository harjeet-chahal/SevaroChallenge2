"""Optimizer A — consult dispatch (min-cost flow). Hand-solvable scenarios."""

from __future__ import annotations

import itertools
import random

from opt_helpers import NOW, OptScenario, config, dispatch, m, pairs

from app.engines.optimization import OptimizationConfig, build_dispatch_problem
from app.engines.optimization.routing import penalties, solve_baseline, solve_min_cost_flow
from app.engines.optimization.routing.solve import objective


def two_hospitals() -> OptScenario:
    return OptScenario().hospital("H1").hospital("H2")


# 1. Credentialing is a hard constraint -------------------------------------------------


def test_never_routes_to_a_physician_not_credentialed_at_the_hospital():
    s = two_hospitals().doctor("P1", ["H2"]).doctor("P2", ["H1"]).history("P2", "H1", 7)
    s.consult("C1", "H1")
    result, _, problem = dispatch(s)

    assert pairs(result) == {"C1": "P2"}  # P1 is idle and unloaded but not credentialed
    assert ("C1", "P1") not in problem.edges


def test_no_credentialed_physician_on_shift_is_explained():
    s = two_hospitals().doctor("P1", ["H2"])
    s.consult("C1", "H1")
    result, _, _ = dispatch(s)

    (u,) = result.plan.unassigned
    assert u.reason_code == "no_credentialed_on_shift"
    assert "split-shift" in u.explanation[0]


# 2./3. Synchronous calls block dispatch but still count for coverage -------------------


def test_busy_physician_is_not_dispatched_but_still_counts_for_coverage():
    s = (
        two_hospitals()
        .doctor("P1", ["H1"])
        .doctor("P2", ["H1"])
        .requirement("H1", "00:00", "00:00", 2)
    )
    s.history("P2", "H1", 8)
    s.event("incoming_call_started", m(-3), physician_id="P1", consult_id="CX", hospital_id="H1")
    s.consult("C1", "H1")
    result, _, _ = dispatch(s)
    rows = {p.physician_id: p for p in result.physicians}

    assert pairs(result) == {"C1": "P2"}
    assert rows["P1"].eligible_for_dispatch is False
    assert rows["P1"].effective_routing_capacity == 0
    assert rows["P1"].counts_for_coverage is True
    assert rows["P1"].coverage_hospital_ids == ["H1"]


def test_video_and_suspected_external_video_block_dispatch():
    s = two_hospitals().doctor("P1", ["H1"]).doctor("P2", ["H1"])
    s.event("video_started", m(-4), physician_id="P1", consult_id="CX", hospital_id="H1")
    s.event("camera_active", m(-2), physician_id="P2")
    s.consult("C1", "H1")
    result, _, _ = dispatch(s)

    (u,) = result.plan.unassigned
    assert u.reason_code == "no_eligible_physician"
    reasons = {x.physician_id: " ".join(x.reasons) for x in u.excluded}
    assert "video" in reasons["P1"] and "external video" in reasons["P2"]


# 4. Asynchronous open consults do not consume synchronous capacity -------------------


def test_open_notes_do_not_consume_sync_capacity():
    s = two_hospitals().doctor("P1", ["H1"])
    s.open_note("P1", "N1", "H1", call_end=-30).open_note("P1", "N2", "H1", call_end=-20)
    s.consult("C1", "H1")
    result, _, _ = dispatch(s)
    row = next(p for p in result.physicians if p.physician_id == "P1")

    assert pairs(result) == {"C1": "P1"}
    assert row.open_async_consults == 2 and row.effective_routing_capacity == 1
    costs = {c.name: c.value for c in result.plan.recommendations[0].cost_breakdown}
    assert costs["open_consults"] == 2 * OptimizationConfig().weights.per_open_consult


# Rule 2 boundaries: ringing phones and the 2-minute call cool-down --------------------


def test_call_cooldown_is_exactly_two_minutes():
    s = two_hospitals().doctor("P1", ["H1"]).doctor("P2", ["H1"])
    s.history("P1", "H1", 1, last_call_end=-2)  # ended exactly 120 s ago -> eligible
    s.history("P2", "H1", 1, last_call_end=-119 / 60)  # 119 s ago -> excluded
    s.consult("C1", "H1").consult("C2", "H1", received=-7, triaged=-6)
    result, _, problem = dispatch(s)

    assert ("C1", "P1") in problem.edges and ("C1", "P2") not in problem.edges
    assert set(pairs(result).values()) == {"P1"}


def test_ringing_phone_excludes_other_calls_and_keeps_its_own_route():
    s = two_hospitals().doctor("P1", ["H1"]).doctor("P2", ["H1"]).history("P2", "H1", 9)
    s.consult("C1", "H1", "General Neuro").consult(
        "C2", "H1", "General Neuro", received=-4, triaged=-3
    )
    s.event("incoming_call_ringing", m(-0.5), physician_id="P1", consult_id="C2", hospital_id="H1")
    result, _, _ = dispatch(s)
    recs = {r.consult_id: r for r in result.plan.recommendations}

    assert recs["C2"].kind == "confirm_ringing" and recs["C2"].physician_id == "P1"
    assert recs["C1"].physician_id == "P2"  # P1's phone is ringing for C2


# 5. Urgency first, then waiting time --------------------------------------------------


def test_stroke_beats_general_neuro_at_the_same_severity():
    s = two_hospitals().doctor("P1", ["H1"])
    s.consult("GN", "H1", "General Neuro", received=-8, triaged=-7)  # warning, waited longer
    s.consult("ST", "H1", "Stroke", received=-6, triaged=-5)  # warning
    result, _, _ = dispatch(s)

    assert pairs(result) == {"ST": "P1"}
    (u,) = result.plan.unassigned
    assert u.consult_id == "GN" and u.reason_code == "capacity_used_by_higher_priority"
    assert u.competing_consult_ids == ["ST"]


def test_critical_alert_beats_warning_and_longer_wait_breaks_ties():
    s = two_hospitals().doctor("P1", ["H1"])
    s.consult("W", "H1", "Stroke", received=-7, triaged=-6)  # warning stroke (tier 3)
    s.consult("C", "H1", "General Neuro", received=-13, triaged=-12)  # critical GN (tier 4)
    assert pairs(dispatch(s)[0]) == {"C": "P1"}

    s = two_hospitals().doctor("P1", ["H1"])
    s.consult("A", "H1", "Stroke", received=-9, triaged=-6)
    s.consult("B", "H1", "Stroke", received=-7, triaged=-6)
    assert pairs(dispatch(s)[0]) == {"A": "P1"}  # same tier, A has waited longer


# 6. No silent reassignment --------------------------------------------------------------


def test_assigned_consults_are_never_moved_and_unavailable_assignees_are_only_proposed():
    s = two_hospitals().doctor("P1", ["H1"]).doctor("P2", ["H1"]).doctor("P3", ["H1"])
    s.consult("OK", "H1", received=-20, triaged=-19)
    s.event("physician_assigned", m(-18), consult_id="OK", physician_id="P1", hospital_id="H1")
    s.consult("TU", "H1", received=-15, triaged=-14)
    s.event("physician_assigned", m(-13), consult_id="TU", physician_id="P3", hospital_id="H1")
    s.open_note("P3", "NOTE", "H1", call_end=-40)
    s.event("physician_status_changed", m(-5), physician_id="P3", status="Temporarily Unavailable")
    result, _, _ = dispatch(s)
    recs = {r.consult_id: r for r in result.plan.recommendations}
    skipped = {x.consult_id: x.reason for x in result.skipped}

    assert "OK" not in recs and "never reassigned silently" in skipped["OK"]
    assert "notes stay with their author" in skipped["NOTE"]
    tu = recs["TU"]
    assert tu.kind == "reassign" and tu.current_physician_id == "P3" and tu.executed is False
    assert any(c.name == "reassignment_disruption" for c in tu.cost_breakdown)
    assert any("nothing is reassigned automatically" in line for line in tu.explanation)


# 7. Capacity --------------------------------------------------------------------------


def test_sync_capacity_limits_new_consults_per_physician():
    s = two_hospitals().doctor("P1", ["H1"])
    s.consult("A", "H1", received=-9, triaged=-6).consult("B", "H1", received=-7, triaged=-6)
    assert len(dispatch(s)[0].plan.recommendations) == 1

    two = config(routing={"sync_capacity": 2})
    result, _, _ = dispatch(s, two)
    assert pairs(result) == {"A": "P1", "B": "P1"}


# 10. Workload balancing and the brief's low-volume priority ---------------------------


def test_prefers_lower_workload_and_low_volume_physicians():
    s = two_hospitals().doctor("P1", ["H1"]).doctor("P2", ["H1"])
    s.history("P1", "H1", 7, last_call_end=-60).history("P2", "H1", 6, last_call_end=-60)
    s.consult("C1", "H1")
    result, _, problem = dispatch(s)
    w = OptimizationConfig().weights

    assert pairs(result) == {"C1": "P2"}
    assert problem.edges[("C1", "P1")].cost - problem.edges[("C1", "P2")].cost == (
        w.per_consult_this_shift + w.not_low_volume
    )
    assert "rule3 not low volume" in result.plan.recommendations[0].explanation[-2]


def test_night_role_uses_the_night_low_volume_threshold():
    s = two_hospitals().doctor("P1", ["H1"], role="night").history("P1", "H1", 5)
    s.consult("C1", "H1")
    row = dispatch(s)[0].physicians[0]

    assert row.low_volume_threshold == 4 and row.low_volume is False


# 9. Determinism -----------------------------------------------------------------------


def _busy_scenario(events_order_seed: int | None = None) -> OptScenario:
    s = two_hospitals().doctor("P1", ["H1", "H2"]).doctor("P2", ["H1"]).doctor("P3", ["H2"])
    s.history("P1", "H1", 3).history("P2", "H1", 3).history("P3", "H2", 3)
    for i, (hid, kind) in enumerate(
        [("H1", "Stroke"), ("H2", "General Neuro"), ("H1", "General Neuro"), ("H2", "Stroke")]
    ):
        s.consult(f"C{i}", hid, kind, received=-6 - i, triaged=-5 - i)
    if events_order_seed is not None:
        random.Random(events_order_seed).shuffle(s.events)
    return s


def _stable(result) -> dict:
    return result.model_dump(exclude={"solver": {"wall_time_ms"}})


def test_identical_input_gives_identical_recommendations():
    first = _stable(dispatch(_busy_scenario())[0])
    assert _stable(dispatch(_busy_scenario())[0]) == first
    assert _stable(dispatch(_busy_scenario(events_order_seed=7))[0]) == first
    assert first["plan"]["recommendations"]  # a non-trivial plan


# Exactness: min-cost flow equals exhaustive search ------------------------------------


def _brute_force(problem, pen) -> int:
    consults = problem.consults
    choices = [[None] + [e.physician_id for e in problem.edges_for(c.consult_id)] for c in consults]
    best = None
    cap = problem.config.routing.sync_capacity
    for combo in itertools.product(*choices):
        used = [p for p in combo if p is not None]
        if any(used.count(p) > cap for p in set(used)):
            continue
        value = objective(
            problem, {c.consult_id: p for c, p in zip(consults, combo, strict=True) if p}, pen
        )
        best = value if best is None else min(best, value)
    return best


def test_min_cost_flow_matches_exhaustive_search():
    for seed in range(6):
        rng = random.Random(seed)
        s = OptScenario().hospital("H1").hospital("H2").hospital("H3")
        for i in range(4):
            creds = sorted(rng.sample(["H1", "H2", "H3"], rng.randint(1, 3)))
            s.doctor(f"P{i}", creds).history(
                f"P{i}", creds[0], rng.randint(0, 9), last_call_end=-rng.randint(3, 80)
            )
        for j in range(5):
            s.consult(
                f"C{j}",
                rng.choice(["H1", "H2", "H3"]),
                rng.choice(["Stroke", "General Neuro"]),
                received=-rng.randint(2, 15),
                triaged=-1.5,
            )
        problem = build_dispatch_problem(s.analyze(NOW), OptimizationConfig())
        pen = penalties(problem)
        solved, run = solve_min_cost_flow(problem)

        assert run.status == "OPTIMAL" and run.proven_optimal
        assert run.objective == _brute_force(problem, pen), seed
        assert all((c, p) in problem.edges for c, p in solved.items())


# 25. The baseline sees the identical scenario and constraints --------------------------


def test_baseline_uses_the_same_problem_and_hard_constraints():
    s = _busy_scenario()
    result, baseline, problem = dispatch(s)
    base_pairs = solve_baseline(problem)

    assert {r.consult_id for r in baseline.recommendations} | {
        u.consult_id for u in baseline.unassigned
    } == {c.consult_id for c in problem.consults}
    assert all((c, p) in problem.edges for c, p in base_pairs.items())
    assert result.plan.objective_cost <= baseline.objective_cost
