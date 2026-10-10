"""Demand spikes and the coverage forecast. Expected numbers are worked out by hand
(in the comments) from the scenario definitions, independently of the engine."""

from __future__ import annotations

from datetime import timedelta

import pytest

from app.engines.rules import RiskConfig
from app.schemas.alert import RuleCode
from tests.analysis_helpers import Scenario, alerts_by_id, hospital_coverage, segments, utc

T0 = utc(2031, 2, 3, 15, 20)  # Monday. 08:20 MST (Denver), 09:20 CST (Chicago)


def m(minutes: float):
    return T0 + timedelta(minutes=minutes)


def demand_of(analysis, hid="H1"):
    return next(h for h in analysis.demand.hospitals if h.hospital_id == hid)


# --- Demand ----------------------------------------------------------------------------


def _arrivals(s: Scenario, hid: str, minutes: list[float], prefix: str = "C") -> Scenario:
    for i, minute in enumerate(minutes):
        s.event(
            "consult_received",
            m(minute),
            consult_id=f"{prefix}{i}",
            hospital_id=hid,
            consult_type="Stroke",
        )
    return s


def test_duplicate_consult_events_do_not_increase_arrivals():
    s = Scenario().hospital("H1", "America/Denver").baseline("H1", 8, 1.0)
    s.event("consult_received", m(-10), event_id="X1", consult_id="C1", hospital_id="H1")
    s.event(
        "consult_received", m(-10), event_id="X1", consult_id="C1", hospital_id="H1", ingested=m(-9)
    )  # same event re-sent
    s.event("consult_received", m(-8), event_id="X2", consult_id="C1", hospital_id="H1")  # new id

    d = demand_of(s.analyze(m(0))).current

    assert d.arrivals == 1
    assert d.consult_ids == ["C1"]


def test_spike_uses_hospital_local_hour_and_p90():
    # 15:20Z = 08:20 MST in Denver -> hour 8 (p90 1.0). The UTC hour (15) has p90 10.
    s = Scenario().hospital("H1", "America/Denver").baseline("H1", 8, 1.0).baseline("H1", 15, 10)
    _arrivals(s, "H1", [-30, -5])

    d = demand_of(s.analyze(m(0))).current

    assert (d.local_hour, d.baseline_p90, d.arrivals, d.spike) == (8, 1.0, 2, True)
    assert d.local_hour_label == "08:00–09:00 MST"
    assert "2 arrivals" in d.comparison and "> p90 1" in d.comparison


def test_spike_requires_strictly_above_p90():
    s = Scenario().hospital("H1", "America/Denver").baseline("H1", 8, 2.0)
    _arrivals(s, "H1", [-30, -5])

    assert demand_of(s.analyze(m(0))).current.spike is False  # 2 is not > 2.0


def test_window_is_half_open_and_crosses_the_hour():
    # At 09:10 MST (16:10Z) the window (08:10, 09:10] spans two local hours; baseline hour = 9.
    s = Scenario().hospital("H1", "America/Denver").baseline("H1", 9, 1.0)
    _arrivals(s, "H1", [-10, 0])  # 08:10 (exactly 60 min before: excluded), 08:20
    # 09:10, ingested at that same instant so it is known at as_of (inclusive edge).
    s.event("consult_received", m(50), ingested=m(50), consult_id="C2", hospital_id="H1")

    d = demand_of(s.analyze(m(50))).current

    assert d.local_hour == 9
    assert d.consult_ids == ["C1", "C2"]  # C0 at the exclusive edge, C2 at the inclusive edge


def test_missing_baseline_is_flagged_not_substituted():
    s = Scenario().hospital("H1", "America/Denver").baseline("H1", 3, 1.0)
    _arrivals(s, "H1", [-5, -4, -3])

    d = demand_of(s.analyze(m(0))).current

    assert (d.spike, d.baseline_status, d.requirement_adjustment, d.baseline_p90) == (
        None,
        "missing",
        None,
        None,
    )


def test_baseline_hour_on_dst_fall_back_day():
    # 2031-11-02: 05:30Z = 01:30 EDT and 06:30Z = 01:30 EST — both local hour 1.
    s = Scenario().hospital("H1", "America/New_York").baseline("H1", 1, 0.5)
    s.event("consult_received", utc(2031, 11, 2, 5, 0), consult_id="C1", hospital_id="H1")

    first = demand_of(s.analyze(utc(2031, 11, 2, 5, 30))).current
    second = demand_of(s.analyze(utc(2031, 11, 2, 6, 30))).current

    assert (first.local_hour, first.local_hour_label) == (1, "01:00–02:00 EDT")
    assert (second.local_hour, second.local_hour_label) == (1, "01:00–02:00 EST")
    assert first.spike is True and second.arrivals == 0


# --- Coverage --------------------------------------------------------------------------


def one_hospital(tz: str = "America/Chicago", n: int = 1) -> Scenario:
    return Scenario().hospital("H1", tz).requirement("H1", "00:00", "00:00", n)


def test_spike_raises_required_coverage_by_exactly_one():
    # Requirement 1 all day; hour-9 CST p90 1.0; 2 arrivals in the last hour -> required 2.
    s = one_hospital().baseline("H1", 9, 1.0).baseline("H1", 10, 1.0)
    s.on_shift("P1", ["H1"], m(-120), m(600))
    _arrivals(s, "H1", [-50, -40])  # leave the window at m(10) and m(20)

    a = s.analyze(m(0))
    # Spike while >1 known arrival in window: until m(10) (C0 exits). Hand-derived segments:
    assert segments(a, "H1") == [
        (m(0), m(10), 2, 1, 1),
        (m(10), m(90), 1, 1, 0),
    ]
    first = hospital_coverage(a, "H1").segments[0]
    assert (first.required_base, first.spike_adjustment) == (1, 1)
    assert RuleCode.DEMAND_SPIKE.value + ":hospital:H1" in alerts_by_id(a)


def test_shift_end_creates_projected_gap():
    s = one_hospital().on_shift("P1", ["H1"], m(-300), m(40))
    hc = hospital_coverage(s.analyze(m(0)), "H1")

    # Gap from m(40) to horizon end m(90): 50 min x deficit 1 = 50 physician-minutes.
    assert hc.metrics.first_shortfall_at == m(40)
    assert hc.metrics.shortfall_minutes == 50
    assert hc.metrics.deficit_physician_minutes == 50
    assert any("shift ends at" in e and "from 1 to 0" in e for e in hc.explanations)
    assert [a.kind for a in hc.annotations] == ["shift_end"]


def test_deficit_is_exact_between_unaligned_boundaries():
    end = m(37) + timedelta(seconds=13)
    s = one_hospital().on_shift("P1", ["H1"], m(-300), end)
    hc = hospital_coverage(s.analyze(m(0)), "H1")

    # (5400 s - 2233 s) / 60 = 52.78333... physician-minutes
    assert hc.metrics.first_shortfall_at == end
    assert hc.metrics.deficit_physician_minutes == pytest.approx(3167 / 60, abs=1e-4)
    assert any(p.at == end and p.kind == "boundary" for p in hc.points)


def test_physician_not_credentialed_is_excluded():
    s = one_hospital().hospital("H2").on_shift("P1", ["H2"], m(-60), m(600))
    hc = hospital_coverage(s.analyze(m(0)), "H1")

    assert hc.metrics.available_now == 0 and hc.metrics.deficit_now == 1
    excluded = next(c for c in hc.contributors if c.physician_id == "P1")
    assert excluded.status == "excluded" and "not credentialed" in excluded.reasons[0]
    assert any("Dr P1 cannot count toward Hospital H1" in e for e in hc.explanations)


def test_temporarily_unavailable_physician_excluded_and_busy_counted():
    s = (
        one_hospital(n=2)
        .on_shift("P1", ["H1"], m(-60), m(600))
        .on_shift("P2", ["H1"], m(-60), m(600))
    )
    s.event("physician_status_changed", m(-5), physician_id="P1", status="Temporarily Unavailable")
    s.event("incoming_call_started", m(-2), physician_id="P2", consult_id="CX", hospital_id="H1")

    hc = hospital_coverage(s.analyze(m(0)), "H1")

    # P1 excluded for the whole horizon (no return time known); P2 busy but on duty.
    assert hc.metrics.available_now == 1 and hc.metrics.deficit_physician_minutes == 90
    reasons = {c.physician_id: c.reasons for c in hc.contributors}
    assert "Temporarily Unavailable" in reasons["P1"][0]
    assert any("busy now" in r for r in reasons["P2"])


def test_busy_counting_is_configurable():
    s = one_hospital().on_shift("P1", ["H1"], m(-60), m(600))
    s.event("video_started", m(-2), physician_id="P1", consult_id="CX", hospital_id="H1")
    config = RiskConfig()
    config.coverage.busy_counts_as_available = False

    assert hospital_coverage(s.analyze(m(0)), "H1").metrics.deficit_now == 0
    assert hospital_coverage(s.analyze(m(0), config), "H1").metrics.deficit_now == 1


def test_multi_hospital_physician_counts_at_each_hospital():
    s = Scenario().hospital("H1").hospital("H2")
    s.requirement("H1", "00:00", "00:00", 1).requirement("H2", "00:00", "00:00", 1)
    s.on_shift("P1", ["H1", "H2"], m(-60), m(600))
    a = s.analyze(m(0))

    assert hospital_coverage(a, "H1").metrics.available_now == 1
    assert hospital_coverage(a, "H2").metrics.available_now == 1


def test_unknown_shift_ends_are_surfaced_as_uncertainty():
    s = one_hospital(n=2).off_shift("P1", ["H1"], m(30))  # roster next start, no end in data
    s.off_shift("P2", ["H1"], None)
    s.event("shift_started", m(-10), physician_id="P2")  # on shift, no scheduled end
    hc = hospital_coverage(s.analyze(m(0)), "H1")

    by_id = {c.physician_id: c for c in hc.contributors}
    assert by_id["P1"].status == "joins_later" and by_id["P1"].counts_until is None
    assert by_id["P2"].status == "counted" and by_id["P2"].counts_until is None
    assert {by_id["P1"].certainty, by_id["P2"].certainty} == {"uncertain"}
    assert hc.metrics.confidence == "uncertain"
    # Required 2: P2 alone for 30 min (deficit 1), then both. Confirmed-only: deficit 2 x 90.
    assert hc.metrics.deficit_physician_minutes == 30
    assert hc.metrics.deficit_physician_minutes_if_uncertain_excluded == 180
    assert any("end time unknown" in e for e in hc.explanations)


def test_offline_agent_counts_but_uncertain():
    s = one_hospital().on_shift("P1", ["H1"], m(-60), m(600))
    s.event("agent_heartbeat_lost", m(-1), physician_id="P1")
    hc = hospital_coverage(s.analyze(m(0)), "H1")

    assert hc.metrics.deficit_now == 0
    assert hc.segments[0].available_uncertain == 1
    assert hc.metrics.deficit_physician_minutes_if_uncertain_excluded == 90


def test_hospital_time_zones_change_requirements_at_their_own_local_time():
    # 2031-06-03 22:30Z = 18:30 EDT (New York) = 15:30 PDT (Los Angeles). Blocks 07-19 -> 2,
    # 19-07 -> 1. NY drops to 1 at 19:00 EDT = 23:00Z; LA stays at 2 (19:00 PDT = 02:00Z).
    as_of = utc(2031, 6, 3, 22, 30)
    s = Scenario().hospital("NY", "America/New_York").hospital("LA", "America/Los_Angeles")
    for hid in ("NY", "LA"):
        s.requirement(hid, "07:00", "19:00", 2).requirement(hid, "19:00", "07:00", 1)
    s.on_shift("P1", ["NY", "LA"], as_of - timedelta(hours=5), as_of + timedelta(hours=6))
    a = s.analyze(as_of)

    assert segments(a, "NY") == [
        (as_of, utc(2031, 6, 3, 23, 0), 2, 1, 1),
        (utc(2031, 6, 3, 23, 0), utc(2031, 6, 4, 0, 0), 1, 1, 0),
    ]
    assert segments(a, "LA") == [(as_of, utc(2031, 6, 4, 0, 0), 2, 1, 1)]
    assert hospital_coverage(a, "NY").metrics.deficit_physician_minutes == 30
    assert hospital_coverage(a, "LA").metrics.deficit_physician_minutes == 90


def test_dst_fall_back_repeats_a_local_block_boundary():
    # 2031-11-02 New York: 06:00Z = 02:00 EDT -> 01:00 EST. Block 01:45-08:00 needs 2.
    # 01:45 happens twice: 05:45Z (EDT) and 06:45Z (EST). One physician on shift.
    as_of = utc(2031, 11, 2, 5, 30)
    s = Scenario().hospital("H1", "America/New_York")
    s.requirement("H1", "01:45", "08:00", 2).requirement("H1", "08:00", "01:45", 1)
    s.on_shift("P1", ["H1"], as_of - timedelta(hours=3), as_of + timedelta(hours=8))
    a = s.analyze(as_of)

    assert segments(a, "H1") == [
        (utc(2031, 11, 2, 5, 30), utc(2031, 11, 2, 5, 45), 1, 1, 0),
        (utc(2031, 11, 2, 5, 45), utc(2031, 11, 2, 6, 0), 2, 1, 1),
        (utc(2031, 11, 2, 6, 0), utc(2031, 11, 2, 6, 45), 1, 1, 0),
        (utc(2031, 11, 2, 6, 45), utc(2031, 11, 2, 7, 0), 2, 1, 1),
    ]
    hc = hospital_coverage(a, "H1")
    assert hc.metrics.deficit_physician_minutes == 30
    assert any(
        x.kind == "dst_transition" and x.at == utc(2031, 11, 2, 6, 0) for x in hc.annotations
    )


def test_dst_spring_forward_skips_a_nonexistent_local_time():
    # 2031-03-09 New York: 07:00Z = 02:00 EST -> 03:00 EDT. 02:30 never happens; the block
    # starting 02:30 takes effect at the jump (07:00Z). Deficit 1 from 07:00Z to 08:00Z.
    as_of = utc(2031, 3, 9, 6, 30)
    s = Scenario().hospital("H1", "America/New_York")
    s.requirement("H1", "02:30", "08:00", 2).requirement("H1", "08:00", "02:30", 1)
    s.on_shift("P1", ["H1"], as_of - timedelta(hours=3), as_of + timedelta(hours=8))
    a = s.analyze(as_of)

    assert segments(a, "H1") == [
        (utc(2031, 3, 9, 6, 30), utc(2031, 3, 9, 7, 0), 1, 1, 0),
        (utc(2031, 3, 9, 7, 0), utc(2031, 3, 9, 8, 0), 2, 1, 1),
    ]
    assert hospital_coverage(a, "H1").metrics.deficit_physician_minutes == 60


def test_future_events_do_not_leak_into_forecast_or_demand():
    s = one_hospital().baseline("H1", 9, 0.5).off_shift("P2", ["H1"], None)
    s.event("consult_received", m(-10), consult_id="C1", hospital_id="H1")
    without_future = s.analyze(m(0))
    # Known only after as_of: a new arrival and an early shift start.
    s.event("consult_received", m(5), ingested=m(5), consult_id="C2", hospital_id="H1")
    s.event("shift_started", m(-1), ingested=m(10), physician_id="P2")
    with_future = s.analyze(m(0))

    assert with_future.coverage.model_dump() == without_future.coverage.model_dump()
    assert with_future.demand.model_dump() == without_future.demand.model_dump()
    assert demand_of(with_future).current.arrivals == 1
    # And they do count once the clock reaches them.
    later = s.analyze(m(11))
    assert demand_of(later).current.arrivals == 2
    assert hospital_coverage(later, "H1").metrics.available_now == 1


def test_no_eligible_physician_is_a_visible_deficit_not_a_crash():
    a = one_hospital(n=2).analyze(m(0))
    hc = hospital_coverage(a, "H1")

    assert (hc.metrics.deficit_now, hc.metrics.deficit_physician_minutes) == (2, 180)
    assert any("No physician credentialed" in e for e in hc.explanations)
    assert alerts_by_id(a)["COVERAGE_GAP_NOW:hospital:H1"].severity.value == "critical"


def test_hospital_without_requirement_has_no_gap_and_says_so():
    s = Scenario().hospital("H1").on_shift("P1", ["H1"], m(-60), m(30))
    hc = hospital_coverage(s.analyze(m(0)), "H1")

    assert not hc.requirement_defined and hc.metrics.deficit_now is None
    assert hc.metrics.confidence == "unknown"
    assert "No coverage requirement" in hc.explanations[0]


def test_regular_chart_points_do_not_change_the_integral():
    s = one_hospital().on_shift("P1", ["H1"], m(-300), m(40))
    coarse = hospital_coverage(s.analyze(m(0), step_minutes=30), "H1")
    fine = hospital_coverage(s.analyze(m(0), step_minutes=1), "H1")

    assert coarse.metrics == fine.metrics
    assert len(fine.points) > len(coarse.points)


def test_horizon_can_extend_beyond_90_minutes():
    s = one_hospital().on_shift("P1", ["H1"], m(-300), m(150))
    hc = hospital_coverage(s.analyze(m(0), horizon_minutes=180), "H1")

    assert hc.horizon_end == m(180)
    assert hc.metrics.deficit_physician_minutes == 30
