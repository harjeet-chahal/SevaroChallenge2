"""Replay semantics: determinism, duplicates, late and out-of-order events, visibility."""

from __future__ import annotations

import random

from app.engines.replay import reconstruct_state
from app.schemas.consultation import ConsultStage
from app.schemas.physician import Availability, DerivedActivity
from tests.engine_helpers import EventFactory, consult_flow, reference, t


def _consult(state, consult_id):
    return next(c for c in state.consultations if c.consult_id == consult_id)


def _physician(state, physician_id):
    return next(p for p in state.physicians if p.physician_id == physician_id)


def _scenario():
    ev = EventFactory()
    events = [
        ev("physician_status_changed", 0, physician="P1", status="Available"),
        *consult_flow(ev, "C1", "P1", 5),
        ev("imaging_requested", 9, consult="C1", hospital="H1"),
        ev("incoming_call_ended", 10, consult="C1", physician="P1", hospital="H1"),
        ev("imaging_returned", 20, consult="C1", hospital="H1"),
        ev("video_started", 25, consult="C1", physician="P1", hospital="H1", ingested=33),
        ev("camera_active", 25, physician="P1"),
        ev("unknown_vendor_event", 26, physician="P1"),
        *consult_flow(ev, "C2", "P2", 12),
        ev("incoming_call_ended", 20, consult="C2", physician="P2", hospital="H1"),
    ]
    return events, reference("P1", "P2")


# 1. Identical replay always produces identical state ---------------------------------


def test_replay_is_deterministic_and_order_independent():
    events, ref = _scenario()
    first = reconstruct_state(events, t(40), ref).model_dump()
    second = reconstruct_state(events, t(40), ref).model_dump()
    shuffled = list(events)
    random.Random(7).shuffle(shuffled)
    third = reconstruct_state(shuffled, t(40), ref).model_dump()

    assert first == second == third


# 2. A duplicate event does not change state or double-count --------------------------


def test_duplicate_event_is_skipped_and_not_double_counted():
    ev = EventFactory()
    events = consult_flow(ev, "C1", "P1", 0)
    call = events[-1]
    resent = ev(
        "incoming_call_started",
        3,
        consult="C1",
        physician="P1",
        hospital="H1",
        event_id=call.event_id,
        ingested=3.5,
    )
    assigned_again = ev(
        "physician_assigned",
        2,
        consult="C1",
        physician="P1",
        hospital="H1",
        event_id=events[2].event_id,
        ingested=4,
    )
    ref = reference("P1")

    baseline = reconstruct_state(events, t(10), ref)
    with_dupes = reconstruct_state([*events, resent, assigned_again], t(10), ref)

    assert with_dupes.diagnostics.duplicates_skipped == 2
    p = _physician(with_dupes, "P1")
    assert p.calls_this_shift == 1
    assert p.consults_this_shift == 1
    assert with_dupes.consultations == baseline.consultations
    assert with_dupes.physicians == baseline.physicians


def test_conflicting_duplicate_keeps_first_copy():
    ev = EventFactory()
    first = ev("physician_status_changed", 0, physician="P1", status="Available", event_id="S1")
    conflicting = ev(
        "physician_status_changed",
        0,
        physician="P1",
        status="Temporarily Unavailable",
        event_id="S1",
        ingested=1,
    )

    state = reconstruct_state([conflicting, first], t(5), reference("P1"))

    assert state.diagnostics.conflicting_duplicates == 1
    assert _physician(state, "P1").signals.self_reported_status.value == "available"


# 3. A late-arriving event is incorporated at its true time ----------------------------


def test_late_event_is_incorporated_at_its_event_time():
    events, ref = _scenario()

    before = _consult(reconstruct_state(events, t(30), ref), "C1")
    after = _consult(reconstruct_state(events, t(34), ref), "C1")

    assert before.stage is ConsultStage.IMAGING_REVIEW
    assert after.stage is ConsultStage.VIDEO_IN_PROGRESS
    assert after.stage_entered_at == t(25)
    assert after.seconds_in_stage == 9 * 60
    assert reconstruct_state(events, t(34), ref).diagnostics.late_arrivals_applied >= 1


# 4. Out-of-order ingestion reconstructs the correct state -----------------------------


def test_older_event_arriving_last_does_not_overwrite_newer_state():
    ev = EventFactory()
    events = [
        ev("camera_active", 10, physician="P1"),
        ev("camera_inactive", 20, physician="P1", ingested=21),
        ev("camera_active", 30, physician="P1", ingested=30.1),
        # Stale "inactive" from minute 15 arrives last.
        ev("camera_inactive", 15, physician="P1", ingested=40),
    ]

    p = _physician(reconstruct_state(events, t(45), reference("P1")), "P1")

    assert p.signals.camera_active is True
    assert p.signals.camera_since == t(30)
    assert p.activity is DerivedActivity.EXTERNAL_VIDEO_SUSPECTED


def test_consult_lifecycle_rebuilt_when_ingested_in_reverse_order():
    ev = EventFactory()
    flow = consult_flow(ev, "C1", "P1", 0)
    # Re-issue the same events so every one is ingested in reverse occurrence order.
    reversed_ingest = [
        ev(
            e.event_type,
            (e.event_time - t(0)).total_seconds() / 60,
            consult=e.consult_id,
            physician=e.physician_id,
            hospital=e.hospital_id,
            consult_type=e.payload.get("consult_type"),
            ingested=20 - i,
        )
        for i, e in enumerate(flow)
    ]

    c = _consult(reconstruct_state(reversed_ingest, t(25), reference("P1")), "C1")

    assert c.stage is ConsultStage.PROVIDER_CONTACTED
    assert [s.stage for s in c.stage_history] == [
        ConsultStage.RECEIVED,
        ConsultStage.TRIAGED,
        ConsultStage.ASSIGNED,
        ConsultStage.PROVIDER_CONTACTED,
    ]
    assert c.anomalies == []


# 5. Events ingested after the simulation time are excluded ----------------------------


def test_events_ingested_after_as_of_are_excluded():
    events, ref = _scenario()

    state = reconstruct_state(events, t(30), ref)

    assert state.diagnostics.events_not_yet_ingested == 1  # the late video_started
    assert _physician(state, "P1").signals.active_videos == []


def test_event_timestamped_after_as_of_is_not_applied_even_if_ingested():
    ev = EventFactory()
    skewed = ev("camera_active", 50, physician="P1", ingested=40)

    state = reconstruct_state([skewed], t(45), reference("P1"))

    assert state.diagnostics.events_future_event_time == 1
    assert _physician(state, "P1").signals.camera_active is None


# 6. State changes correctly as simulation time advances -------------------------------


def test_state_changes_when_simulation_time_advances():
    events, ref = _scenario()
    ev = EventFactory()
    ev.sequence = 100
    events += [
        ev("video_ended", 45, consult="C1", physician="P1", hospital="H1"),
        ev("camera_inactive", 45.2, physician="P1"),
    ]

    during = reconstruct_state(events, t(40), ref)
    after = reconstruct_state(events, t(50), ref)

    assert _physician(during, "P1").availability is Availability.BUSY
    assert _consult(during, "C1").stage is ConsultStage.VIDEO_IN_PROGRESS
    assert _physician(after, "P1").availability is Availability.AVAILABLE
    assert _consult(after, "C1").stage is ConsultStage.NOTE_PENDING
    assert _consult(after, "C1").seconds_in_stage == 5 * 60


def test_unknown_event_types_are_counted_not_applied():
    events, ref = _scenario()

    state = reconstruct_state(events, t(40), ref)

    assert state.diagnostics.unknown_event_types == {"unknown_vendor_event": 1}


def test_physician_after_scheduled_shift_is_off_shift():
    ev = EventFactory()
    events = [ev("physician_status_changed", 0, physician="P1", status="Available")]
    ref = reference("P1", shift=(-60, 30))

    p = _physician(reconstruct_state(events, t(31), ref), "P1")

    assert p.on_shift is False
    assert p.availability is Availability.OFF_SHIFT
