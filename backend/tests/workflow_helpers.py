"""Helpers for the Phase 5 workflow tests (HTTP level, isolated test databases)."""

from __future__ import annotations

from fastapi.testclient import TestClient

COORD = {"X-Demo-Role": "coordinator", "X-Demo-Actor-Id": "coord-1"}
LEAD = {"X-Demo-Role": "clinical_lead", "X-Demo-Actor-Id": "lead-1"}

WORKFLOW = "synthetic_workflow"
REF = "2030-09-10T22:35:00Z"
"""Reference time of the surge/workflow samples (18:35 EDT)."""
RIDGE, LAKESHORE = "SRG-H3", "SRG-H4"
VALE, YARA = "SRG-P6", "SRG-P8"
"""Ridge has nobody credentialed on shift; Dr. Vale Surge is the recommended split shift
(online 20 min after start), Dr. Yara Surge an eligible backup (35 min)."""
RIDGE_GAP_ALERT = "COVERAGE_GAP_NOW:hospital:SRG-H3"


def doctor(pid: str) -> dict[str, str]:
    return {"X-Demo-Role": "physician", "X-Demo-Actor-Id": pid}


def load(client: TestClient, name: str = WORKFLOW) -> TestClient:
    response = client.post("/api/datasets/sample", params={"name": name})
    assert response.status_code == 200, response.text
    return client


def propose(client: TestClient, **body):
    body.setdefault("type", "split_shift")
    if body["type"] == "split_shift":
        body.setdefault("alert_id", RIDGE_GAP_ALERT)
    return client.post("/api/interventions", headers=COORD, json=body)


def propose_ok(client: TestClient, **body) -> dict:
    response = propose(client, **body)
    assert response.status_code == 201, response.text
    return response.json()


def decide(client: TestClient, iid: str, decision: str = "approve", headers=LEAD, **body):
    return client.post(
        f"/api/interventions/{iid}/decision", headers=headers, json={"decision": decision, **body}
    )


def send(client: TestClient, iid: str, headers=COORD):
    return client.post(f"/api/interventions/{iid}/send-offers", headers=headers)


def offers_sent(client: TestClient, **body) -> tuple[dict, dict[str, dict]]:
    """Propose, approve and send; returns (intervention, physician_id -> offer)."""
    created = propose_ok(client, **body)
    assert decide(client, created["id"]).status_code == 200
    response = send(client, created["id"])
    assert response.status_code == 200, response.text
    sent = response.json()
    return sent, {o["physician_id"]: o for o in sent["offers"]}


def respond(client: TestClient, offer_id: str, pid: str, response: str = "accept"):
    return client.post(
        f"/api/offers/{offer_id}/respond", headers=doctor(pid), json={"response": response}
    )


def advance(client: TestClient, minutes: float):
    response = client.post("/api/simulation/advance", json={"minutes": minutes})
    assert response.status_code == 200, response.text
    return response.json()


def intervention(client: TestClient, iid: str) -> dict:
    response = client.get(f"/api/interventions/{iid}", headers=COORD)
    assert response.status_code == 200, response.text
    return response.json()


def audit(client: TestClient, iid: str) -> list[dict]:
    items = client.get(f"/api/interventions/{iid}/audit", headers=COORD).json()["items"]
    return list(reversed(items))


def physician(client: TestClient, pid: str) -> dict:
    return client.get(f"/api/physicians/{pid}").json()


def coverage(client: TestClient, hid: str) -> dict:
    return client.get(f"/api/coverage/{hid}").json()


def contributor(client: TestClient, hid: str, pid: str) -> dict | None:
    return next(
        (c for c in coverage(client, hid)["contributors"] if c["physician_id"] == pid), None
    )


def data_version(client: TestClient) -> int:
    return client.get("/api/config").json()["data_version"]
