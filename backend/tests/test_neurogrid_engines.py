"""NEUROGRID intelligence engines: invariants that must hold for *any* dataset.

Run against every bundled synthetic sample and (when present) the official challenge
data. Expected values are derived independently (rebuilding coverage from a filtered
state, re-deriving lead-time arithmetic from the roster CSV), never read back from the
engine under test.
"""

from __future__ import annotations

import csv
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.session import build_engine
from app.engines.analysis import analyze
from app.engines.coverage_prediction import build_coverage_models
from app.engines.intelligence import (
    IntelligenceConfig,
    availability_report,
    class_map,
    fragility_report,
    last_safe_moment_report,
    planning_models,
    problem_report,
    scarcity_report,
    simulate_rescues,
)
from app.engines.intelligence.common import drop_physicians, profiles
from app.engines.intelligence.network import _allocation
from app.engines.optimization import load_optimization_config, run_staffing
from app.engines.optimization.routing import build_dispatch_problem  # noqa: F401
from app.main import create_app
from app.repositories import EventRepository, ReferenceRepository, SystemRepository
from app.schemas.intelligence import AvailabilityClass
from tests.conftest import upload

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = Path(__file__).resolve().parents[1] / "sample_data"
OFFICIAL = ROOT / "data"
DATASETS = [
    *(p for p in sorted(SAMPLES.iterdir()) if (p / "event_stream.csv").exists()),
    *([OFFICIAL] if (OFFICIAL / "event_stream.csv").exists() else []),
]


def _load(folder: Path, tmp: Path):
    settings = Settings(
        _env_file=None, app_env="test", database_url=f"sqlite:///{tmp / 'x.db'}", cors_origins=""
    )
    with TestClient(create_app(settings)) as client:
        files = {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()}
        assert upload(client, files).status_code == 200
    engine = build_engine(settings.resolved_database_url)
    with Session(engine) as session:
        events = EventRepository(session).load_all()
        reference = ReferenceRepository(session).load()
        now = SystemRepository(session).get_simulation_state().current_time
    engine.dispose()
    analysis = analyze(events, reference, now)
    cfg = load_optimization_config(None)
    staffing, internals = run_staffing(analysis, cfg, offer_log={})
    return analysis, cfg, staffing, internals


@pytest.fixture(scope="module", params=DATASETS, ids=lambda p: p.name)
def world(request, tmp_path_factory):
    return _load(request.param, tmp_path_factory.mktemp(request.param.name))


def test_every_physician_gets_exactly_one_class_with_evidence(world):
    analysis, cfg, _, _ = world
    report = availability_report(analysis, cfg)
    assert {v.physician_id for v in report.physicians} == {
        p.physician_id for p in analysis.state.physicians
    }
    for v in report.physicians:
        assert v.rationale and v.decision_rule
        if v.availability_class is AvailabilityClass.PROBABLY_BUSY_EXTERNAL:
            assert not v.auto_routable  # brief: treat as busy
        if v.availability_class is AvailabilityClass.UNCERTAIN:
            assert v.needs_confirmation and v.confidence.value == "STALE"
        if v.availability_class in (AvailabilityClass.OFF_SHIFT, AvailabilityClass.UNAVAILABLE):
            assert not v.auto_routable
    assert sum(report.counts_by_class.values()) == len(report.physicians)


def test_single_point_failure_matches_an_independent_rebuild(world):
    """Dropping a physician's windows == rebuilding coverage without that physician."""
    analysis, _, _, _ = world
    horizon = 240
    models = planning_models(analysis, horizon)
    base = profiles(models)
    for p in analysis.state.physicians[:8]:
        state = analysis.state.model_copy(
            update={"physicians": [x for x in analysis.state.physicians if x is not p]}
        )
        rebuilt = build_coverage_models(
            state, analysis.reference, analysis.demand_models, analysis.config.coverage, horizon
        )
        dropped = profiles(drop_physicians(models, [p.physician_id]))
        for hid in models:
            assert dropped[hid].deficit_pm == pytest.approx(
                profiles({hid: rebuilt[hid]})[hid].deficit_pm
            )
            assert dropped[hid].deficit_pm >= base[hid].deficit_pm - 1e-9  # monotone


def test_fragility_report_is_consistent(world):
    analysis, cfg, _, internals = world
    icfg = IntelligenceConfig()
    models = planning_models(analysis, 240)
    report = fragility_report(
        analysis, models, class_map(analysis, cfg), {}, icfg, horizon_minutes=240
    )
    ranks = [c.rank for c in report.physicians]
    assert ranks == list(range(1, len(ranks) + 1))
    scores = [c.criticality_score for c in report.physicians]
    assert scores == sorted(scores, reverse=True)
    for c in report.physicians:
        assert c.added_deficit_physician_minutes == pytest.approx(
            sum(i.added_deficit_physician_minutes for i in c.hospitals_affected)
        )
        if not c.relevant:
            assert c.added_deficit_physician_minutes == 0
    for check in report.allocation:
        assert check.exclusive_covered <= check.pool_covered <= check.required_total
        used = [pid for pids in check.assignment.values() for pid in pids]
        assert len(used) == len(set(used)), "a physician fills at most one position"
    creds = {p.physician_id: set(p.credentialed_hospital_ids) for p in analysis.state.physicians}
    for e in report.edges:
        assert e.hospital_id in creds[e.physician_id]  # edges are real credentials only


@settings(
    max_examples=25, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(data=st.data())
def test_property_removal_never_helps_and_matching_is_valid(world, data):
    analysis, _, _, _ = world
    models = planning_models(analysis, 240)
    ids = sorted({w.physician_id for m in models.values() for w in m.windows})
    if not ids:
        return
    removed = data.draw(st.lists(st.sampled_from(ids), unique=True, max_size=len(ids)))
    base = profiles(models)
    after_models = drop_physicians(models, removed)
    after = profiles(after_models)
    for hid in models:
        assert after[hid].deficit_pm >= base[hid].deficit_pm - 1e-9
    check = _allocation(after_models, analysis.state.as_of, "now")
    assert check.exclusive_covered <= check.pool_covered
    assert not (set(removed) & {p for v in check.assignment.values() for p in v})


def test_last_safe_moment_arithmetic(world):
    analysis, _, _, internals = world
    icfg = IntelligenceConfig()
    report = last_safe_moment_report(internals.ctx, internals.candidates, icfg)
    lead = icfg.lead
    for item in report.items:
        for t in item.candidates:
            assert t.lead.conservative_total_minutes == (
                lead.approval_minutes + lead.response_minutes_conservative + t.lead.online_minutes
            )
            if t.latest_initiation_conservative is not None:
                assert t.latest_initiation_conservative == item.shortfall_at - timedelta(
                    minutes=t.lead.conservative_total_minutes
                )
                assert t.eligible_at_start and t.covers_shortfall_start
        if item.latest_initiation_at is not None:
            assert item.remaining_minutes == pytest.approx(
                (item.latest_initiation_at - analysis.state.as_of).total_seconds() / 60, abs=0.01
            )
        elif item.phase not in ("missed", "no_candidate"):
            pytest.fail(f"{item.hospital_id}: no deadline but phase {item.phase}")


def test_scarcity_never_counts_an_ineligible_backup(world):
    _, _, _, internals = world
    report = scarcity_report(internals.ctx, internals.candidates)
    eligible = {c.physician_id for c in internals.candidates if c.eligibility.eligible}
    for e in report.entries:
        if not e.eligible:
            assert e.recommendation == "not_eligible" and e.scarcity_score == 0
        for h in e.hospitals:
            assert set(h.alternative_candidate_ids) <= eligible
    if report.gap_hospital_ids and not eligible:
        assert report.no_feasible_candidate and report.escalation_recommended


def test_simulator_isolated_and_hard_constraints_first(world):
    analysis, _, staffing, internals = world
    before = {h: m.deficit_physician_minutes() for h, m in internals.ctx.models.items()}
    windows_before = {h: len(m.windows) for h, m in internals.ctx.models.items()}
    targets = staffing.gap_hospital_ids[:1] or [analysis.state.hospitals[0].id]
    sim = simulate_rescues(
        internals.ctx,
        internals.candidates,
        internals.options,
        staffing,
        None,
        IntelligenceConfig(),
        target_hospital_ids=targets,
        target_label="test",
    )
    assert any(o.kind == "do_nothing" for o in sim.options)
    assert sum(o.recommended for o in sim.options) == 1
    rec = next(o for o in sim.options if o.recommended)
    assert rec.feasible and not rec.simulation_only
    for o in sim.options:
        if o.kind == "split_shift" and o.physician_ids:
            cand = next(c for c in internals.candidates if c.physician_id == o.physician_ids[0])
            if not cand.eligibility.eligible:
                assert not o.feasible and o.proposal is None
        if o.simulation_only:
            assert not o.feasible and o.proposal is None
    keys = [o.lexicographic_key for o in sim.options]
    assert keys == sorted(keys)
    # the live models were not mutated by any preview
    assert {h: m.deficit_physician_minutes() for h, m in internals.ctx.models.items()} == before
    assert {h: len(m.windows) for h, m in internals.ctx.models.items()} == windows_before


def test_problem_groups_partition_alerts_deterministically(world):
    analysis, _, _, _ = world
    a = problem_report(analysis)
    b = problem_report(analysis)
    assert [g.fingerprint for g in a.groups] == [g.fingerprint for g in b.groups]
    members = [m for g in a.groups for m in g.member_alert_ids]
    assert sorted(members) == sorted(x.alert_id for x in analysis.alerts.alerts)
    critical = {x.alert_id for x in analysis.alerts.alerts if x.severity.value == "critical"}
    assert critical == {m for g in a.groups for m in g.critical_alert_ids}
    tiers = [g.tier for g in a.groups]
    assert tiers == sorted(tiers)


@pytest.mark.skipif(not (OFFICIAL / "event_stream.csv").exists(), reason="no official data")
def test_official_last_safe_moment_from_roster_csv(tmp_path):
    """Northfield is short from 20:00 ET; the earliest eligible backup's deadline is
    derived from physicians_off_shift_roster.csv (time to come online) and the policy."""
    analysis, _, _, internals = _load(OFFICIAL, tmp_path)
    report = last_safe_moment_report(internals.ctx, internals.candidates, IntelligenceConfig())
    with open(OFFICIAL / "physicians_off_shift_roster.csv", newline="") as fh:
        rows = list(csv.DictReader(fh))
    online_col = next(k for k in rows[0] if "online" in k.lower())
    online = {r["physician_id"]: int(float(r[online_col])) for r in rows}
    for item in report.items:
        if item.best_physician_id is None:
            continue
        lead = 5 + 10 + online[item.best_physician_id]
        assert item.latest_initiation_at == item.shortfall_at - timedelta(minutes=lead)
    northfield = next(i for i in report.items if i.hospital_id == "SYN-008")
    assert northfield.shortfall_at == datetime.fromisoformat("2026-03-17T20:00:00-04:00")
