"""Hand-authored judging file, independent of the existing scenario generators.

Expected behavior is specified from the CSV: eight rows, one duplicate, two distinct
new consults at one hospital, one repeat request, and one future status change.
"""

from pathlib import Path


def test_malformed_status_description_rejects_the_entire_file(client):
    assert client.post("/api/datasets/challenge").status_code == 200
    before = client.get("/api/datasets/status").json()
    csv = Path(__file__).parent / "fixtures" / "judging_rehearsal.csv"
    malformed = csv.read_bytes().replace(b"Self-reported status: ", b"")
    response = client.post(
        "/api/events/csv", files={"file": ("malformed.csv", malformed, "text/csv")}
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "event_invalid"
    after = client.get("/api/datasets/status").json()
    assert after["active"]["import_id"] == before["active"]["import_id"]
    assert after["active"]["counts"]["events"] == before["active"]["counts"]["events"]
    assert client.get("/api/consultations/REHEARSAL-C1").status_code == 404


def test_surprise_file_replays_without_resetting_the_day(client):
    assert client.post("/api/datasets/challenge").status_code == 200
    status = client.get("/api/datasets/status").json()
    before = client.get("/api/simulation").json()
    original = client.get("/api/consultations/CON-2105").json()
    coord = {"X-Demo-Role": "coordinator"}
    proposal = client.post("/api/interventions", headers=coord, json={"type": "split_shift"})
    assert proposal.status_code == 201, proposal.text
    csv = Path(__file__).parent / "fixtures" / "judging_rehearsal.csv"
    response = client.post(
        "/api/events/csv", files={"file": (csv.name, csv.read_bytes(), "text/csv")}
    )
    assert response.status_code == 201, response.text
    result = response.json()
    assert (result["received"], result["accepted"], result["duplicates"]) == (8, 7, 1)
    assert (
        client.get("/api/datasets/status").json()["active"]["import_id"]
        == status["active"]["import_id"]
    )
    assert client.get("/api/simulation").json()["current_time"] == before["current_time"]
    for cid, received in (
        ("REHEARSAL-C1", "2026-03-17T22:18:00Z"),
        ("REHEARSAL-C2", "2026-03-17T22:18:30Z"),
    ):
        consult = client.get(f"/api/consultations/{cid}").json()
        assert consult["stage"] == "triaged"
        assert consult["received_at"] == received
    repeat = client.get("/api/consultations/CON-2105").json()
    assert repeat["received_at"] == original["received_at"]
    assert "repeat_request" in {a["code"] for a in repeat["anomalies"]}
    demand = client.get("/api/demand").json()["hospitals"]
    oak = next(h for h in demand if h["hospital_id"] == "SYN-010")["current"]
    assert oak["arrivals"] == 3  # one original + two distinct, not the repeated request
    assert oak["spike"] is True
    physician = client.get("/api/physicians/PHY-004").json()
    assert physician["availability"] == "unavailable"
    assert client.post("/api/simulation/advance", json={"minutes": 10}).status_code == 200
    physician = client.get("/api/physicians/PHY-004").json()
    assert physician["availability"] == "available"
    alerts = client.get("/api/alerts").json()["alerts"]
    assert any(a["consult_id"] == "REHEARSAL-C1" and a["severity"] == "critical" for a in alerts)
    saved = client.get(f"/api/interventions/{proposal.json()['id']}", headers=coord)
    assert saved.status_code == 200
    assert saved.json()["status"] == "pending_approval"
