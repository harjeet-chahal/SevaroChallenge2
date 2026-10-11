"""Phase 5: human-in-the-loop intervention workflow over HTTP (isolated test databases).

Scenario: ``synthetic_workflow`` = the surge sample plus a backup candidate and a busy
hospital without a gap. At 18:35 EDT (22:35Z) Ridge (SRG-H3) has nobody credentialed on
shift. Dr. Vale Surge (SRG-P6, online 20 min after start) is the optimizer's split shift,
22:35–02:35Z; Dr. Yara Surge (SRG-P8, online 35 min) is eligible but not needed. Vale is
also credentialed at Lakeshore (SRG-H4), which has no gap, so trap protection must keep
Vale's routing on Ridge only.

Numbered comments map to the mandatory Phase 5 test list.
"""

from __future__ import annotations

import io
import json
import threading
from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import OfferRecord
from app.engines.interventions import find_disallowed
from app.repositories.workflow import WorkflowRepository
from tests.workflow_helpers import (
    COORD,
    LAKESHORE,
    LEAD,
    REF,
    RIDGE,
    RIDGE_GAP_ALERT,
    VALE,
    YARA,
    advance,
    audit,
    contributor,
    coverage,
    data_version,
    decide,
    doctor,
    intervention,
    load,
    offers_sent,
    physician,
    propose,
    propose_ok,
    respond,
    send,
)


@pytest.fixture
def wf(client: TestClient) -> TestClient:
    return load(client)


def _iso(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# 1. Coordinator can propose; a split shift becomes a pending clinical approval -----------


def test_coordinator_proposes_split_shift_as_pending_approval_without_contacting_anyone(wf):
    preview = wf.post(
        "/api/interventions/preview",
        headers=COORD,
        json={"type": "split_shift", "alert_id": RIDGE_GAP_ALERT},
    ).json()
    assert preview["valid"] and preview["intervention"]["id"] == "PREVIEW"

    created = propose_ok(wf, rationale="Ridge has no credentialed physician on shift")

    assert created["status"] == "pending_approval"
    assert created["allowed_actions"] == ["cancel"]  # coordinators cannot approve
    (plan,) = created["offer_plan"]
    assert (plan["physician_id"], plan["start_at"], plan["duration_minutes"]) == (
        VALE,
        REF,
        240,
    )
    assert plan["expected_online_at"] == "2030-09-10T22:55:00Z"
    assert plan["coverage_minutes"] == 220
    assert plan["routing_scope_hospital_ids"] == [RIDGE]
    assert plan["excluded_credentialed_hospital_ids"] == [LAKESHORE]
    assert all(check["passed"] for check in plan["checks"])
    # Every off-shift physician is evaluated, with a reason for each.
    rows = {c["physician_id"]: c for c in created["candidates"]}
    assert set(rows) == {"SRG-P5", "SRG-P6", "SRG-P7", "SRG-P8"}
    assert rows["SRG-P5"]["failed_rules"] == ["no_overlap"]
    assert rows["SRG-P7"]["failed_rules"] == ["opt_in"]
    assert rows[YARA]["eligible"] and "Not needed" in rows[YARA]["summary"]
    # What is wrong, impact and the algorithm are recorded.
    assert created["problem"]["rule_code"] == "COVERAGE_GAP_NOW"
    assert created["problem"]["severity"] == "critical"
    assert created["impact"]["hospitals"][0]["deficit_before"] == 90
    assert created["impact"]["hospitals"][0]["deficit_after"] == 20
    assert "not confirmed" in created["impact"]["label"]
    assert "CP-SAT" in created["recommendation"]["algorithm"]
    assert created["recommendation"]["approver_role"] == "clinical_lead"
    assert created["trap"]["protected"]["routed_to_joiner_elsewhere"] == 0
    # Nobody has been contacted.
    assert created["offers"] == []
    assert wf.get("/api/offers/mine", headers=doctor(VALE)).json() == []
    assert wf.get("/api/config").json()["pending_approvals"] == 1
    actions = [e["action"] for e in audit(wf, created["id"])]
    assert actions == ["intervention_proposed", "approval_requested"]


# 2. Unapproved shift offers cannot be sent -----------------------------------------------


def test_offers_cannot_be_sent_before_approval(wf):
    created = propose_ok(wf)
    for headers in (COORD, LEAD):
        response = send(wf, created["id"], headers=headers)
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "approval_required"
    assert wf.get("/api/offers", headers=COORD).json()["total"] == 0
    assert wf.get("/api/offers/mine", headers=doctor(VALE)).json() == []
    assert intervention(wf, created["id"])["status"] == "pending_approval"


# 3. Clinical lead can approve --------------------------------------------------------------


def test_clinical_lead_approves_with_revalidation_and_sim_timestamp(wf):
    created = propose_ok(wf)
    response = decide(wf, created["id"], note="Go ahead")

    assert response.status_code == 200, response.text
    approved = response.json()
    assert approved["status"] == "approved"
    assert approved["approval"]["decided_by"] == {"role": "clinical_lead", "actor_id": "lead-1"}
    assert approved["approval"]["decided_at"] == REF  # simulation time, not the wall clock
    assert approved["approval"]["note"] == "Go ahead"
    assert any("rules pass" in line for line in approved["approval"]["revalidation"])
    assert approved["allowed_actions"] == ["send_offers", "cancel"]
    coordinator_view = intervention(wf, created["id"])
    assert coordinator_view["allowed_actions"] == ["send_offers", "cancel"]
    # Repeated approval is refused, not applied twice.
    again = decide(wf, created["id"])
    assert again.status_code == 409 and again.json()["error"]["code"] == "already_decided"
    assert [e["action"] for e in audit(wf, created["id"])].count("intervention_approved") == 1


# 4. Clinical lead can reject ---------------------------------------------------------------


def test_clinical_lead_rejects_with_explanation(wf):
    created = propose_ok(wf)
    response = decide(wf, created["id"], "reject", note="Use the night physician instead")

    assert response.status_code == 200
    rejected = response.json()
    assert rejected["status"] == "rejected" and rejected["is_terminal"]
    assert rejected["approval"]["decision"] == "reject"
    assert rejected["status_reason"] == "Use the night physician instead"
    assert send(wf, created["id"]).status_code == 409
    assert decide(wf, created["id"]).status_code == 409
    assert audit(wf, created["id"])[-1]["action"] == "intervention_rejected"


# 5. Unauthorized simulated roles cannot approve ---------------------------------------------


def test_only_the_clinical_lead_role_can_decide(wf):
    created = propose_ok(wf)
    url = f"/api/interventions/{created['id']}/decision"
    body = {"decision": "approve"}

    assert wf.post(url, headers=COORD, json=body).status_code == 403
    assert wf.post(url, headers=doctor(VALE), json=body).status_code == 403
    assert wf.post(url, json=body).status_code == 401
    system = wf.post(url, headers={"X-Demo-Role": "system"}, json=body)
    assert system.status_code == 401 and system.json()["error"]["code"] == "role_invalid"
    # Physicians cannot read interventions or the audit log either.
    assert wf.get("/api/interventions", headers=doctor(VALE)).status_code == 403
    assert wf.get("/api/audit", headers=doctor(VALE)).status_code == 403
    assert intervention(wf, created["id"])["status"] == "pending_approval"


# 6. Approval rechecks current eligibility ---------------------------------------------------


def _inject(client, *events):
    response = client.post("/api/events", json=list(events))
    assert response.status_code == 201, response.text


def test_approval_rechecks_the_offer_against_current_data(wf):
    created = propose_ok(wf)
    advance(wf, 5)  # the offer was to start at 22:35Z; it is now 22:40Z
    response = decide(wf, created["id"])

    assert response.status_code == 409
    error = response.json()["error"]
    assert error["code"] == "revalidation_failed"
    assert any("has passed" in p for p in error["details"]["problems"])
    assert intervention(wf, created["id"])["status"] == "pending_approval"
    assert audit(wf, created["id"])[-1]["action"] == "approval_blocked"
    assert wf.get("/api/offers", headers=COORD).json()["total"] == 0


def test_approval_rechecks_eligibility_when_the_physician_starts_a_regular_shift(wf):
    created = propose_ok(wf)
    # New data: Dr. Vale starts a regular shift. A split shift no longer applies (and Ridge
    # is now covered by that shift), so the request closes instead of being approved.
    _inject(
        wf,
        {
            "event_id": "LIVE-SHIFT-P6",
            "event_type": "shift_started",
            "event_time": "2030-09-10T18:35:00-04:00",
            "physician_id": VALE,
        },
    )
    response = decide(wf, created["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "no_longer_required"
    assert intervention(wf, created["id"])["status"] == "no_longer_required"
    assert wf.get("/api/offers", headers=COORD).json()["total"] == 0


def test_approval_closes_a_request_whose_gap_disappeared(wf):
    created = propose_ok(wf)
    # Dr. Wren (credentialed at Ridge) starts a shift: Ridge is covered, no gap remains.
    _inject(
        wf,
        {
            "event_id": "LIVE-SHIFT-P7",
            "event_type": "shift_started",
            "event_time": "2030-09-10T15:35:00-07:00",
            "physician_id": "SRG-P7",
        },
    )
    response = decide(wf, created["id"])

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "no_longer_required"
    assert intervention(wf, created["id"])["status"] == "no_longer_required"


# 7. Offer count limits are enforced ---------------------------------------------------------


def test_three_offers_per_rolling_week_limit(wf):
    for _ in range(3):
        _, offers = offers_sent(wf, physician_ids=[YARA])
        assert respond(wf, offers[YARA]["id"], YARA, "decline").status_code == 200

    response = propose(wf, physician_ids=[YARA])
    assert response.status_code == 422
    reasons = " ".join(response.json()["error"]["details"]["blocking_reasons"])
    assert "3 offers in the rolling 7 days" in reasons
    row = next(
        c
        for c in wf.get("/api/optimization/split-shifts").json()["candidates"]
        if c["physician_id"] == YARA
    )
    assert row["failed_rules"] == ["notification_limits"]


def test_rolling_week_counts_offers_sent_in_the_last_168_hours(wf, settings):
    from app.db.session import build_engine

    engine = build_engine(settings.resolved_database_url)
    now = _iso(REF)
    with Session(engine) as session:
        repo = WorkflowRepository(session)
        assert repo.offer_counts(YARA, now, timedelta(days=7)) == (0, 0, 0)
        created = propose_ok(wf, physician_ids=[YARA])
        decide(wf, created["id"])
        send(wf, created["id"])
        session.expire_all()
        assert repo.offer_counts(YARA, now, timedelta(days=7)) == (1, 0, 1)
        # Seven days later the offer has left the rolling window.
        later = now + timedelta(days=7)
        assert repo.offer_counts(YARA, later, timedelta(days=7))[2] == 0
        assert repo.offer_counts(YARA, later - timedelta(seconds=1), timedelta(days=7))[2] == 1
    engine.dispose()


# 8. One-open-offer restriction ---------------------------------------------------------------


def test_one_open_offer_per_physician(wf, settings):
    _, offers = offers_sent(wf, physician_ids=[YARA])
    assert offers[YARA]["status"] == "sent"

    row = next(
        c
        for c in wf.get("/api/optimization/split-shifts").json()["candidates"]
        if c["physician_id"] == YARA
    )
    assert row["failed_rules"] == ["notification_limits"]
    assert "open offer" in next(
        c["message"] for c in row["checks"] if c["code"] == "notification_limits"
    )
    blocked = propose(wf, physician_ids=[YARA], hospital_ids=[RIDGE])
    assert blocked.status_code == 422

    # The database enforces it too (partial unique index on sent offers).
    from app.db.session import build_engine

    engine = build_engine(settings.resolved_database_url)
    with Session(engine) as session:
        existing = session.get(OfferRecord, offers[YARA]["id"])
        clone = OfferRecord(
            **{
                c.name: getattr(existing, c.name)
                for c in OfferRecord.__table__.columns
                if c.name != "id"
            },
            id="OFF-CLONE",
        )
        session.add(clone)
        with pytest.raises(IntegrityError):
            session.commit()
    engine.dispose()


# 9-10. Expiry at the simulated timestamp; expired offers cannot be accepted ------------------


def test_offer_expires_exactly_ten_simulated_minutes_after_sending(wf):
    sent, offers = offers_sent(wf)
    offer = offers[VALE]
    assert offer["sent_at"] == REF and offer["expires_at"] == "2030-09-10T22:45:00Z"

    advance(wf, 9)
    assert intervention(wf, sent["id"])["offers"][0]["status"] == "sent"
    assert wf.get("/api/offers/mine", headers=doctor(VALE)).json()[0]["can_accept"] is True

    advance(wf, 1)  # exactly 10 minutes
    after = intervention(wf, sent["id"])
    assert after["offers"][0]["status"] == "expired"
    assert after["status"] == "expired"
    expiry = next(e for e in audit(wf, sent["id"]) if e["action"] == "offer_expired")
    assert expiry["occurred_at"] == "2030-09-10T22:45:00Z"
    assert expiry["actor"]["role"] == "system"


def test_expired_offer_cannot_be_accepted_and_the_attempt_is_logged(wf):
    sent, offers = offers_sent(wf)
    advance(wf, 12)
    response = respond(wf, offers[VALE]["id"], VALE)

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "offer_expired"
    offer = intervention(wf, sent["id"])["offers"][0]
    assert offer["status"] == "expired"
    assert [r["outcome"] for r in offer["responses"]] == ["rejected_expired"]
    assert audit(wf, sent["id"])[-1]["action"] == "response_rejected"
    view = wf.get("/api/offers/mine", headers=doctor(VALE)).json()[0]
    assert view["status"] == "expired" and view["can_accept"] is False


# 11, 13. Accepting a valid offer; repeated acceptance is idempotent ---------------------------


def test_valid_offer_can_be_accepted_once_and_repeats_are_idempotent(wf):
    sent, offers = offers_sent(wf)
    version = data_version(wf)
    advance(wf, 3)
    first = respond(wf, offers[VALE]["id"], VALE)

    assert first.status_code == 200, first.text
    body = first.json()
    assert body["outcome"] == "accepted" and body["idempotent_replay"] is False
    assert body["offer"]["status"] == "accepted"
    assert body["offer"]["expected_online_at"] == "2030-09-10T22:58:00Z"  # 22:38 + 20 min
    assert data_version(wf) == version + 1
    assert intervention(wf, sent["id"])["status"] == "accepted"

    second = respond(wf, offers[VALE]["id"], VALE)
    assert second.status_code == 200
    assert second.json()["outcome"] == "duplicate_ignored"
    assert second.json()["idempotent_replay"] is True
    assert data_version(wf) == version + 1  # nothing changed
    offer = intervention(wf, sent["id"])["offers"][0]
    assert [r["outcome"] for r in offer["responses"]] == ["accepted", "duplicate_ignored"]
    assert offer["responses"][0]["response_seconds"] == 180
    # Declining after accepting is refused.
    assert respond(wf, offers[VALE]["id"], VALE, "decline").status_code == 409


# 12. Decline is persisted and communicated ----------------------------------------------------


def test_decline_is_persisted_and_communicated(wf, make_client):
    sent, offers = offers_sent(wf)
    response = respond(wf, offers[VALE]["id"], VALE, "decline")

    assert response.status_code == 200
    assert response.json()["outcome"] == "declined"
    assert "coordinator has been informed" in response.json()["message"]
    with make_client() as restarted:
        record = intervention(restarted, sent["id"])
        assert record["status"] == "declined"
        assert record["offers"][0]["status"] == "declined"
        assert any(e["action"] == "offer_declined" for e in audit(restarted, sent["id"]))
        view = restarted.get("/api/offers/mine", headers=doctor(VALE)).json()[0]
        assert view["status_label"] == "Declined" and view["can_accept"] is False
        late = respond(restarted, offers[VALE]["id"], VALE)
        assert late.status_code == 409 and late.json()["error"]["code"] == "offer_declined"
        again = respond(restarted, offers[VALE]["id"], VALE, "decline")
        assert again.status_code == 200 and again.json()["idempotent_replay"] is True


# 14. Two physicians accepting offers for the same gap ----------------------------------------


def test_backup_offer_is_withdrawn_once_the_first_acceptance_fills_the_gap(wf):
    sent, offers = offers_sent(wf, physician_ids=[VALE, YARA])
    assert {o["plan_role"] for o in sent["offers"]} == {"primary", "backup"}
    assert all(o["status"] == "sent" for o in sent["offers"])

    assert respond(wf, offers[VALE]["id"], VALE).json()["outcome"] == "accepted"
    after = {o["physician_id"]: o for o in intervention(wf, sent["id"])["offers"]}
    assert after[YARA]["status"] == "withdrawn"
    assert "secured" in after[YARA]["status_reason"]

    late = respond(wf, offers[YARA]["id"], YARA)
    assert late.status_code == 409 and late.json()["error"]["code"] == "offer_withdrawn"
    assert "recorded" in late.json()["error"]["message"]
    after = {o["physician_id"]: o for o in intervention(wf, sent["id"])["offers"]}
    assert after[YARA]["responses"][0]["outcome"] == "rejected_withdrawn"  # never dropped
    actions = [e["action"] for e in audit(wf, sent["id"])]
    assert "redundant_acceptance_recorded" in actions and "conflict_resolved" in actions
    # Only one physician becomes coverage.
    assert physician(wf, VALE)["temporary_shift"]["phase"] == "preparing"
    assert physician(wf, YARA)["temporary_shift"] is None


def test_simultaneous_acceptances_for_the_same_gap_bind_exactly_one(wf):
    # Two separate requests for the same Ridge gap, both approved and sent.
    a, offers_a = offers_sent(wf, physician_ids=[VALE], hospital_ids=[RIDGE])
    b, offers_b = offers_sent(wf, physician_ids=[YARA], hospital_ids=[RIDGE], alert_id=None)
    barrier = threading.Barrier(2)
    results: dict[str, object] = {}

    def accept(pid: str, offer_id: str) -> None:
        barrier.wait()
        results[pid] = respond(wf, offer_id, pid)

    threads = [
        threading.Thread(target=accept, args=(VALE, offers_a[VALE]["id"])),
        threading.Thread(target=accept, args=(YARA, offers_b[YARA]["id"])),
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    statuses = {
        pid: intervention(wf, iid)["offers"][0]["status"]
        for pid, iid in ((VALE, a["id"]), (YARA, b["id"]))
    }
    assert sorted(statuses.values()).count("accepted") == 1
    loser = next(pid for pid, s in statuses.items() if s != "accepted")
    assert statuses[loser] in {"redundant", "withdrawn"}
    winner = next(pid for pid, s in statuses.items() if s == "accepted")
    assert physician(wf, winner)["temporary_shift"] is not None
    assert physician(wf, loser)["temporary_shift"] is None
    entries = wf.get("/api/audit", headers=COORD).json()["items"]
    assert any(e["action"] in {"conflict_resolved", "offer_withdrawn"} for e in entries)


# 15. Accepted-but-not-active is not counted as active -----------------------------------------


def test_accepted_physician_is_not_counted_as_active_capacity(wf):
    _, offers = offers_sent(wf)
    respond(wf, offers[VALE]["id"], VALE)

    p6 = physician(wf, VALE)
    assert p6["on_shift"] is False and p6["availability"] == "off_shift"
    assert p6["temporary_shift"]["phase"] == "preparing"
    entry = contributor(wf, RIDGE, VALE)
    assert entry["status"] == "pending_activation" and entry["certainty"] == "uncertain"
    assert entry["counts_from"] == "2030-09-10T22:55:00Z"
    ridge = coverage(wf, RIDGE)
    now = ridge["segments"][0]
    assert now["available_confirmed"] == 0 and now["deficit"] == 1
    assert ridge["metrics"]["deficit_now"] == 1
    gap = next(
        a for a in wf.get("/api/alerts").json()["alerts"] if a["alert_id"] == RIDGE_GAP_ALERT
    )
    assert gap["severity"] == "critical"  # still a gap now
    routing = wf.get("/api/optimization/assignments").json()
    assert VALE not in {p["physician_id"] for p in routing["physicians"]}


# 16. Activation recalculates staffing coverage -------------------------------------------------


def test_activation_at_expected_online_time_recalculates_everything(wf):
    sent, offers = offers_sent(wf)
    respond(wf, offers[VALE]["id"], VALE)
    version = data_version(wf)

    advance(wf, 20)  # 22:55Z = start + 20 min to come online

    record = intervention(wf, sent["id"])
    assert record["status"] == "activated"
    offer = record["offers"][0]
    assert offer["status"] == "active" and offer["activated_at"] == "2030-09-10T22:55:00Z"
    assert offer["activation_source"] == "simulation_policy"
    assert data_version(wf) > version
    p6 = physician(wf, VALE)
    assert p6["on_shift"] is True and p6["availability"] == "available"
    entry = contributor(wf, RIDGE, VALE)
    assert entry["status"] == "counted" and entry["certainty"] == "confirmed"
    assert coverage(wf, RIDGE)["metrics"]["deficit_physician_minutes"] == 0
    assert RIDGE_GAP_ALERT not in {a["alert_id"] for a in wf.get("/api/alerts").json()["alerts"]}
    row = next(
        c
        for c in wf.get("/api/optimization/split-shifts").json()["candidates"]
        if c["physician_id"] == VALE
    )
    assert "off_shift" in row["failed_rules"]
    impact = wf.get(f"/api/interventions/{sent['id']}/impact", headers=COORD).json()
    assert impact["at_activation"]["total_before"] == 90
    assert impact["at_activation"]["total_after"] == 0
    actions = [e["action"] for e in audit(wf, sent["id"])]
    assert actions[-3:] == [
        "physician_activated",
        "coverage_recalculated",
        "intervention_activated",
    ]


def test_physician_can_go_online_early_but_not_before_the_shift_starts(wf):
    _, offers = offers_sent(wf, physician_ids=[YARA], start_at="2030-09-10T22:45:00Z")
    respond(wf, offers[YARA]["id"], YARA)
    early = wf.post(f"/api/offers/{offers[YARA]['id']}/activate", headers=doctor(YARA))
    assert early.status_code == 409 and early.json()["error"]["code"] == "shift_not_started"

    advance(wf, 15)  # 22:50Z: shift started 22:45, expected online 23:20
    online = wf.post(f"/api/offers/{offers[YARA]['id']}/activate", headers=doctor(YARA))
    assert online.status_code == 200, online.text
    assert online.json()["activated_at"] == "2030-09-10T22:50:00Z"
    assert online.json()["activation_source"] == "physician_reported"
    assert physician(wf, YARA)["on_shift"] is True


# 17. Routing scope restricts the activated physician -------------------------------------------


def test_activated_physician_is_routed_only_inside_the_approved_scope(wf):
    sent, offers = offers_sent(wf)
    respond(wf, offers[VALE]["id"], VALE)
    advance(wf, 20)
    _inject(
        wf,
        {
            "event_id": "LIVE-H4-1",
            "event_type": "consult_received",
            "event_time": "2030-09-10T17:55:00-05:00",
            "consult_id": "LIVE-C400",
            "hospital_id": LAKESHORE,
            "consult_type": "Stroke",
        },
        {
            "event_id": "LIVE-H4-2",
            "event_type": "consult_triaged",
            "event_time": "2030-09-10T17:55:30-05:00",
            "consult_id": "LIVE-C400",
            "hospital_id": LAKESHORE,
        },
    )
    routing = wf.get("/api/optimization/assignments").json()
    row = next(p for p in routing["physicians"] if p["physician_id"] == VALE)
    assert row["routing_scope_hospital_ids"] == [RIDGE]
    proposals = {r["consult_id"]: r["physician_id"] for r in routing["plan"]["recommendations"]}
    assert proposals.get("SRG-C220") == VALE  # the stranded Ridge consult
    assert proposals.get("LIVE-C400") != VALE  # Lakeshore is outside the approved scope
    lakeshore = contributor(wf, LAKESHORE, VALE)
    assert lakeshore["status"] == "excluded" and "routing scope" in lakeshore["reasons"][0]

    impact = wf.get(f"/api/interventions/{sent['id']}/impact", headers=COORD).json()
    trap, routing_view = impact["trap"], impact["routing"]
    assert routing_view["intended_hospital_ids"] == [RIDGE]
    assert routing_view["authorized_scope_hospital_ids"] == [RIDGE]
    assert LAKESHORE in routing_view["credentialed_hospital_ids"]
    assert routing_view["workload_before_joining"]["actual_consults"] == 0
    assert trap["unrestricted"]["routed_to_joiner_elsewhere"] > 0
    assert trap["protected"]["routed_to_joiner_elsewhere"] == 0
    assert "production routing" in routing_view["disclaimer"]


# 18. No patient information in offer payloads --------------------------------------------------


def test_offer_payloads_carry_no_patient_information(wf):
    rationale = "Stroke patient in CON-SECRET at Ridge; SRG-C220 waiting 23 min"
    _, offers = offers_sent(wf, rationale=rationale)
    payload = wf.get("/api/offers/mine", headers=doctor(VALE)).json()
    text = json.dumps(payload)
    consult_ids = [c["consult_id"] for c in wf.get("/api/consultations").json()]

    assert find_disallowed([text], [*consult_ids, "CON-SECRET", rationale]) == []
    assert "stroke" not in text.lower() and "general neuro" not in text.lower()
    allowed = {
        "id", "status", "status_label", "hospitals", "hospital_timezone", "start_at", "end_at",
        "duration_minutes", "minutes_to_online", "expected_online_at", "reason", "sent_at",
        "expires_at", "responded_at", "activated_at", "can_accept", "can_decline",
        "can_go_online", "message",
    }  # fmt: skip
    assert set(payload[0]) == allowed
    assert payload[0]["hospitals"] == [{"id": RIDGE, "name": "Ridge Sample Clinic"}]
    accepted = respond(wf, offers[VALE]["id"], VALE).json()
    assert find_disallowed([json.dumps(accepted)], [*consult_ids, rationale]) == []
    # Another physician cannot see or answer this offer.
    assert wf.get("/api/offers/mine", headers=doctor(YARA)).json() == []
    assert respond(wf, offers[VALE]["id"], YARA).status_code == 404


# 19. Every workflow transition creates an audit record ------------------------------------------


def test_every_transition_is_audited_with_simulation_times(wf):
    sent, offers = offers_sent(wf, physician_ids=[VALE, YARA])
    respond(wf, offers[VALE]["id"], VALE)
    advance(wf, 20)
    advance(wf, 240)  # past the 02:35Z end

    entries = audit(wf, sent["id"])
    chain = [
        (e["from_status"], e["to_status"]) for e in entries if e["entity_type"] == "intervention"
    ]
    for step in [
        (None, "pending_approval"),
        ("pending_approval", "approved"),
        ("approved", "offer_sent"),
        ("offer_sent", "accepted"),
        ("accepted", "activated"),
        ("activated", "completed"),
    ]:
        assert step in chain, step
    vale = [
        (e["from_status"], e["to_status"]) for e in entries if e["offer_id"] == offers[VALE]["id"]
    ]
    for step in [
        (None, "sent"),
        ("sent", "accepted"),
        ("accepted", "active"),
        ("active", "completed"),
    ]:
        assert step in vale, step
    assert ("sent", "withdrawn") in [
        (e["from_status"], e["to_status"]) for e in entries if e["offer_id"] == offers[YARA]["id"]
    ]
    completed = next(e for e in entries if e["action"] == "split_shift_completed")
    assert completed["occurred_at"] == "2030-09-11T02:35:00Z"
    assert all(e["recorded_at"] and e["occurred_at"] for e in entries)
    record = intervention(wf, sent["id"])
    assert record["status"] == "completed"
    assert physician(wf, VALE)["on_shift"] is False


# 20. Judge CSV events append without erasing interventions --------------------------------------


def test_judge_csv_append_keeps_interventions_and_staffing_overlay(wf):
    sent, offers = offers_sent(wf)
    respond(wf, offers[VALE]["id"], VALE)
    before = data_version(wf)
    csv = (
        "event_id,event_time,ingested_at,consult_id,event_type,physician_id,hospital_id,"
        "description\n"
        "JUDGE-1,2030-09-10T18:40:00-04:00,2030-09-10T18:40:05-04:00,JUDGE-C1,"
        "consult_received,,SRG-H1,Stroke consult received\n"
        "JUDGE-2,2030-09-10T18:41:00-04:00,2030-09-10T18:41:02-04:00,JUDGE-C1,"
        "consult_triaged,,SRG-H1,Triaged\n"
    )
    response = wf.post(
        "/api/events/csv", files={"file": ("judge_events.csv", io.BytesIO(csv.encode()))}
    )
    assert response.status_code == 201, response.text
    assert response.json()["accepted"] == 2
    assert data_version(wf) > before

    record = intervention(wf, sent["id"])
    assert record["status"] == "accepted" and record["offers"][0]["status"] == "accepted"
    assert physician(wf, VALE)["temporary_shift"]["phase"] == "preparing"
    advance(wf, 20)
    assert intervention(wf, sent["id"])["status"] == "activated"
    consults = {c["consult_id"] for c in wf.get("/api/consultations").json()}
    assert "JUDGE-C1" in consults


# 21. Existing forecasting and matching behavior remains correct ----------------------------------


def test_forecast_and_matching_are_unchanged_until_a_shift_is_accepted(wf):
    coverage_before = wf.get("/api/coverage").json()
    routing_before = wf.get("/api/optimization/assignments").json()
    staffing_before = wf.get("/api/optimization/split-shifts").json()

    created = propose_ok(wf)
    decide(wf, created["id"])
    send(wf, created["id"])
    # Proposals, approvals and open offers do not change operational state.
    assert wf.get("/api/coverage").json()["hospitals"] == coverage_before["hospitals"]
    routing = wf.get("/api/optimization/assignments").json()
    assert routing["plan"] == routing_before["plan"]
    # Staffing only differs because Dr. Vale now has an open offer (notification limit).
    staffing = wf.get("/api/optimization/split-shifts").json()
    vale = next(c for c in staffing["candidates"] if c["physician_id"] == VALE)
    assert vale["failed_rules"] == ["notification_limits"]
    assert staffing["gap_hospital_ids"] == staffing_before["gap_hospital_ids"]
    # Cancelling restores the original picture.
    sent = intervention(wf, created["id"])
    respond(wf, sent["offers"][0]["id"], VALE)
    assert (
        coverage(wf, RIDGE)["metrics"]
        != next(h for h in coverage_before["hospitals"] if h["hospital_id"] == RIDGE)["metrics"]
    )
    wf.post(f"/api/interventions/{created['id']}/cancel", headers=COORD, json={"reason": "test"})
    assert wf.get("/api/coverage").json()["hospitals"] == coverage_before["hospitals"]


# 22. Restarting the backend preserves workflow state ----------------------------------------------


def test_backend_restart_preserves_workflow_state(wf, make_client):
    sent, offers = offers_sent(wf, physician_ids=[VALE, YARA])
    respond(wf, offers[VALE]["id"], VALE)
    before = intervention(wf, sent["id"])
    before_audit = audit(wf, sent["id"])

    with make_client() as restarted:
        after = intervention(restarted, sent["id"])
        assert after["status"] == before["status"] == "accepted"
        assert after["offers"] == before["offers"]
        assert after["approval"] == before["approval"]
        assert audit(restarted, sent["id"]) == before_audit
        assert physician(restarted, VALE)["temporary_shift"]["phase"] == "preparing"
        mine = restarted.get("/api/offers/mine", headers=doctor(VALE)).json()
        assert mine[0]["status"] == "accepted"


# 23. Re-importing a full dataset has an explicit policy -------------------------------------------


def test_full_reimport_closes_open_workflow_and_keeps_history(wf):
    accepted, offers = offers_sent(wf)
    respond(wf, offers[VALE]["id"], VALE)
    pending = propose_ok(wf, physician_ids=[YARA], alert_id=None, hospital_ids=[RIDGE])

    load(wf)  # replace the dataset

    active = wf.get("/api/interventions", headers=COORD).json()
    assert active["total"] == 0
    history = {
        i["id"]: i for i in wf.get("/api/interventions?scope=all", headers=COORD).json()["items"]
    }
    assert history[accepted["id"]]["status"] == "cancelled"
    assert history[accepted["id"]]["offers"][0]["status"] == "cancelled"
    assert history[pending["id"]]["status"] == "no_longer_required"
    assert "dataset replaced" in history[pending["id"]]["status_reason"]
    assert physician(wf, VALE)["temporary_shift"] is None  # overlay is per dataset
    actions = [e["action"] for e in audit(wf, accepted["id"])]
    assert "intervention_closed_dataset_replaced" in actions
    assert "offer_closed_dataset_replaced" in actions


# 24. Stale recommendations cannot bypass eligibility --------------------------------------------


def test_stale_or_hand_edited_proposals_are_revalidated(wf):
    opted_out = propose(wf, physician_ids=["SRG-P7"], hospital_ids=[RIDGE])
    assert opted_out.status_code == 422
    assert "opted out" in " ".join(opted_out.json()["error"]["details"]["blocking_reasons"])

    overlap = propose(
        wf, physician_ids=[VALE], start_at="2030-09-11T20:00:00Z", duration_minutes=24 * 60
    )
    assert overlap.status_code == 422
    assert "overlaps" in " ".join(overlap.json()["error"]["details"]["blocking_reasons"])

    too_short = propose(wf, physician_ids=[VALE], duration_minutes=130)
    reasons = " ".join(too_short.json()["error"]["details"]["blocking_reasons"])
    assert too_short.status_code == 422 and "worth only 110 min" in reasons

    in_the_past = propose(wf, physician_ids=[VALE], start_at="2030-09-10T22:00:00Z")
    assert in_the_past.status_code == 422

    version = data_version(wf)
    _inject(
        wf,
        {
            "event_id": "LIVE-SHIFT-P6",
            "event_type": "shift_started",
            "event_time": "2030-09-10T18:35:00-04:00",
            "physician_id": VALE,
        },
    )
    stale = propose(wf, physician_ids=[VALE], expected_data_version=version)
    assert stale.status_code == 422
    details = stale.json()["error"]["details"]
    assert any("changed since" in w for w in details["warnings"])
    assert any("on shift" in r for r in details["blocking_reasons"])


# Reassignment and escalation flows -------------------------------------------------------------


def test_reassignment_is_revalidated_and_applied_as_a_workflow_event(wf):
    _, offers = offers_sent(wf)
    respond(wf, offers[VALE]["id"], VALE)
    advance(wf, 20)
    alert = next(
        a
        for a in wf.get("/api/alerts").json()["alerts"]
        if a["consult_id"] == "SRG-C220" and a["rule_code"] == "STAGE_TRIAGED_UNASSIGNED"
    )
    created = propose_ok(wf, type="reassign_consult", alert_id=alert["alert_id"])
    assert created["status"] == "proposed"
    assert created["reassignment"]["target_physician_id"] == VALE
    assert created["recommendation"]["approver_role"] == "coordinator"
    assert decide(wf, created["id"]).status_code == 409  # nothing to approve

    applied = wf.post(f"/api/interventions/{created['id']}/apply", headers=COORD)
    assert applied.status_code == 200, applied.text
    assert applied.json()["status"] == "completed"
    consult = wf.get("/api/consultations/SRG-C220").json()
    assert consult["assigned_physician_id"] == VALE
    events = wf.get("/api/events", params={"consult_id": "SRG-C220"}).json()["items"]
    workflow = [e for e in events if e["source"] == "workflow"]
    assert len(workflow) == 1 and workflow[0]["event_type"] == "physician_assigned"
    again = wf.post(f"/api/interventions/{created['id']}/apply", headers=COORD)
    assert again.status_code == 409


def test_reassignment_without_an_eligible_physician_suggests_escalation(wf):
    response = propose(
        wf, type="reassign_consult", alert_id="STAGE_TRIAGED_UNASSIGNED:consult:SRG-C220"
    )
    assert response.status_code == 422
    assert "Escalate" in " ".join(response.json()["error"]["details"]["blocking_reasons"])


def test_escalation_is_authorized_and_resolved_by_the_clinical_lead(wf):
    created = propose_ok(
        wf, type="escalation", alert_id="STAGE_TRIAGED_UNASSIGNED:consult:SRG-C220"
    )
    assert created["status"] == "pending_approval"
    assert created["escalation"]["blocking_facts"]
    approved = decide(wf, created["id"])
    assert approved.status_code == 200 and approved.json()["status"] == "approved"
    resolved = wf.post(
        f"/api/interventions/{created['id']}/resolve", headers=LEAD, json={"note": "Called"}
    )
    assert resolved.status_code == 200 and resolved.json()["status"] == "completed"
    assert [e["action"] for e in audit(wf, created["id"])][-1] == "escalation_resolved"


def test_live_stream_reports_versions(wf):
    created = propose_ok(wf)
    body = wf.get("/api/live", params={"once": True}).text
    payload = json.loads(body.split("data: ", 1)[1].split("\n", 1)[0])
    assert payload["pending_approvals"] == 1
    assert payload["workflow_version"] >= 2
    assert payload["simulation_time"] == REF
    assert created["id"]


def test_workflow_fixture_generator_is_reproducible(tmp_path):
    import filecmp

    from scripts.generate_workflow_dataset import OUTPUT, write_dataset

    write_dataset(tmp_path)
    names = sorted(p.name for p in OUTPUT.iterdir())
    _, mismatch, errors = filecmp.cmpfiles(OUTPUT, tmp_path, names, shallow=False)
    assert not mismatch and not errors


def test_split_shift_quota_follows_the_peak_deficit(wf):
    created = propose_ok(wf)
    assert created["required_physicians"] == 1


def test_declared_extra_availability_persists_and_restricts_candidates(wf):
    payload = {"enabled": True, "windows": []}
    assert wf.put("/api/offers/extra-availability", headers=COORD, json=payload).status_code == 403
    saved = wf.put("/api/offers/extra-availability", headers=doctor(VALE), json=payload)
    assert saved.status_code == 200
    assert wf.get("/api/offers/extra-availability", headers=doctor(VALE)).json() == payload
    result = wf.get("/api/optimization/split-shifts").json()
    assert "outside declared" in json.dumps(result)
    assert (
        wf.put(
            "/api/offers/extra-availability",
            headers=doctor(VALE),
            json={
                "enabled": True,
                "windows": [{"start": "2030-09-10T22:35:00Z", "end": "2030-09-11T02:35:00Z"}],
            },
        ).status_code
        == 200
    )
    created = propose_ok(wf)
    assert any(p["physician_id"] == VALE for p in created["offer_plan"])


def test_declared_availability_rejects_invalid_times(wf):
    for window in [
        {"start": "2030-09-10T22:00:00", "end": "2030-09-11T02:00:00"},
        {"start": "2030-09-11T02:00:00Z", "end": "2030-09-10T22:00:00Z"},
    ]:
        assert (
            wf.put(
                "/api/offers/extra-availability",
                headers=doctor(VALE),
                json={"enabled": True, "windows": [window]},
            ).status_code
            == 422
        )


def test_extra_availability_clips_offer_and_revalidates_approval(wf):
    assert (
        wf.put(
            "/api/offers/extra-availability",
            headers=doctor(VALE),
            json={
                "enabled": True,
                "windows": [{"start": "2030-09-10T22:35:00Z", "end": "2030-09-11T01:05:00Z"}],
            },
        ).status_code
        == 200
    )
    created = propose_ok(wf)
    plan = next(p for p in created["offer_plan"] if p["physician_id"] == VALE)
    assert plan["duration_minutes"] <= 150
    assert (
        wf.put(
            "/api/offers/extra-availability",
            headers=doctor(VALE),
            json={"enabled": True, "windows": []},
        ).status_code
        == 200
    )
    assert decide(wf, created["id"]).status_code == 409
