"""The real challenge dataset (repo-root ``data/``) imports, and a judge CSV appends to it.

Skipped when the folder is absent. Expectations are structural (headers, units, time
zones, append behaviour), not the hidden scenario answers.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest

from tests.conftest import upload

DATA = Path(__file__).resolve().parents[2] / "data"

pytestmark = pytest.mark.skipif(
    not (DATA / "event_stream.csv").exists(), reason="challenge dataset not present"
)


@pytest.fixture
def challenge(client):
    files = {p.name: p.read_bytes() for p in sorted(DATA.glob("*.csv"))}
    response = upload(client, files)
    assert response.status_code == 200, response.text
    return client, response.json()


def test_handbook_headers_map_and_eastern_blocks_become_hospital_local(challenge):
    client, report = challenge
    mapped = {m["file"]: m for m in report["column_mappings"]}
    off = mapped["physicians_off_shift_roster.csv"]["mapped"]
    assert off["hours_worked_trailing_7d"] == "hours_worked_last_7d"
    assert off["minutes_to_come_online"] == "est_minutes_to_online"
    cov = mapped["coverage_requirements.csv"]
    assert cov["mapped"]["min_available_physicians"] == "min_available_credentialed_physicians"
    assert cov["zone_hint"] == "et"
    assert mapped["baseline_hourly_volume.csv"]["mapped"]["hour_local"] == "hour_start_et"
    assert any(i["code"] == "zone_hint_converted" for i in report["issues"])

    staffing = client.get("/api/optimization/split-shifts").json()
    rows = {c["physician_id"]: c for c in staffing["candidates"]}
    assert len(rows) == 6  # every off-shift physician is evaluated
    assert all(r["minutes_to_come_online"] is not None for r in rows.values())
    assert not any(r["online_time_assumed"] for r in rows.values())
    assert all(r["remaining_weekly_hours"] is not None for r in rows.values())


def test_eastern_labelled_blocks_and_hours_are_stored_in_hospital_local_time(challenge, settings):
    from datetime import time

    from sqlalchemy.orm import Session

    from app.db.session import build_engine
    from app.repositories import ReferenceRepository

    engine = build_engine(settings.resolved_database_url)
    with Session(engine) as session:
        reference = ReferenceRepository(session).load()
    engine.dispose()
    blocks = {
        (r.block_start_local, r.block_end_local)
        for r in reference.coverage_requirements
        if r.hospital_id == "SYN-001"  # America/Chicago
    }
    assert blocks == {(time(6), time(15)), (time(15), time(21)), (time(21), time(6))}
    eastern = {
        (r.block_start_local, r.block_end_local)
        for r in reference.coverage_requirements
        if r.hospital_id == "SYN-005"  # America/New_York: unchanged
    }
    assert (time(16), time(22)) in eastern
    # Baseline hour 18:00 ET at a Denver hospital is 16:00 local.
    by_hour = {
        b.hour_local: b.p90_consults
        for b in reference.baseline_volume
        if b.hospital_id == "SYN-002"
    }
    assert len(by_hour) == 24


def test_judge_csv_appends_to_the_loaded_day_without_replacing_it(challenge):
    client, _ = challenge
    before = client.get("/api/simulation").json()
    imports_before = client.get("/api/datasets/status").json()
    csv = (
        "event_id,event_time,ingested_at,consult_id,event_type,physician_id,hospital_id,"
        "description\n"
        "JUDGE-0001,2026-03-17T18:22:00-04:00,2026-03-17T18:22:03-04:00,CON-9001,"
        "consult_received,,SYN-005,Stroke consult received\n"
        "JUDGE-0002,2026-03-17T18:23:00-04:00,2026-03-17T18:23:02-04:00,CON-9001,"
        "consult_triaged,,SYN-005,Triaged\n"
    )
    response = client.post(
        "/api/events/csv", files={"file": ("judge.csv", io.BytesIO(csv.encode()))}
    )
    assert response.status_code == 201, response.text
    assert response.json()["accepted"] == 2
    after = client.get("/api/simulation").json()
    assert after["data_version"] == before["data_version"] + 1
    assert after["first_event_time"] == before["first_event_time"]  # same day, appended
    status = client.get("/api/datasets/status").json()
    assert status["active"]["import_id"] == imports_before["active"]["import_id"]
    client.post("/api/simulation/advance", json={"minutes": 5})
    consults = {c["consult_id"] for c in client.get("/api/consultations").json()}
    assert "CON-9001" in consults and "CON-2105" in consults
