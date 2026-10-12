"""The surge fixture over HTTP, checked against expectations worked out by hand.

Reference time 2030-09-10 22:35Z (18:35 EDT). Derivations (see scripts/generate_surge_dataset.py):

SRG-H1 (NY). Block 07-19 EDT needs 2, 19-07 needs 1. Arrivals 21:50, 22:05, 22:15, 22:25Z.
  22:35  4 in (21:35, 22:35] > p90(18h)=2.0 -> spike; R = 2+1 = 3. P1, P2, P3 on shift -> A 3.
  22:50  21:50 leaves -> 3 > 2.0, still spike.          R 3, A 3.
  23:00  19:00 EDT: base 1; 3 in (22:00, 23:00] > p90(19h)=1.5 -> R 2. P1, P2 end -> A 1. D 1.
  23:05  22:05 leaves -> 2 > 1.5 -> R 2, A 1, D 1.
  23:15  22:15 leaves -> 1 <= 1.5 -> R 1, A 1, D 0.
  23:30  P5's roster start -> A 2 (end unknown: uncertain).
  => first gap 23:00Z, 15 min, 15 physician-minutes; spike ends 23:15Z.
SRG-H2 (LA). R 1. P1 (shared with H1) until 23:00Z; P4 Temporarily Unavailable -> excluded.
  => gap 23:00Z to 00:05Z = 65 physician-minutes.
SRG-H3 (Chicago). R 1, nobody credentialed on shift, no baseline rows -> deficit 1 x 90 = 90.
Candidates: P5 online 22:45 covers H1's gap (15); P6 online 22:55 -> H3 70; P7 online 23:05
  -> H2 60 and H3 60.
"""

from __future__ import annotations

import filecmp

import pytest

from scripts.generate_surge_dataset import write_dataset
from tests.conftest import SAMPLE_DIR

SURGE = SAMPLE_DIR.parent / "synthetic_surge"


@pytest.fixture
def surge(make_client, tmp_path):
    """Capacity only (the derivations above): stranded strokes are not counted."""
    policy = tmp_path / "policy.json"
    policy.write_text('{"staffing": {"stranded_urgent_categories": []}}', encoding="utf-8")
    with make_client(optimization_policy_file=policy) as client:
        response = client.post("/api/datasets/sample", params={"name": "synthetic_surge"})
        assert response.status_code == 200, response.text
        yield client


def test_stranded_strokes_count_as_one_more_physician_needed_now(client):
    """Default policy: SRG-C204 (H1: Quinn, Reese, Sawyer all busy) and SRG-C210 (H2: its
    doctor Temporarily Unavailable, Quinn busy) cannot be placed, so each hospital needs one
    physician beyond those on duty (A 3 -> R 4 at H1, A 1 -> R 2 at H2) from now."""
    assert (
        client.post("/api/datasets/sample", params={"name": "synthetic_surge"}).status_code == 200
    )
    report = {h["hospital_id"]: h for h in client.get("/api/coverage").json()["hospitals"]}
    rows = {
        hid: (h["stranded_consult_ids"], h["metrics"]["required_now"], h["metrics"]["deficit_now"])
        for hid, h in report.items()
    }
    assert rows["SRG-H1"] == (["SRG-C204"], 4, 1)
    assert rows["SRG-H2"] == (["SRG-C210"], 2, 1)
    assert rows["SRG-H3"][0] == []  # General Neuro SRG-C220 is not an urgent category


def _coverage(client, hid, **params):
    return client.get(f"/api/coverage/{hid}", params=params).json()


def test_samples_are_listed(client):
    names = [s["name"] for s in client.get("/api/datasets/samples").json()]

    assert names == [
        "synthetic_dev",
        "synthetic_staffing",
        "synthetic_surge",
        "synthetic_workflow",  # Phase 5 demo sample (surge + backup + gap-free hospital)
    ]


def test_surge_coverage_matches_hand_calculation(surge):
    h1 = _coverage(surge, "SRG-H1")
    simplified = [
        (s["start"][11:19], s["end"][11:19], s["required"], s["available"], s["deficit"])
        for s in h1["segments"]
    ]

    assert simplified == [
        ("22:35:00", "23:00:00", 3, 3, 0),
        ("23:00:00", "23:15:00", 2, 1, 1),
        ("23:15:00", "23:30:00", 1, 1, 0),
        ("23:30:00", "00:05:00", 1, 2, 0),
    ]
    assert h1["metrics"]["first_shortfall_at"] == "2030-09-10T23:00:00Z"
    assert h1["metrics"]["deficit_physician_minutes"] == 15
    assert _coverage(surge, "SRG-H2")["metrics"]["deficit_physician_minutes"] == 65
    h3 = _coverage(surge, "SRG-H3")["metrics"]
    assert (h3["deficit_now"], h3["deficit_physician_minutes"]) == (1, 90)


def test_surge_explanations_name_the_causes(surge):
    text = " ".join(_coverage(surge, "SRG-H1")["explanations"])

    assert "Dr. Quinn Surge and Dr. Reese Surge's shifts end at 19:00 EDT" in text
    assert "exceeds this hospital's p90 baseline (2)" in text
    assert "additional qualified physician is required under the demand-spike rule" in text
    assert "Demand-spike adjustment ends at 19:15 EDT" in text
    assert "cannot count toward Northgate Sample Hospital" in text
    assert "shift end unknown" in text


def test_surge_demand_report(surge):
    by_id = {h["hospital_id"]: h for h in surge.get("/api/demand").json()["hospitals"]}

    h1 = by_id["SRG-H1"]
    assert (h1["current"]["arrivals"], h1["current"]["baseline_p90"], h1["current"]["spike"]) == (
        4,
        2.0,
        True,
    )
    assert h1["current"]["consult_ids"] == ["SRG-C201", "SRG-C202", "SRG-C203", "SRG-C204"]
    assert h1["spike_ends_at"] == "2030-09-10T23:15:00Z"
    assert by_id["SRG-H3"]["current"]["baseline_status"] == "missing"
    assert by_id["SRG-H3"]["current"]["spike"] is None


def test_surge_alerts_and_ranking(surge):
    body = surge.get("/api/alerts").json()
    ids = [a["alert_id"] for a in body["alerts"]]

    assert body["counts_by_severity"] == {"critical": 5, "warning": 9, "info": 1}
    # Hand-derived order of the critical alerts (see rank.py for the key).
    assert ids[:5] == [
        "STAGE_ASSIGNED_NOT_CONTACTED:consult:SRG-C210",
        "ASSIGNED_PHYSICIAN_UNAVAILABLE:consult:SRG-C210",
        "COVERAGE_GAP_NOW:hospital:SRG-H3",
        "STAGE_TRIAGED_UNASSIGNED:consult:SRG-C220",
        "OPEN_NOTES_NEAR_SHIFT_END:physician:SRG-P1",
    ]
    assert set(ids[5:]) == {
        "STAGE_IMAGING_PENDING:consult:SRG-C203",
        "ROUTING_FAILURE:consult:SRG-C204",
        "STAGE_TRIAGED_UNASSIGNED:consult:SRG-C204",
        "ROUTING_FAILURE:consult:SRG-C220",
        "NOTE_OVERDUE:consult:SRG-C200",
        "COVERAGE_GAP_PROJECTED:hospital:SRG-H1",
        "COVERAGE_GAP_PROJECTED:hospital:SRG-H2",
        "OPEN_NOTES_NEAR_SHIFT_END:physician:SRG-P2",
        "DEMAND_SPIKE:hospital:SRG-H1",
        "SIGNAL_EXTERNAL_VIDEO:physician:SRG-P2",
    }
    projected = next(
        a for a in body["alerts"] if a["alert_id"] == "COVERAGE_GAP_PROJECTED:hospital:SRG-H1"
    )
    assert projected["minutes_to_impact"] == 25
    assert projected["recommended_action_type"] == "propose_split_shift"


def test_candidate_coverage_effects(surge):
    body = surge.get("/api/optimization/input").json()
    effects = {
        c["physician_id"]: {e["hospital_id"]: e["reduction"] for e in c["effects"]}
        for c in body["candidate_interventions"]
    }

    assert effects == {
        "SRG-P5": {"SRG-H1": 15},
        "SRG-P6": {"SRG-H3": 70},
        "SRG-P7": {"SRG-H2": 60, "SRG-H3": 60},
    }
    assert all(not c["eligibility_evaluated"] for c in body["candidate_interventions"])


def test_metrics_summary(surge):
    metrics = surge.get("/api/metrics").json()

    assert metrics["coverage"]["gap_now"] == 1
    assert metrics["coverage"]["gap_projected"] == 2
    assert metrics["coverage"]["deficit_physician_minutes_total"] == 15 + 65 + 90
    assert metrics["earliest_projected_gap_at"] == "2030-09-10T23:00:00Z"
    assert metrics["demand"]["hospitals_spiking"] == 1
    assert "not measured patient outcomes" in metrics["disclaimer"]


# 14. Events ingested after the simulation time do not leak ------------------------------


def test_after_reference_events_only_count_once_visible(surge):
    at_ref = {h["hospital_id"]: h for h in surge.get("/api/demand").json()["hospitals"]}
    later = {
        h["hospital_id"]: h
        for h in surge.get("/api/demand", params={"as_of": "2030-09-10T22:45:00Z"}).json()[
            "hospitals"
        ]
    }

    # SRG-C205 (received 22:40) is invisible at 22:35 and visible at 22:45.
    assert "SRG-C205" not in at_ref["SRG-H1"]["current"]["consult_ids"]
    assert "SRG-C205" in later["SRG-H1"]["current"]["consult_ids"]


# 15. Injected events update alerts and projections without restart -----------------------


def test_injection_updates_alerts_and_coverage(surge):
    before = _coverage(surge, "SRG-H1")["metrics"]
    assert before["deficit_now"] == 0

    response = surge.post(
        "/api/events",
        json=[
            # P2 (camera-busy, R5) -> Temporarily Unavailable (R4 outranks R5). Not P3: an
            # active Synapse call (R1) would still outrank the status.
            {
                "event_id": "LIVE-TU",
                "event_type": "physician_status_changed",
                "event_time": "2030-09-10T18:34:30-04:00",
                "physician_id": "SRG-P2",
                "status": "Temporarily Unavailable",
            },
            {
                "event_id": "LIVE-STROKE",
                "event_type": "consult_received",
                "event_time": "2030-09-10T18:34:50-04:00",
                "consult_id": "LIVE-C1",
                "hospital_id": "SRG-H1",
                "consult_type": "Stroke",
            },
        ],
    )
    assert response.status_code == 201, response.text

    after = _coverage(surge, "SRG-H1")["metrics"]
    alert_ids = {a["alert_id"] for a in surge.get("/api/alerts").json()["alerts"]}
    demand = {h["hospital_id"]: h for h in surge.get("/api/demand").json()["hospitals"]}

    assert (after["required_now"], after["available_now"], after["deficit_now"]) == (3, 2, 1)
    assert "COVERAGE_GAP_NOW:hospital:SRG-H1" in alert_ids
    assert "COVERAGE_GAP_PROJECTED:hospital:SRG-H1" not in alert_ids
    assert demand["SRG-H1"]["current"]["arrivals"] == 5


def test_clock_advance_reveals_early_shift_start_that_covers_the_gap(surge):
    surge.post("/api/simulation/advance", json={"minutes": 30})  # 23:05Z = 19:05 EDT
    alerts = {a["alert_id"]: a for a in surge.get("/api/alerts").json()["alerts"]}
    h1 = _coverage(surge, "SRG-H1")

    # After-reference events are now visible: C204 assigned at 22:39 (triage alert gone, and
    # still not contacted 26 min later -> critical), and P5 started early at 22:50.
    assert "STAGE_TRIAGED_UNASSIGNED:consult:SRG-C204" not in alerts
    assert alerts["STAGE_ASSIGNED_NOT_CONTACTED:consult:SRG-C204"]["severity"] == "critical"
    # P1/P2 ended at 23:00Z. Arrivals now known: 21:50, 22:05, 22:15, 22:25 and SRG-C205 at
    # 22:40. Window (t-60, t] vs p90 1.5: 23:05 -> 3, 23:15 -> 2, 23:25 -> 1. So R = 2 until
    # 23:25Z, then 1. A = P3 (confirmed) + P5 (uncertain: end unknown) -> no deficit, but
    # confirmed-only coverage is short 1 from 23:05 to 23:25 = 20 physician-minutes.
    m = h1["metrics"]
    assert (m["required_now"], m["available_now"], m["deficit_now"]) == (2, 2, 0)
    assert m["deficit_physician_minutes_if_uncertain_excluded"] == 20
    p5 = next(c for c in h1["contributors"] if c["physician_id"] == "SRG-P5")
    assert p5["status"] == "counted" and p5["certainty"] == "uncertain"
    assert "COVERAGE_GAP_PROJECTED:hospital:SRG-H1" not in alerts


# 17. Switching datasets removes stale alerts and projections ---------------------------


def test_switching_dataset_removes_stale_results(surge):
    assert any("SRG-" in a["alert_id"] for a in surge.get("/api/alerts").json()["alerts"])

    assert surge.post("/api/datasets/sample").status_code == 200  # back to synthetic_dev
    alerts = surge.get("/api/alerts").json()["alerts"]
    hospitals = [h["hospital_id"] for h in surge.get("/api/coverage").json()["hospitals"]]

    assert not any("SRG-" in a["alert_id"] for a in alerts)
    assert hospitals == ["DEV-H01", "DEV-H02", "DEV-H03", "DEV-H04", "DEV-H05"]


# 19. API errors keep the standard envelope ------------------------------------------------


def _envelope(response, status, code):
    assert response.status_code == status, response.text
    body = response.json()
    assert set(body) == {"error"} and body["error"]["code"] == code
    return body["error"]


def test_analysis_errors_use_standard_envelope(client):
    _envelope(client.get("/api/alerts"), 409, "no_dataset")
    _envelope(client.get("/api/coverage"), 409, "no_dataset")
    client.post("/api/datasets/sample")
    _envelope(client.get("/api/coverage/NOPE"), 404, "not_found")
    _envelope(client.get("/api/alerts/NOPE"), 404, "not_found")
    _envelope(
        client.get("/api/alerts", params={"as_of": "2030-05-14T21:30:00"}), 422, "validation_error"
    )
    _envelope(client.get("/api/coverage", params={"horizon_minutes": 30}), 422, "validation_error")
    error = _envelope(
        client.post("/api/datasets/sample", params={"name": "../etc"}), 404, "not_found"
    )
    assert error["details"]["available"] == [
        "synthetic_dev",
        "synthetic_staffing",
        "synthetic_surge",
        "synthetic_workflow",
    ]


def test_alert_filters_and_lookup(surge):
    critical = surge.get("/api/alerts", params={"severity": "critical"}).json()["alerts"]
    one = surge.get("/api/alerts/DEMAND_SPIKE:hospital:SRG-H1").json()

    assert {a["severity"] for a in critical} == {"critical"}
    assert [a["priority"] for a in critical] == [1, 2, 3, 4, 5]  # global priorities kept
    assert one["rule_source"] == "challenge_brief" and one["evidence"]


def test_analysis_is_cached_per_data_version_and_time(surge):
    first = surge.get("/api/alerts").json()
    second = surge.get("/api/alerts").json()

    assert first == second


def test_surge_fixture_generator_is_reproducible(tmp_path):
    write_dataset(tmp_path)
    names = sorted(p.name for p in SURGE.iterdir() if p.suffix in {".csv", ".json", ".md"})
    _, mismatch, errors = filecmp.cmpfiles(SURGE, tmp_path, names, shallow=False)

    assert mismatch == [] and errors == [], "committed surge fixture is stale: regenerate it"
