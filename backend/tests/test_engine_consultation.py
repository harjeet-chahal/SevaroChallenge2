"""Consult lifecycle transitions, including unexpected sequences."""

from __future__ import annotations

from app.engines.consultation_state import decide_transition
from app.engines.replay import reconstruct_state
from app.schemas.consultation import ConsultStage as S
from tests.engine_helpers import EventFactory, consult_flow, reference, t


def _c(events, at, cid="C1"):
    state = reconstruct_state(events, t(at), reference("P1", "P2"))
    return next(c for c in state.consultations if c.consult_id == cid)


def test_full_stroke_lifecycle_closes_consult():
    ev = EventFactory()
    events = [
        *consult_flow(ev, "C1", "P1", 0),
        ev("imaging_requested", 4, consult="C1"),
        ev("incoming_call_ended", 6, consult="C1", physician="P1"),
        ev("imaging_returned", 15, consult="C1"),
        ev("video_started", 18, consult="C1", physician="P1"),
        ev("video_ended", 30, consult="C1", physician="P1"),
        ev("note_started", 35, consult="C1", physician="P1"),
        ev("note_signed", 50, consult="C1", physician="P1"),
    ]

    c = _c(events, 60)

    assert c.stage is S.SIGNED_OFF and not c.is_open and c.closed_at == t(50)
    assert [h.stage for h in c.stage_history] == [
        S.RECEIVED,
        S.TRIAGED,
        S.ASSIGNED,
        S.PROVIDER_CONTACTED,
        S.IMAGING_PENDING,
        S.IMAGING_REVIEW,
        S.VIDEO_IN_PROGRESS,
        S.NOTE_PENDING,
        S.DOCUMENTATION,
        S.SIGNED_OFF,
    ]
    assert c.consult_type == "Stroke"
    assert c.hospital_name == "Test Hospital One"


def test_outgoing_status_check_call_does_not_regress_imaging_pending():
    ev = EventFactory()
    events = [
        *consult_flow(ev, "C1", "P1", 0),
        ev("imaging_requested", 4, consult="C1"),
        ev("incoming_call_ended", 5, consult="C1", physician="P1"),
        ev("outgoing_call_started", 20, consult="C1", physician="P1"),
        ev("outgoing_call_ended", 22, consult="C1", physician="P1"),
    ]

    c = _c(events, 25)

    assert c.stage is S.IMAGING_PENDING and c.stage_entered_at == t(4)
    assert c.anomalies == []


def test_provisional_note_pending_is_superseded_by_video():
    ev = EventFactory()
    events = [
        *consult_flow(ev, "C1", "P1", 0),
        ev("incoming_call_ended", 6, consult="C1", physician="P1"),
        ev("video_started", 7, consult="C1", physician="P1"),
    ]

    c = _c(events, 10)

    assert c.stage is S.VIDEO_IN_PROGRESS
    assert c.stage_history[-2].stage is S.NOTE_PENDING and c.stage_history[-2].provisional


def test_backwards_event_is_recorded_as_anomaly_and_stage_kept():
    ev = EventFactory()
    events = [
        *consult_flow(ev, "C1", "P1", 0),
        ev("note_started", 10, consult="C1", physician="P1"),
        ev("imaging_requested", 12, consult="C1"),
    ]

    c = _c(events, 15)

    assert c.stage is S.DOCUMENTATION
    assert [a.code for a in c.anomalies] == ["out_of_sequence"]


def test_missing_received_event_still_builds_consult():
    ev = EventFactory()
    events = [ev("physician_assigned", 3, consult="C7", physician="P1", hospital="H2")]

    c = _c(events, 5, cid="C7")

    assert c.stage is S.ASSIGNED and c.assigned_physician_id == "P1"
    assert c.received_at is None
    assert "missing_consult_received" in {a.code for a in c.anomalies}


def test_routing_failures_are_counted_and_consult_stays_unassigned():
    ev = EventFactory()
    events = [
        ev("consult_received", 0, consult="C1", hospital="H1", consult_type="Stroke"),
        ev("consult_triaged", 1, consult="C1", hospital="H1"),
        ev("routing_attempt_failed", 2, consult="C1", hospital="H1"),
        ev("routing_attempt_failed", 7, consult="C1", hospital="H1"),
    ]

    c = _c(events, 10)

    assert c.stage is S.TRIAGED and c.assigned_physician_id is None
    assert c.routing_failures == 2 and c.last_routing_failure_at == t(7)


def test_repeat_request_keeps_the_first_clock_and_is_labelled_as_a_repeat():
    ev = EventFactory()
    events = [
        ev("consult_received", 0, consult="C1", hospital="H1", consult_type="Stroke"),
        ev("consult_triaged", 1, consult="C1", hospital="H1"),
        ev("consult_received", 7, consult="C1", hospital="H1", consult_type="Stroke"),
    ]

    c = _c(events, 10)

    assert c.stage is S.TRIAGED and c.stage_entered_at == t(1)
    assert c.received_at == t(0) and c.seconds_since_received == 600
    assert [a.code for a in c.anomalies] == ["repeat_request"]


def test_first_received_after_other_events_is_out_of_sequence_not_a_repeat():
    ev = EventFactory()
    events = [
        ev("consult_triaged", 1, consult="C1", hospital="H1"),
        ev("consult_received", 2, consult="C1", hospital="H1"),
    ]

    c = _c(events, 5)

    assert c.received_at == t(2)
    assert [a.code for a in c.anomalies] == [
        "missing_consult_received",
        "received_out_of_sequence",
    ]


def test_ringing_does_not_assign_consult():
    ev = EventFactory()
    events = [
        ev("consult_received", 0, consult="C1", hospital="H1"),
        ev("incoming_call_ringing", 1, consult="C1", physician="P2", hospital="H1"),
    ]

    c = _c(events, 2)

    assert c.assigned_physician_id is None and c.stage is S.RECEIVED


def test_reassignment_is_recorded():
    ev = EventFactory()
    events = [
        *consult_flow(ev, "C1", "P1", 0),
        ev("physician_assigned", 8, consult="C1", physician="P2", hospital="H1"),
    ]

    c = _c(events, 10)

    assert c.assigned_physician_id == "P2"
    assert [a.physician_id for a in c.assignment_history] == ["P1", "P2"]


def test_consult_type_from_description_fallback():
    ev = EventFactory()
    events = [
        ev(
            "consult_received",
            0,
            consult="C1",
            hospital="H1",
            description="General Neuro consult request received",
        ),
    ]

    assert _c(events, 1).consult_type == "General Neuro"


def test_transition_table_is_explicit():
    assert decide_transition(None, False, "video_started").target is S.VIDEO_IN_PROGRESS
    assert decide_transition(S.SIGNED_OFF, False, "note_started").anomaly_code == (
        "event_after_sign_off"
    )
    assert decide_transition(S.IMAGING_PENDING, False, "incoming_call_ended").target is None
    decision = decide_transition(S.PROVIDER_CONTACTED, False, "outgoing_call_ended")
    assert decision.target is S.NOTE_PENDING and decision.provisional
