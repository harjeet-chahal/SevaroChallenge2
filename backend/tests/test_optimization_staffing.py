"""Optimizer B — split-shift eligibility, CP-SAT staffing, trap policy and what-if previews.

Base scenario (hand-solvable): one hospital H1 needs 1 physician all day; its only
physician's shift ends at +60 min, so over the 240-minute planning window the deficit is
1 physician from +60 to +240 = 180 physician-minutes.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from opt_helpers import NOW, OptScenario, config, m, staffing

from app.engines.optimization import ForecastConfig, OptimizationConfig, simulate_intervention
from app.engines.optimization.split_shift import (
    build_planning_context,
    evaluate_candidates,
    generate_options,
    offer_checks,
)
from app.schemas.whatif import AssignConsultAction, SplitShiftAction

RULES = [
    "opt_in",
    "credentialed_at_gap",
    "off_shift",
    "rest_10h",
    "weekly_hours",
    "no_overlap",
    "min_length",
    "notification_limits",
]


def base() -> OptScenario:
    s = OptScenario().hospital("H1").requirement("H1", "00:00", "00:00", 1)
    return s.doctor("P1", ["H1"], end=m(60))


def ctx_for(s: OptScenario, cfg: OptimizationConfig | None = None):
    ctx = build_planning_context(s.analyze(NOW), cfg or OptimizationConfig())
    return ctx, {c.physician_id: c for c in evaluate_candidates(ctx)}


def checks_at(s: OptScenario, pid: str, start, minutes: int) -> dict[str, bool]:
    ctx, cands = ctx_for(s)
    c = cands[pid]
    result = offer_checks(c.state, c.profile, start, minutes, ("H1",), ctx, c.online_minutes, False)
    return {x.code: x.passed for x in result}


# 18. CP-SAT returns the hand-computed optimum and an accurate status ------------------


def test_cpsat_finds_the_hand_computed_optimum():
    s = base().candidate("G", ["H1"])
    result, internals = staffing(s)
    (rec,) = result.recommendations

    # Cover exactly [+60, +240): start at +60 for 180 min. Starting now wastes 60 min of
    # excess coverage; 240/360-minute offers tie on deficit and excess but offer more hours.
    assert (rec.offer_start, rec.offer_minutes) == (m(60), 180)
    assert result.totals.deficit_physician_minutes_before == 180
    assert result.totals.deficit_physician_minutes_after == 0
    assert result.totals.excess_physician_minutes == 0
    assert result.solver.status == "OPTIMAL" and result.solver.proven_optimal
    assert [st["name"] for st in result.solver.stages] == [
        "deficit",
        "physicians",
        "excess",
        "offered_minutes",
        "lateness",
        "tie_break",
    ]
    assert all(st["status"] == "OPTIMAL" for st in result.solver.stages)
    assert any("Check passed" in n for n in result.solver.notes)
    assert rec.status == "proposed" and rec.requires_approval is True


def test_full_coverage_requirement_reports_infeasible_instead_of_guessing():
    s = base().candidate("G", ["H1"], online=90)  # online at +90 at the earliest
    strict = config(staffing={"require_full_coverage": True})
    result, _ = staffing(s, strict)

    assert result.solver.status == "INFEASIBLE" and not result.solver.proven_optimal
    assert result.recommendations == [] and result.infeasibility

    relaxed, _ = staffing(s)
    assert relaxed.solver.status == "OPTIMAL"
    assert relaxed.totals.deficit_physician_minutes_after == 30  # +60..+90 unfillable


def test_staffing_is_deterministic():
    s = base().candidate("G", ["H1"]).candidate("K", ["H1"], online=5)

    def stable(r):
        return r.model_dump(exclude={"solver": {"wall_time_ms", "stages"}})

    assert stable(staffing(s)[0]) == stable(staffing(s)[0])


# 11.–17. Eligibility rules, boundaries and missing data -------------------------------


def test_every_candidate_is_listed_with_every_rule():
    s = base().candidate("G", ["H1"]).candidate("X", ["H1"], opt_in=False)
    result, _ = staffing(s)

    assert [c.physician_id for c in result.candidates] == ["G", "X"]
    for c in result.candidates:
        assert [x.code for x in c.checks] == RULES
    x = next(c for c in result.candidates if c.physician_id == "X")
    assert x.eligible is False and x.failed_rules == ["opt_in"]


def test_opt_in_must_be_explicitly_true():
    s = base().candidate("NO", ["H1"], opt_in=False).candidate("UNK", ["H1"], opt_in=None)
    rows = {c.physician_id: c for c in staffing(s)[0].candidates}

    assert rows["NO"].failed_rules == ["opt_in"]
    unknown = next(x for x in rows["UNK"].checks if x.code == "opt_in")
    assert unknown.passed is False and unknown.missing_data is True


def test_rest_is_measured_at_the_offered_start_to_the_second():
    exact = base().candidate("G", ["H1"], last_end=m(-600))
    assert checks_at(exact, "G", NOW, 120)["rest_10h"] is True

    short = base().candidate("G", ["H1"], last_end=m(-600) + timedelta(seconds=1))
    assert checks_at(short, "G", NOW, 120)["rest_10h"] is False
    _, cands = ctx_for(short)
    assert cands["G"].eligibility.earliest_valid_start == m(1)  # 10 h reached at +1 s


def test_weekly_hours_include_the_offered_hours():
    assert checks_at(base().candidate("G", ["H1"], hours=58), "G", NOW, 120)["weekly_hours"]
    assert not checks_at(base().candidate("G", ["H1"], hours=58), "G", NOW, 121)["weekly_hours"]

    tight = base().candidate("G", ["H1"], hours=58.5)
    row = staffing(tight)[0].candidates[0]
    assert row.failed_rules == ["weekly_hours"]
    assert row.remaining_weekly_hours == 1.5 and row.max_offer_minutes == 90

    ctx, cands = ctx_for(base().candidate("G", ["H1"], hours=57))
    assert {o.minutes for o in generate_options(list(cands.values()), ctx)} <= {120, 180}


def test_offer_may_end_exactly_when_the_next_shift_starts_but_not_after():
    assert checks_at(base().candidate("G", ["H1"], next_start=m(120)), "G", NOW, 120)["no_overlap"]
    assert not checks_at(base().candidate("G", ["H1"], next_start=m(119)), "G", NOW, 120)[
        "no_overlap"
    ]
    ctx, cands = ctx_for(base().candidate("G", ["H1"], next_start=m(200)))
    options = generate_options(list(cands.values()), ctx)
    assert options and all(o.end <= m(200) for o in options)


def test_offers_are_at_least_two_hours_and_online_time_counts_against_them():
    ctx, cands = ctx_for(base().candidate("G", ["H1"], online=20))
    options = generate_options(list(cands.values()), ctx)
    assert options and min(o.minutes for o in options) >= 120
    assert all(o.online_at == o.start + timedelta(minutes=20) for o in options)

    # Handbook: the time to come online counts against the offer's worth. The next shift at
    # +240 caps the offer at 240 min, which is worth only 90 min after 150 min to come online.
    late = base().candidate("G", ["H1"], online=150, next_start=m(240))
    assert staffing(late)[0].candidates[0].failed_rules == ["min_length"]
    # Without that cap a longer offer (360 min) is still worth >= 2 h, so it is eligible.
    assert staffing(base().candidate("G", ["H1"], online=150))[0].candidates[0].eligible
    # A concrete 2 h offer with 20 min to come online is worth 100 min: it fails.
    ctx, cands = ctx_for(base().candidate("G", ["H1"], online=20))
    g = cands["G"]
    two_hours = offer_checks(g.state, g.profile, NOW, 120, ("H1",), ctx, 20, False)
    assert not next(c for c in two_hours if c.code == "min_length").passed


def test_credentials_elsewhere_do_not_help():
    s = base().hospital("H2").candidate("G", ["H2"])
    result, internals = staffing(s)

    assert result.candidates[0].failed_rules == ["credentialed_at_gap"]
    assert internals.options == [] and result.recommendations == []


@pytest.mark.parametrize(
    ("missing", "rule"),
    [(("last_end",), "rest_10h"), (("next_start",), "no_overlap")],
)
def test_missing_schedule_data_fails_instead_of_passing(missing, rule):
    row = staffing(base().candidate("G", ["H1"], missing=missing))[0].candidates[0]
    check = next(x for x in row.checks if x.code == rule)

    assert row.eligible is False and row.failed_rules == [rule]
    assert check.missing_data is True and check.value == "missing"


def test_missing_weekly_hours_fail_and_missing_online_time_is_flagged():
    row = staffing(base().candidate("G", ["H1"], hours=None))[0].candidates[0]
    assert row.failed_rules == ["weekly_hours"]

    result, _ = staffing(base().candidate("G", ["H1"], online=None))
    row = result.candidates[0]
    assert row.eligible and row.online_time_assumed and row.minutes_to_come_online == 30
    assert "minutes_to_come_online (assumed)" in row.missing_data
    assert any("assumed" in line for line in result.recommendations[0].explanation)


# 22. Multi-hospital coverage follows the brief's (non-exclusive) model -----------------


def two_gaps() -> OptScenario:
    s = OptScenario().hospital("H1").hospital("H2")
    s.requirement("H1", "00:00", "00:00", 1).requirement("H2", "00:00", "00:00", 1)
    return s.doctor("P1", ["H1"], end=m(60)).doctor("P2", ["H2"], end=m(60))


def test_one_physician_counts_at_every_gap_hospital_they_cover():
    result, _ = staffing(two_gaps().candidate("G", ["H1", "H2"]))

    assert result.totals.deficit_physician_minutes_before == 360
    assert result.totals.deficit_physician_minutes_after == 0
    assert result.recommendations[0].hospital_ids == ["H1", "H2"]


def test_exclusive_mode_counts_each_physician_at_one_hospital():
    exclusive = config(staffing={"count_at_all_scope_hospitals": False})
    result, _ = staffing(two_gaps().candidate("G", ["H1", "H2"]), exclusive)

    assert result.totals.deficit_physician_minutes_after == 180
    assert len(result.recommendations[0].hospital_ids) == 1


# 21. Split-shift trap -----------------------------------------------------------------


def test_trap_protection_restricts_scope_and_seeds_the_count():
    s = base().hospital("H3").requirement("H3", "00:00", "00:00", 1)
    s.doctor("P3", ["H3"]).history("P3", "H3", 8, last_call_end=-30)
    s.history("P1", "H1", 4, last_call_end=-40)
    for hour in range(24):
        s.baseline("H3", hour, 8.0)  # mean 4 consults/hour at a hospital with no gap
    s.candidate("G", ["H1", "H3"])
    result, _ = staffing(s)
    (rec,) = result.recommendations
    trap = result.trap

    assert rec.protection.routing_scope_hospital_ids == ["H1"]
    assert rec.protection.excluded_credentialed_hospital_ids == ["H3"]
    assert rec.protection.seeded_consult_count == 4  # median of peers covering H1 (P1: 4)
    assert trap.unrestricted.routed_to_joiner_elsewhere > 0
    assert trap.protected.routed_to_joiner_elsewhere == 0
    assert trap.unrestricted.modeled_arrivals == trap.protected.modeled_arrivals == 8


# 19./20. What-if previews never touch real coverage ---------------------------------


def test_what_if_split_shift_reduces_projected_deficit_without_changing_live_coverage():
    s = base().candidate("G", ["H1"])
    analysis = s.analyze(NOW)
    live = analysis.coverage.model_dump()
    windows = len(analysis.coverage_models["H1"].windows)
    action = SplitShiftAction(physician_id="G", start=m(60), duration_minutes=180)
    result = simulate_intervention(analysis, action, ForecastConfig(OptimizationConfig()))
    (p,) = result.projections

    assert result.allowed and result.label.startswith("Projected if accepted")
    assert (p.deficit_physician_minutes_before, p.deficit_physician_minutes_after) == (30, 0)
    assert p.first_shortfall_before == m(60) and p.first_shortfall_after is None
    proposed = [c for c in p.after.contributors if c.status == "proposed"]
    assert [c.physician_id for c in proposed] == ["G"]
    assert any("proposed split shift" in a.label for a in p.after.annotations)
    assert all(c.status != "proposed" for c in p.before.contributors)
    assert any("wait-time" in line for line in result.effects_not_modeled)
    # The live forecast is untouched.
    assert analysis.coverage.model_dump() == live
    assert len(analysis.coverage_models["H1"].windows) == windows


def test_what_if_rejects_an_offer_that_breaks_a_rule():
    s = base().candidate("G", ["H1"], opt_in=False)
    action = SplitShiftAction(physician_id="G", duration_minutes=119)
    result = simulate_intervention(s.analyze(NOW), action, ForecastConfig(OptimizationConfig()))

    assert result.allowed is False and result.projections == []
    assert {v.code for v in result.violations} == {"opt_in", "min_length"}


def test_what_if_consult_assignment_checks_eligibility_and_leaves_coverage_unchanged():
    s = base().doctor("P2", ["H1"])
    s.event("video_started", m(-3), physician_id="P2", consult_id="CX", hospital_id="H1")
    s.consult("C1", "H1")
    analysis = s.analyze(NOW)
    fc = ForecastConfig(OptimizationConfig())

    ok = simulate_intervention(
        analysis, AssignConsultAction(consult_id="C1", physician_id="P1"), fc
    )
    assert ok.allowed and ok.workload.consults_this_shift_after == 1
    (p,) = ok.projections
    assert p.deficit_physician_minutes_before == p.deficit_physician_minutes_after

    busy = simulate_intervention(
        analysis, AssignConsultAction(consult_id="C1", physician_id="P2"), fc
    )
    assert busy.allowed is False and "video" in busy.violations[0].message
