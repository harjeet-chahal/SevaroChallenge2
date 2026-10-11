"""NEUROGRID API: chaos isolation, import preview, monotonic clock, rescue verification."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.conftest import upload

DATA = Path(__file__).resolve().parents[2] / "data"
WORKFLOW = Path(__file__).resolve().parents[1] / "sample_data" / "synthetic_workflow"
COORD = {"X-Demo-Role": "coordinator", "X-Demo-Actor-Id": "coord-1"}
LEAD = {"X-Demo-Role": "clinical_lead", "X-Demo-Actor-Id": "lead-1"}
HEADER = (
    "event_id,event_time,ingested_at,consult_id,event_type,physician_id,hospital_id,description\n"
)

ENDPOINTS = [
    "availability",
    "problems",
    "time-machine",
    "last-safe-moment",
    "fragility",
    "genome",
    "scarcity",
    "coverage-debt",
    "handoff",
    "simulate",
    "load-guardian",
    "evaluation",
]


def _client(tmp: Path, folder: Path) -> TestClient:
    settings = Settings(
        _env_file=None, app_env="test", database_url=f"sqlite:///{tmp / 'n.db'}", cors_origins=""
    )
    client = TestClient(create_app(settings))
    client.__enter__()
    files = {p.name: p.read_bytes() for p in folder.iterdir() if p.is_file()}
    assert upload(client, files).status_code == 200
    return client


@pytest.fixture
def wf(tmp_path):
    client = _client(tmp_path, WORKFLOW)
    yield client
    client.__exit__(None, None, None)


def test_every_intelligence_endpoint_answers(wf):
    for ep in ENDPOINTS:
        r = wf.get(f"/api/intelligence/{ep}")
        assert r.status_code == 200, (ep, r.text)
        assert r.json()["data_version"] == wf.get("/api/config").json()["data_version"]


def test_time_machine_only_now_is_observed_and_boundaries_are_exact(wf):
    tm = wf.get("/api/intelligence/time-machine").json()
    frames = tm["frames"]
    assert frames[0]["kind"] == "now" and frames[0]["observed"]
    assert all(not f["observed"] for f in frames[1:])
    assert frames[-1]["kind"] == "horizon_end"
    assert [f["at"] for f in frames] == sorted(f["at"] for f in frames)
    cov = wf.get("/api/coverage").json()
    for h in cov["hospitals"]:
        for seg in h["segments"]:
            if seg["start"] > cov["as_of"]:
                assert any(f["at"] == seg["start"] for f in frames), "exact change point kept"
    bands = tm["demand"]
    assert all(
        b["p10_trailing_hour"] <= b["p50_trailing_hour"] <= b["p90_trailing_hour"] for b in bands
    )
    again = wf.get("/api/intelligence/time-machine", params={"rate_multiplier": 1.0}).json()
    assert again["demand"] == bands  # seeded: reproducible


def test_chaos_runs_on_a_branch_and_never_touches_the_baseline(wf):
    before = wf.get("/api/config").json()
    events_before = wf.get("/api/events", params={"limit": 1}).json()["total"]
    scenarios = wf.get("/api/chaos/scenarios").json()
    assert len(scenarios) >= 14
    for sc in scenarios:
        r = wf.post(f"/api/chaos/run/{sc['scenario_id']}", headers=COORD)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["baseline_unchanged"] is True
        assert body["assertions"], sc
    after = wf.get("/api/config").json()
    assert after["data_version"] == before["data_version"]
    assert after["workflow_version"] == before["workflow_version"]
    assert after["simulation_time"] == before["simulation_time"]
    assert wf.get("/api/events", params={"limit": 1}).json()["total"] == events_before


def test_chaos_requires_staff_role(wf):
    r = wf.post(
        "/api/chaos/run/surge_single",
        headers={"X-Demo-Role": "physician", "X-Demo-Actor-Id": "x"},
    )
    assert r.status_code == 403


def test_import_preview_changes_nothing_then_apply_advances_clock_monotonically(wf):
    cfg = wf.get("/api/config").json()
    now = cfg["simulation_time"]
    hospital = wf.get("/api/coverage").json()["hospitals"][0]["hospital_id"]
    from datetime import datetime, timedelta

    t = datetime.fromisoformat(now.replace("Z", "+00:00"))
    later = (t + timedelta(minutes=7)).isoformat()
    earlier = (t - timedelta(minutes=30)).isoformat()
    csv = (
        HEADER
        + f"NG-1,{later},{later},NG-C1,consult_received,,{hospital},Stroke consult received\n"
        + f"NG-2,{earlier},{later},NG-C2,consult_received,,{hospital},General consult received\n"
    )
    preview = wf.post(
        "/api/events/csv/preview",
        params={"advance_clock": True},
        files={"file": ("judge.csv", io.BytesIO(csv.encode()))},
    )
    assert preview.status_code == 200, preview.text
    p = preview.json()
    assert p["valid"] and p["accepted"] == 2
    assert p["clock_after"] > p["clock_before"]
    assert wf.get("/api/config").json()["data_version"] == cfg["data_version"]  # untouched

    applied = wf.post(
        "/api/events/csv",
        params={"advance_clock": True},
        files={"file": ("judge.csv", io.BytesIO(csv.encode()))},
    )
    assert applied.status_code == 201, applied.text
    body = applied.json()
    assert body["clock_before"].startswith(now[:19])
    after = wf.get("/api/config").json()
    assert after["simulation_time"] > now
    assert all(o["visible_now"] for o in body["outcomes"])
    consults = {c["consult_id"] for c in wf.get("/api/consultations").json()}
    assert {"NG-C1", "NG-C2"} <= consults

    # a later, late-only import never moves time backward
    old = (t - timedelta(minutes=50)).isoformat()
    late = HEADER + f"NG-3,{old},{old},NG-C3,consult_received,,{hospital},Late consult\n"
    r = wf.post(
        "/api/events/csv",
        params={"advance_clock": True},
        files={"file": ("late.csv", io.BytesIO(late.encode()))},
    )
    assert r.status_code == 201
    assert wf.get("/api/config").json()["simulation_time"] == after["simulation_time"]


def test_invalid_preview_reports_rows_and_stores_nothing(wf):
    before = wf.get("/api/events", params={"limit": 1}).json()["total"]
    bad = HEADER + "NG-X,not-a-time,,,consult_received,,,broken\n"
    r = wf.post("/api/events/csv/preview", files={"file": ("bad.csv", io.BytesIO(bad.encode()))})
    assert r.status_code == 200
    assert r.json()["valid"] is False and r.json()["errors"]
    assert wf.get("/api/events", params={"limit": 1}).json()["total"] == before
    r = wf.post("/api/events/csv/preview", files={"file": ("bad.txt", io.BytesIO(b"x"))})
    assert r.status_code == 422


def test_rescue_contract_is_verified_only_after_activation(wf):
    sim = wf.get("/api/intelligence/simulate").json()
    rec = next(o for o in sim["options"] if o["recommended"])
    assert rec["kind"] == "split_shift", rec
    body = rec["proposal"]
    iv = wf.post("/api/interventions", headers=COORD, json=body)
    assert iv.status_code == 201, iv.text
    iid = iv.json()["id"]
    v = wf.get(f"/api/rescue-contracts/{iid}/verification", headers=COORD).json()
    assert v["contract_phase"] == "AWAITING_APPROVAL" and v["verdict"] == "pending"
    assert (
        wf.post(
            f"/api/interventions/{iid}/decision", headers=LEAD, json={"decision": "approve"}
        ).status_code
        == 200
    )
    assert wf.post(f"/api/interventions/{iid}/send-offers", headers=LEAD).status_code == 200
    pid = body["physician_ids"][0]
    doc = {"X-Demo-Role": "physician", "X-Demo-Actor-Id": pid}
    offer = wf.get("/api/offers/mine", headers=doc).json()[0]
    assert (
        wf.post(
            f"/api/offers/{offer['id']}/respond", headers=doc, json={"response": "accept"}
        ).status_code
        == 200
    )
    v = wf.get(f"/api/rescue-contracts/{iid}/verification", headers=COORD).json()
    assert v["verdict"] == "pending", "accepted is not online: no recovery claimed"
    assert v["contract_phase"] == "ACTIVATION_PENDING"
    wf.post("/api/simulation/advance", json={"minutes": 60})
    v = wf.post(f"/api/rescue-contracts/{iid}/verify", headers=COORD).json()
    assert v["verdict"] in ("resolved", "partially_resolved")
    assert v["target_deficit_physician_minutes"] <= v["baseline_deficit_physician_minutes"]
    audit = wf.get(f"/api/interventions/{iid}/audit", headers=COORD).json()["items"]
    assert any(e["action"] == "contract_verified" for e in audit)
    phases = wf.get("/api/rescue-contracts/phases", headers=COORD).json()
    assert phases[iid] in ("ACTIVE", "RESOLVED")
    r = wf.get(f"/api/rescue-contracts/{iid}/verification", headers=doc)
    assert r.status_code == 403


@pytest.mark.skipif(not (DATA / "event_stream.csv").exists(), reason="no official data")
def test_official_chaos_suite_passes(tmp_path):
    client = _client(tmp_path, DATA)
    try:
        for sc in client.get("/api/chaos/scenarios").json():
            body = client.post(f"/api/chaos/run/{sc['scenario_id']}", headers=COORD).json()
            failed = [a for a in body["assertions"] if not a["passed"]]
            assert body["passed"], (sc["scenario_id"], failed)
    finally:
        client.__exit__(None, None, None)
