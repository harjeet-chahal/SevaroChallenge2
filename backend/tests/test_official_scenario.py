"""The official Challenge 2 scenario (repo-root ``data/``) at the 18:20 ET reference time.

Every expected value is derived by hand from the raw CSVs, or recomputed here from them
with the standard library. None is read back from the engine. The derivations are in
docs/official-scenario-audit.md. Skipped when the folder is absent.

Coverage is credentialed on-duty capacity: a physician on a call or video still counts,
while Temporarily Unavailable does not. Being free right now is a routing concept, kept
separate (see the audit, section 2).
"""

from __future__ import annotations

import csv
import io
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.db.session import build_engine
from app.engines.analysis import analyze
from app.engines.optimization import load_optimization_config, run_staffing
from app.engines.rules import load_risk_config
from app.main import create_app
from app.repositories import EventRepository, ReferenceRepository
from tests.conftest import upload

DATA = Path(__file__).resolve().parents[2] / "data"

pytestmark = pytest.mark.skipif(
    not (DATA / "event_stream.csv").exists(), reason="challenge dataset not present"
)

ET = ZoneInfo("America/New_York")
DAY = datetime(2026, 3, 17).date()
NOW = datetime(2026, 3, 17, 18, 20, tzinfo=ET)
HOSPITALS = [f"SYN-{n:03d}" for n in range(1, 13)]
COORD = {"X-Demo-Role": "coordinator", "X-Demo-Actor-Id": "coord-1"}


def _rows(name: str) -> list[dict[str, str]]:
    with open(DATA / name, newline="") as handle:
        return list(csv.DictReader(handle))


def _et(clock: str) -> datetime:
    """'HH:MM' or 'HH:MM:SS' Eastern on the scenario day."""
    return datetime.combine(DAY, time(*map(int, clock.split(":"))), tzinfo=ET)


def _iso(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _csv_requirement(hospital_id: str, moment: datetime) -> int:
    """coverage_requirements.csv looked up by the *Eastern* wall clock of the instant."""
    clock = moment.astimezone(ET).strftime("%H:%M")
    for row in _rows("coverage_requirements.csv"):
        if row["hospital_id"] != hospital_id:
            continue
        start, end = row["time_block_et"].split("-")
        inside = (start <= clock < end) if start < end else (clock >= start or clock < end)
        if inside:
            return int(row["min_available_credentialed_physicians"])
    raise AssertionError(f"no block for {hospital_id} at {clock}")


def _first_received() -> dict[str, tuple[datetime, str]]:
    """consult_id -> (first consult_received event_time, hospital), one copy per event id."""
    seen: set[str] = set()
    first: dict[str, tuple[datetime, str]] = {}
    for row in _rows("event_stream.csv"):
        if row["event_type"] != "consult_received" or row["event_id"] in seen:
            continue
        seen.add(row["event_id"])
        at = _iso(row["event_time"])
        if row["consult_id"] not in first or at < first[row["consult_id"]][0]:
            first[row["consult_id"]] = (at, row["hospital_id"])
    return first


@pytest.fixture(scope="module")
def official(tmp_path_factory):
    db = tmp_path_factory.mktemp("official") / "official.db"
    settings = Settings(
        _env_file=None,
        app_env="test",
        database_url=f"sqlite:///{db}",
        cors_origins="http://localhost:3000",
    )
    with TestClient(create_app(settings)) as client:
        files = {p.name: p.read_bytes() for p in sorted(DATA.glob("*.csv"))}
        response = upload(client, files)
        assert response.status_code == 200, response.text
        yield client, settings


@pytest.fixture(scope="module")
def inputs(official):
    _, settings = official
    engine = build_engine(settings.resolved_database_url)
    with Session(engine) as session:
        events = EventRepository(session).load_all()
        reference = ReferenceRepository(session).load()
    engine.dispose()
    return events, reference


@pytest.fixture(scope="module")
def analysis_1820(inputs):
    events, reference = inputs
    return analyze(events, reference, NOW, load_risk_config(None))


def _staffing(inputs, *, at: datetime = NOW, planning_minutes: int | None = None):
    events, reference = inputs
    analysis = analyze(events, reference, at, load_risk_config(None))
    cfg = load_optimization_config(None)
    if planning_minutes is not None:
        staffing = cfg.staffing.model_copy(update={"planning_horizon_minutes": planning_minutes})
        cfg = cfg.model_copy(update={"staffing": staffing})
    result, _ = run_staffing(analysis, cfg)
    return result


# --- 1. Import and replay ---------------------------------------------------------------


def test_bundled_challenge_loads_and_verifies_via_demo_endpoint(client):
    response = client.post("/api/datasets/challenge")
    assert response.status_code == 200, response.text
    report = response.json()
    assert report["synthetic"] is True
    assert _iso(report["reference_time"]) == NOW
    assert report["reference_source"] == "snapshot_filename"
    verification = client.get("/api/datasets/verification").json()
    assert verification["available"] is True
    assert verification["compared_entities"] == 26
    assert verification["compared_fields"] > 0
    assert verification["mismatches"] == []


def test_replay_at_1820_reproduces_both_reference_snapshots(official):
    client, _ = official
    assert _iso(client.get("/api/simulation").json()["current_time"]) == NOW
    verification = client.get("/api/datasets/verification").json()
    assert verification["available"] is True
    assert verification["compared_entities"] == 8 + 18  # snapshot rows: physicians + consults
    assert verification["mismatches"] == []


def test_shift_and_roster_instants_are_preserved(inputs):
    _, reference = inputs
    by_id = {p.id: p for p in reference.physicians}
    for row in _rows("physicians_on_shift.csv"):
        shift = by_id[row["physician_id"]].schedule.current_shift
        assert shift.start == _et(row["shift_start_et"])
        assert shift.end == _et(row["shift_end_et"])
    for row in _rows("physicians_off_shift_roster.csv"):
        schedule = by_id[row["physician_id"]].schedule
        assert schedule.last_shift_ended_at == _iso(row["last_shift_end"])
        assert schedule.next_shift_starts_at == _iso(row["next_shift_start"])
        assert schedule.hours_worked_trailing_7d == float(row["hours_worked_last_7d"])
        assert schedule.minutes_to_come_online == int(row["est_minutes_to_online"])
        assert by_id[row["physician_id"]].split_shift_opt_in is (row["split_shift_opt_in"] == "Yes")
    zones = {h.id: h.timezone for h in reference.hospitals}
    assert zones == {r["hospital_id"]: r["local_timezone"] for r in _rows("hospitals.csv")}


def test_credentialing_matrix_is_loaded_cell_for_cell(inputs):
    _, reference = inputs
    expected = {
        (row["physician_id"], h)
        for row in _rows("credentialing_matrix.csv")
        for h in HOSPITALS
        if row[h].strip().upper() == "Y"
    }
    loaded = {(p.id, h) for p in reference.physicians for h in p.credentialed_hospital_ids}
    assert len(expected) == 68
    assert loaded == expected


def test_eastern_requirement_blocks_apply_at_the_labelled_instants(analysis_1820):
    """Each ET block must start and end at the same instant in every hospital time zone."""
    boundaries = [_et(b) for b in ("07:00", "16:00", "22:00")]
    probes = [_et("00:00") + timedelta(minutes=30 * i) for i in range(48)]
    probes += [b + d for b in boundaries for d in (timedelta(0), timedelta(seconds=-1))]
    for hid in HOSPITALS:
        model = analysis_1820.coverage_models[hid]
        for moment in probes:
            required, _ = model.requirement_at(moment)
            assert required == _csv_requirement(hid, moment), (hid, moment.isoformat())


def test_eastern_baseline_hours_apply_at_the_labelled_instants(analysis_1820):
    p90 = {
        (r["hospital_id"], int(r["hour_start_et"][:2])): float(r["p90_consults"])
        for r in _rows("baseline_hourly_volume.csv")
    }
    for hid in HOSPITALS:
        model = analysis_1820.demand_models[hid]
        for hour in range(24):
            moment = _et(f"{hour:02d}:30")
            assert model.evaluate(moment).baseline_p90 == p90[(hid, hour)], (hid, hour)


# --- 2./3. Demand and coverage ----------------------------------------------------------


def test_demand_at_1820_only_suncrest_is_above_its_p90(official):
    client, _ = official
    counts = dict.fromkeys(HOSPITALS, 0)
    for at, hid in _first_received().values():
        if NOW - timedelta(minutes=60) < at <= NOW:
            counts[hid] += 1
    p90 = {
        r["hospital_id"]: float(r["p90_consults"])
        for r in _rows("baseline_hourly_volume.csv")
        if r["hour_start_et"] == "18:00"
    }
    demand = {h["hospital_id"]: h["current"] for h in client.get("/api/demand").json()["hospitals"]}
    for hid in HOSPITALS:
        assert demand[hid]["arrivals"] == counts[hid], hid
        assert demand[hid]["baseline_p90"] == p90[hid], hid
        assert demand[hid]["spike"] is (counts[hid] > p90[hid]), hid
    assert [h for h in HOSPITALS if demand[h]["spike"]] == ["SYN-005"]
    assert counts["SYN-005"] == 5 and p90["SYN-005"] == 1


# Credentialed on-duty capacity at 18:20, by hand from the on-shift roster x matrix,
# minus PHY-008 (Temporarily Unavailable). Busy physicians count.
CAPACITY_1820 = {
    "SYN-001": ["PHY-001", "PHY-003", "PHY-004", "PHY-006"],
    "SYN-002": ["PHY-002", "PHY-007"],
    "SYN-003": ["PHY-004", "PHY-005"],
    "SYN-004": ["PHY-001", "PHY-003", "PHY-005", "PHY-006"],
    "SYN-005": ["PHY-003", "PHY-005", "PHY-006"],
    "SYN-006": ["PHY-001", "PHY-004", "PHY-006"],
    "SYN-007": ["PHY-002", "PHY-004"],
    "SYN-008": ["PHY-001", "PHY-002", "PHY-005", "PHY-006"],
    "SYN-009": ["PHY-001", "PHY-003", "PHY-004", "PHY-006"],
    "SYN-010": ["PHY-002"],
    "SYN-011": ["PHY-001", "PHY-002", "PHY-005", "PHY-006"],
    "SYN-012": ["PHY-001", "PHY-003", "PHY-006", "PHY-007"],
}
# 16:00-22:00 ET block, plus one at Suncrest for the demand spike.
REQUIRED_1820 = {
    h: 2 if h in ("SYN-001", "SYN-003", "SYN-005", "SYN-008") else 1 for h in HOSPITALS
}


def test_capacity_forecast_has_no_gap_through_1950(official):
    client, _ = official
    report = client.get("/api/coverage").json()
    assert report["horizon_minutes"] == 90
    for h in report["hospitals"]:
        hid, m = h["hospital_id"], h["metrics"]
        assert m["required_now"] == REQUIRED_1820[hid], hid
        assert m["available_now"] == len(CAPACITY_1820[hid]), hid
        assert sorted(h["segments"][0]["counted_physician_ids"]) == CAPACITY_1820[hid], hid
        assert m["deficit_physician_minutes"] == 0 and m["first_shortfall_at"] is None, hid


def test_suncrest_oak_valley_and_redwood_traces(official, analysis_1820):
    client, _ = official
    report = {h["hospital_id"]: h for h in client.get("/api/coverage").json()["hospitals"]}
    arrivals = sorted(at for at, hid in _first_received().values() if hid == "SYN-005")
    recent = [a for a in arrivals if NOW - timedelta(minutes=60) < a <= NOW]
    # The spike (count > p90 of 1) lasts until the 2nd-latest arrival leaves the window.
    spike_end = recent[-2] + timedelta(minutes=60)
    seven = _et("19:00")

    def trace(hid):
        return [
            (_iso(s["start"]), s["required"], sorted(s["counted_physician_ids"]))
            for s in report[hid]["segments"]
        ]

    assert trace("SYN-005") == [
        (NOW, 2, ["PHY-003", "PHY-005", "PHY-006"]),
        (seven, 2, ["PHY-005", "PHY-011"]),  # PHY-003/006 leave, night PHY-011 starts
        (spike_end, 1, ["PHY-005", "PHY-011"]),
    ]
    assert trace("SYN-010") == [(NOW, 1, ["PHY-002"])]  # PHY-008 Temporarily Unavailable
    assert trace("SYN-003") == [(NOW, 2, ["PHY-004", "PHY-005"])]
    reasons = {c["physician_id"]: c["reasons"] for c in report["SYN-010"]["contributors"]}
    assert any(r.startswith("busy now") for r in reasons["PHY-002"])
    assert "Temporarily Unavailable" in reasons["PHY-008"][0]


def test_first_capacity_gaps_follow_the_20_00_and_21_00_shift_ends(official):
    client, _ = official
    report = client.get("/api/coverage", params={"horizon_minutes": 240}).json()
    gaps = {
        h["hospital_id"]: (
            _iso(h["metrics"]["first_shortfall_at"]),
            h["metrics"]["deficit_physician_minutes"],
        )
        for h in report["hospitals"]
        if h["metrics"]["deficit_physician_minutes"]
    }
    # Northfield: PHY-001/002/005 leave at 20:00 -> PHY-011 alone vs 2 until 22:00 (min 1).
    # Cedar Ridge: PHY-004 leaves at 21:00 -> PHY-011 alone vs 2 until 22:00.
    # Redwood: PHY-005 leaves at 20:00 (PHY-012 starts), PHY-004 at 21:00 -> 1 vs 2.
    assert gaps == {
        "SYN-008": (_et("20:00"), 120),
        "SYN-001": (_et("21:00"), 60),
        "SYN-003": (_et("21:00"), 60),
    }


def test_scheduled_free_and_routing_ready_tiers_stay_separate(official):
    """Capacity, free-now and routing-ready counts differ; routing failed only where a
    consult is waiting and no credentialed physician is free."""
    client, _ = official
    physicians = client.get("/api/physicians").json()
    busy = {"PHY-001", "PHY-002", "PHY-003", "PHY-005", "PHY-006"}  # snapshot derived states
    assert {p["physician_id"] for p in physicians if p["availability"] == "busy"} == busy
    assert {p["physician_id"] for p in physicians if p["availability"] == "unavailable"} == {
        "PHY-008"
    }

    def tier(pid_filter):
        return {
            h: sorted(
                p["physician_id"]
                for p in physicians
                if p["on_shift"] and h in p["credentialed_hospital_ids"] and pid_filter(p)
            )
            for h in HOSPITALS
        }

    scheduled = tier(lambda p: p["availability"] != "unavailable")
    free = tier(lambda p: p["availability"] == "available")
    ready = tier(
        lambda p: (
            p["availability"] == "available"
            and not p["signals"]["ringing"]
            and not (
                p["signals"]["last_call_ended_at"]
                and NOW - _iso(p["signals"]["last_call_ended_at"]) < timedelta(minutes=2)
            )
        )
    )
    assert scheduled == CAPACITY_1820
    assert {h: v for h, v in free.items() if v} == {
        "SYN-001": ["PHY-004"],
        "SYN-002": ["PHY-007"],
        "SYN-003": ["PHY-004"],
        "SYN-006": ["PHY-004"],
        "SYN-007": ["PHY-004"],
        "SYN-009": ["PHY-004"],
        "SYN-012": ["PHY-007"],
    }
    # PHY-007's phone is ringing for CON-2109, so only PHY-004 is routing-ready.
    assert {h: v for h, v in ready.items() if v} == {
        h: ["PHY-004"] for h in ("SYN-001", "SYN-003", "SYN-006", "SYN-007", "SYN-009")
    }
    # Under a "free right now" reading seven hospitals would be short, Redwood included.
    short_if_free = sorted(h for h in HOSPITALS if len(free[h]) < REQUIRED_1820[h])
    assert short_if_free == [
        "SYN-001",
        "SYN-003",
        "SYN-004",
        "SYN-005",
        "SYN-008",
        "SYN-010",
        "SYN-011",
    ]
    consults = client.get("/api/consultations").json()
    failed = {c["hospital_id"] for c in consults if c["is_open"] and c["routing_failures"]}
    assert failed == {"SYN-005", "SYN-010"}
    assert all(not free[h] for h in failed)


def test_capacity_meets_base_requirements_all_day_but_free_count_does_not(inputs):
    """Evidence for the governing coverage definition (audit section 2), sampled every
    30 min from 09:00 to 18:00 ET: on-duty capacity always meets the base requirement
    (only a demand spike can open a gap), whereas counting only free physicians would leave
    Redwood (2 required, 2 credentialed on shift) short for most of the day."""
    events, reference = inputs
    samples = [_et("09:00") + timedelta(minutes=30 * i) for i in range(19)]
    redwood_short_if_free = 0
    for moment in samples:
        analysis = analyze(events, reference, moment, load_risk_config(None))
        for h in analysis.coverage.hospitals:
            now = h.segments[0]
            assert now.available >= now.required_base, (h.hospital_id, moment.isoformat())
        free = [
            p
            for p in analysis.state.physicians
            if p.on_shift
            and p.availability.value == "available"
            and "SYN-003" in p.credentialed_hospital_ids
        ]
        redwood_short_if_free += len(free) < 2
    assert redwood_short_if_free > len(samples) / 2


# --- 4. Off-shift physicians -----------------------------------------------------------


def test_every_off_shift_physician_passes_or_fails_the_expected_rules(official):
    client, _ = official
    staffing = client.get("/api/optimization/split-shifts").json()
    assert staffing["gap_hospital_ids"] == ["SYN-001", "SYN-003", "SYN-008"]
    rows = {c["physician_id"]: c for c in staffing["candidates"]}
    expected = {
        "PHY-009": set(),  # rested 11.3 h, 36 + offer <= 60, next shift 03-18 19:00
        "PHY-010": set(),  # rested 22.3 h, 24 h, next shift 03-19 08:00
        "PHY-011": {"no_overlap"},  # night shift at 19:00, 40 min away
        "PHY-012": {"opt_in", "no_overlap"},  # opted out; night shift at 20:00
        "PHY-013": {"opt_in", "credentialed_at_gap"},  # opted out; 005/009/010/011 not short
        "PHY-014": {"weekly_hours"},  # 59 h + 2 h > 60 h
    }
    assert {pid: set(r["failed_rules"]) for pid, r in rows.items()} == expected
    assert rows["PHY-009"]["gap_hospital_ids"] == ["SYN-008"]
    assert rows["PHY-010"]["gap_hospital_ids"] == ["SYN-003"]
    off = {r["physician_id"]: r for r in _rows("physicians_off_shift_roster.csv")}
    for pid, row in rows.items():
        assert row["remaining_weekly_hours"] == 60 - float(off[pid]["hours_worked_last_7d"])
        assert row["minutes_to_come_online"] == int(off[pid]["est_minutes_to_online"])
        assert _iso(row["latest_valid_end"]) == _iso(off[pid]["next_shift_start"])


@pytest.mark.parametrize(
    ("planning_minutes", "eligible"),
    [
        (90, set()),
        (100, set()),  # the 20:00 Northfield gap starts exactly at the window end
        (101, {"PHY-009"}),
        (120, {"PHY-009"}),  # a two-hour window reproduces the handbook candidate count
        (160, {"PHY-009"}),  # the 21:00 Cedar Ridge / Redwood gaps not reached yet
        (161, {"PHY-009", "PHY-010"}),
        (240, {"PHY-009", "PHY-010"}),
    ],
)
def test_eligible_set_at_1820_depends_on_the_look_ahead_window(inputs, planning_minutes, eligible):
    result = _staffing(inputs, planning_minutes=planning_minutes)
    assert {c.physician_id for c in result.candidates if c.eligible} == eligible


@pytest.mark.parametrize(
    ("minutes_after", "eligible"),
    [(10, set()), (11, {"PHY-009"}), (70, {"PHY-009"}), (71, {"PHY-009", "PHY-010"})],
)
def test_with_a_90_minute_window_the_eligible_set_follows_the_clock(
    inputs, minutes_after, eligible
):
    result = _staffing(inputs, at=NOW + timedelta(minutes=minutes_after), planning_minutes=90)
    assert {c.physician_id for c in result.candidates if c.eligible} == eligible


# --- 6. Judge CSV ------------------------------------------------------------------------

JUDGE_CSV = (
    "event_id,event_time,ingested_at,consult_id,event_type,physician_id,hospital_id,description\n"
    # a new stroke consult at the surging hospital, after 18:20
    "JDG-0001,2026-03-17T18:24:00-04:00,2026-03-17T18:24:02-04:00,CON-9001,consult_received,,"
    "SYN-005,Stroke consult request received\n"
    "JDG-0002,2026-03-17T18:25:30-04:00,2026-03-17T18:25:33-04:00,CON-9001,consult_triaged,,"
    "SYN-005,Consult triaged\n"
    "JDG-0003,2026-03-17T18:25:40-04:00,2026-03-17T18:25:42-04:00,CON-9001,"
    "routing_attempt_failed,,SYN-005,No available credentialed provider; retry scheduled\n"
    # the hospital calls again about CON-2105 (first received 18:07:30)
    "JDG-0004,2026-03-17T18:26:00-04:00,2026-03-17T18:26:02-04:00,CON-2105,consult_received,,"
    "SYN-010,Stroke consult request received\n"
    # a record that arrives 5.5 minutes late, then the same record again
    "JDG-0005,2026-03-17T18:22:00-04:00,2026-03-17T18:27:30-04:00,CON-2107,video_ended,PHY-006,"
    "SYN-005,Video consult completed; note not started\n"
    "JDG-0005,2026-03-17T18:22:00-04:00,2026-03-17T18:27:30-04:00,CON-2107,video_ended,PHY-006,"
    "SYN-005,Video consult completed; note not started\n"
    # a base-dataset record sent again
    "EVT-01163,2026-03-17T18:19:40-04:00,2026-03-17T18:19:43-04:00,CON-2109,"
    "incoming_call_ringing,PHY-007,SYN-012,Hospital call ringing to intended physician; "
    "not yet answered\n"
    # a backfilled record that happened before 18:20
    "JDG-0006,2026-03-17T18:15:00-04:00,2026-03-17T18:19:50-04:00,CON-2118,note_started,"
    "PHY-006,SYN-012,Note started\n"
)


def test_judge_csv_appends_to_the_official_day_without_resetting_anything(client):
    files = {p.name: p.read_bytes() for p in sorted(DATA.glob("*.csv"))}
    assert upload(client, files).status_code == 200
    proposed = client.post("/api/interventions", headers=COORD, json={"type": "split_shift"})
    assert proposed.status_code == 201, proposed.text
    before = client.get("/api/simulation").json()
    import_id = client.get("/api/datasets/status").json()["active"]["import_id"]
    first_2105 = _iso(
        next(c for c in client.get("/api/consultations").json() if c["consult_id"] == "CON-2105")[
            "received_at"
        ]
    )

    response = client.post(
        "/api/events/csv", files={"file": ("judge.csv", io.BytesIO(JUDGE_CSV.encode()))}
    )

    assert response.status_code == 201, response.text
    result = response.json()
    assert (result["received"], result["accepted"], result["duplicates"]) == (8, 6, 2)
    statuses = [(o["event_id"], o["status"], o["visible_now"]) for o in result["outcomes"]]
    assert statuses == [
        ("JDG-0001", "accepted", False),
        ("JDG-0002", "accepted", False),
        ("JDG-0003", "accepted", False),
        ("JDG-0004", "accepted", False),
        ("JDG-0005", "accepted", False),
        ("JDG-0005", "duplicate", False),
        ("EVT-01163", "duplicate", True),
        ("JDG-0006", "accepted", True),
    ]
    after = client.get("/api/simulation").json()
    assert after["data_version"] == before["data_version"] + 1
    assert after["current_time"] == before["current_time"]  # "now" does not jump
    assert client.get("/api/datasets/status").json()["active"]["import_id"] == import_id
    backfilled = client.get("/api/consultations/CON-2118").json()
    assert backfilled["stage"] == "documentation"
    assert _iso(backfilled["stage_entered_at"]) == _et("18:15")

    client.post("/api/simulation/advance", json={"minutes": 10})  # 18:30 ET
    consults = {c["consult_id"]: c for c in client.get("/api/consultations").json()}
    repeat = consults["CON-2105"]
    assert _iso(repeat["received_at"]) == first_2105 == _et("18:07:30")
    assert repeat["seconds_since_received"] == 22 * 60 + 30
    assert "repeat_request" in {a["code"] for a in repeat["anomalies"]}
    assert consults["CON-9001"]["stage"] == "triaged"
    assert consults["CON-9001"]["routing_failures"] == 1
    assert consults["CON-2107"]["stage"] == "note_pending"
    assert _iso(consults["CON-2107"]["stage_entered_at"]) == _et("18:22")
    demand = {h["hospital_id"]: h["current"] for h in client.get("/api/demand").json()["hospitals"]}
    assert demand["SYN-005"]["arrivals"] == 6 and demand["SYN-005"]["spike"] is True
    assert demand["SYN-010"]["arrivals"] == 1  # the repeat call is not new demand
    alerts = {a["alert_id"] for a in client.get("/api/alerts").json()["alerts"]}
    assert "ROUTING_FAILURE:consult:CON-9001" in alerts
    assert "DEMAND_SPIKE:hospital:SYN-005" in alerts
    staffing = client.get("/api/optimization/split-shifts").json()
    assert staffing["data_version"] == after["data_version"]
    interventions = client.get("/api/interventions", headers=COORD).json()["items"]
    assert [(i["id"], i["status"]) for i in interventions] == [
        (proposed.json()["id"], "pending_approval")
    ]
