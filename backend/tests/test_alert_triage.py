"""Handled alerts leave the ranked queue: a problem whose interventions have all finished,
with at least one completed after the condition began, ranks below every open alert and is
left out of the severity and rule counts (alerts list and metrics alike)."""

from __future__ import annotations

from collections import Counter
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.engines.alert_detection.handled import InterventionRef, handled_by
from app.schemas.alert import Alert
from app.schemas.intervention import InterventionStatus as S
from tests.workflow_helpers import LEAD, decide, load, propose_ok

C220_ALERT = "STAGE_TRIAGED_UNASSIGNED:consult:SRG-C220"


@pytest.fixture
def wf(client: TestClient) -> TestClient:
    return load(client)


def _alerts(client: TestClient) -> dict:
    response = client.get("/api/alerts")
    assert response.status_code == 200, response.text
    return response.json()


def test_without_interventions_every_alert_is_open(wf):
    body = _alerts(wf)
    assert body["open_total"] == body["total"] and body["handled_total"] == 0
    assert all(a["handled_by"] is None for a in body["alerts"])


def test_a_completed_escalation_moves_its_problem_below_the_open_queue(wf):
    before = _alerts(wf)
    created = propose_ok(wf, type="escalation", alert_id=C220_ALERT)

    pending = _alerts(wf)
    assert pending["handled_total"] == 0, "an intervention in flight does not handle the alert"
    assert decide(wf, created["id"]).status_code == 200
    resolved = wf.post(
        f"/api/interventions/{created['id']}/resolve", headers=LEAD, json={"note": "Called"}
    )
    assert resolved.status_code == 200 and resolved.json()["status"] == "completed"

    after = _alerts(wf)
    handled = [a for a in after["alerts"] if a["handled_by"]]
    open_alerts = [a for a in after["alerts"] if not a["handled_by"]]
    # Every alert about the consult is handled by the escalation; nothing disappears.
    assert handled and {a["consult_id"] for a in handled} == {"SRG-C220"}
    assert {a["handled_by"] for a in handled} == {created["id"]}
    assert after["total"] == before["total"]
    assert (after["open_total"], after["handled_total"]) == (len(open_alerts), len(handled))
    # Handled rank last; the open queue keeps its order and is re-numbered from 1.
    assert after["alerts"] == open_alerts + handled
    assert [a["priority"] for a in after["alerts"]] == list(range(1, after["total"] + 1))
    assert [a["alert_id"] for a in open_alerts] == [
        a["alert_id"] for a in before["alerts"] if a["consult_id"] != "SRG-C220"
    ]
    # Counts describe the open queue, and the metrics agree with the list.
    by_severity = Counter(a["severity"] for a in open_alerts)
    assert after["counts_by_severity"] == {
        s: by_severity.get(s, 0) for s in ("critical", "warning", "info")
    }
    assert sum(after["counts_by_rule"].values()) == len(open_alerts)
    metrics = wf.get("/api/metrics").json()
    assert metrics["alerts_by_severity"] == after["counts_by_severity"]
    assert metrics["alerts_by_rule"] == after["counts_by_rule"]
    assert wf.get(f"/api/alerts/{C220_ALERT}").json()["handled_by"] == created["id"]


def test_a_rejected_escalation_leaves_the_alert_open(wf):
    created = propose_ok(wf, type="escalation", alert_id=C220_ALERT)
    assert decide(wf, created["id"], "reject").status_code == 200
    assert _alerts(wf)["handled_total"] == 0


def test_handled_is_judged_at_the_alert_time_and_a_new_occurrence_is_open(wf):
    raw = next(a for a in _alerts(wf)["alerts"] if a["alert_id"] == C220_ALERT)
    alert = Alert.model_validate(raw)
    assert alert.condition_since is not None
    now, since = alert.as_of, alert.condition_since
    later = now + timedelta(minutes=5)

    def ref(status: S, updated, proposed=None, iid: str = "INT-9001") -> InterventionRef:
        return InterventionRef(
            id=iid,
            status=status,
            alert_id=alert.alert_id,
            consult_id=None,
            proposed_at=proposed or updated,
            updated_at=updated,
        )

    assert handled_by(alert, [ref(S.COMPLETED, now)]) == "INT-9001"
    # Linked by consult alone (e.g. raised from the consult's routing-failure alert).
    by_consult = InterventionRef("INT-9002", S.COMPLETED, None, "SRG-C220", now, now)
    assert handled_by(alert, [by_consult]) == "INT-9002"
    # Completed before the condition began: this is a new occurrence.
    assert handled_by(alert, [ref(S.COMPLETED, since - timedelta(minutes=1))]) is None
    # Anything still in flight keeps it open, even beside a completed one.
    in_flight = ref(S.PENDING_APPROVAL, now, iid="INT-9003")
    assert handled_by(alert, [ref(S.COMPLETED, now), in_flight]) is None
    # Not proposed yet at the alert time, or finished only after it.
    assert handled_by(alert, [ref(S.COMPLETED, later, proposed=later)]) is None
    assert handled_by(alert, [ref(S.COMPLETED, later, proposed=now)]) is None
    # Finished without completing (rejected, cancelled, ...) is not handled.
    assert handled_by(alert, [ref(S.REJECTED, now)]) is None
