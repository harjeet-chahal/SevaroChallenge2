"""Availability precedence rules (items 7-9) and independence from consult state (item 10)."""

from __future__ import annotations

from app.engines.replay import reconstruct_state
from app.schemas.common import Severity
from app.schemas.consultation import ConsultStage
from app.schemas.physician import Availability, DerivedActivity
from tests.engine_helpers import EventFactory, consult_flow, reference, t


def _p(events, at=60, pid="P1"):
    state = reconstruct_state(events, t(at), reference("P1", "P2"))
    return next(p for p in state.physicians if p.physician_id == pid), state


def _codes(p):
    return {f.code for f in p.flags}


# 7. Call and video signals override lower-priority availability signals ----------------


def test_active_call_overrides_camera_status_and_meeting():
    ev = EventFactory()
    p, _ = _p(
        [
            ev("physician_status_changed", 0, physician="P1", status="In Meeting"),
            ev("camera_active", 1, physician="P1"),
            ev("outgoing_call_started", 2, physician="P1", consult="C9", hospital="H1"),
        ]
    )

    assert p.availability is Availability.BUSY
    assert p.activity is DerivedActivity.OUTGOING_CALL
    assert p.decision_rule == "R1_SYNAPSE_CALL"
    assert any("camera" in line.lower() for line in p.explanation)


def test_active_video_is_busy_even_when_self_reported_available():
    ev = EventFactory()
    p, _ = _p(
        [
            ev("physician_status_changed", 0, physician="P1", status="Available"),
            ev("video_started", 5, physician="P1", consult="C1", hospital="H1"),
        ]
    )

    assert p.availability is Availability.BUSY
    assert p.decision_rule == "R2_SYNAPSE_VIDEO"
    assert "status_contradiction" in _codes(p)


def test_call_beats_temporarily_unavailable_status():
    ev = EventFactory()
    p, _ = _p(
        [
            ev("physician_status_changed", 0, physician="P1", status="Temporarily Unavailable"),
            ev("incoming_call_started", 2, physician="P1", consult="C1", hospital="H1"),
        ]
    )

    assert p.decision_rule == "R1_SYNAPSE_CALL"
    assert p.activity is DerivedActivity.INCOMING_CALL


def test_call_end_restores_lower_priority_signal():
    ev = EventFactory()
    p, _ = _p(
        [
            ev("physician_status_changed", 0, physician="P1", status="Temporarily Unavailable"),
            ev("incoming_call_started", 2, physician="P1", consult="C1", hospital="H1"),
            ev("incoming_call_ended", 8, physician="P1", consult="C1", hospital="H1"),
        ]
    )

    assert p.availability is Availability.UNAVAILABLE
    assert p.decision_rule == "R4_TEMPORARILY_UNAVAILABLE"
    assert p.signals.last_call_ended_at == t(8)


# 8. Meeting and camera conflict rules -------------------------------------------------


def test_camera_without_synapse_and_not_in_meeting_is_busy_and_flagged():
    ev = EventFactory()
    p, _ = _p(
        [
            ev("physician_status_changed", 0, physician="P1", status="Available"),
            ev("camera_active", 3, physician="P1"),
        ]
    )

    assert p.availability is Availability.BUSY
    assert p.activity is DerivedActivity.EXTERNAL_VIDEO_SUSPECTED
    assert p.decision_rule == "R5_CAMERA_NO_SYNAPSE"
    assert "external_video_suspected" in _codes(p)


def test_camera_while_in_meeting_is_available_and_interruptible():
    ev = EventFactory()
    p, _ = _p(
        [
            ev("physician_status_changed", 0, physician="P1", status="In Meeting"),
            ev("camera_active", 3, physician="P1"),
        ]
    )

    assert p.availability is Availability.AVAILABLE
    assert p.activity is DerivedActivity.IN_MEETING
    assert p.decision_rule == "R6_CAMERA_IN_MEETING"
    assert "external_video_suspected" not in _codes(p)


def test_in_meeting_without_camera_is_available():
    ev = EventFactory()
    p, _ = _p([ev("physician_status_changed", 0, physician="P1", status="In Meeting")])

    assert p.availability is Availability.AVAILABLE
    assert p.decision_rule == "R7_IN_MEETING"


# 9. Offline-agent routing assumption includes uncertainty ------------------------------


def test_offline_agent_is_assumed_available_with_uncertainty_flag():
    ev = EventFactory()
    p, _ = _p(
        [
            ev("physician_status_changed", 0, physician="P1", status="Available"),
            ev("camera_active", 2, physician="P1"),
            ev("agent_heartbeat_lost", 4, physician="P1"),
        ]
    )

    assert p.availability is Availability.AVAILABLE
    assert p.decision_rule == "R8_AGENT_OFFLINE"
    flag = next(f for f in p.flags if f.code == "availability_unverified")
    assert flag.severity is Severity.WARNING
    # The stale camera_active must not be trusted while the agent is offline.
    assert any("Camera: unknown" in line for line in p.explanation)


def test_later_desktop_agent_event_marks_agent_online_as_inferred():
    ev = EventFactory()
    p, _ = _p(
        [
            ev("agent_heartbeat_lost", 0, physician="P1"),
            ev("camera_inactive", 5, physician="P1"),
        ]
    )

    assert p.signals.agent_online is True
    assert p.signals.agent_online_inferred is True
    assert p.decision_rule == "R10_DEFAULT"


def test_offline_agent_does_not_hide_an_active_call():
    ev = EventFactory()
    p, _ = _p(
        [
            ev("agent_heartbeat_lost", 0, physician="P1"),
            ev("incoming_call_started", 2, physician="P1", consult="C1", hospital="H1"),
        ]
    )

    assert p.availability is Availability.BUSY
    assert "agent_offline" in _codes(p)


# 10. One physician, multiple consults in independent stages ----------------------------


def test_one_physician_owns_consults_in_independent_stages():
    ev = EventFactory()
    events = [
        # C1: phone-only consult; call ends -> provisional Note Pending.
        *consult_flow(ev, "C1", "P1", 0),
        ev("incoming_call_ended", 10, consult="C1", physician="P1", hospital="H1"),
        # C2: waiting on imaging.
        *consult_flow(ev, "C2", "P1", 12),
        ev("imaging_requested", 16, consult="C2", hospital="H1"),
        ev("incoming_call_ended", 18, consult="C2", physician="P1", hospital="H1"),
        # C3: on video now.
        *consult_flow(ev, "C3", "P1", 20),
        ev("incoming_call_ended", 24, consult="C3", physician="P1", hospital="H1"),
        ev("video_started", 30, consult="C3", physician="P1", hospital="H1"),
        # C4: documentation in progress.
        *consult_flow(ev, "C4", "P1", 32),
        ev("incoming_call_ended", 36, consult="C4", physician="P1", hospital="H1"),
        ev("note_started", 40, consult="C4", physician="P1", hospital="H1"),
    ]

    p, state = _p(events, at=45)
    stages = {c.consult_id: c.stage for c in state.consultations}

    assert stages == {
        "C1": ConsultStage.NOTE_PENDING,
        "C2": ConsultStage.IMAGING_PENDING,
        "C3": ConsultStage.VIDEO_IN_PROGRESS,
        "C4": ConsultStage.DOCUMENTATION,
    }
    assert p.open_consult_ids == ["C1", "C2", "C3", "C4"]
    assert p.availability is Availability.BUSY  # on video
    assert p.consults_this_shift == 4

    # Signing off one consult leaves the others untouched.
    events.append(ev("note_signed", 50, consult="C4", physician="P1", hospital="H1"))
    p_after, after = _p(events, at=55)
    after_stages = {c.consult_id: c.stage for c in after.consultations}
    assert after_stages["C4"] is ConsultStage.SIGNED_OFF
    assert {k: v for k, v in after_stages.items() if k != "C4"} == {
        k: v for k, v in stages.items() if k != "C4"
    }
    assert p_after.open_consult_ids == ["C1", "C2", "C3"]


def test_documentation_is_not_a_busy_signal():
    ev = EventFactory()
    events = [
        *consult_flow(ev, "C1", "P1", 0),
        ev("incoming_call_ended", 5, consult="C1", physician="P1", hospital="H1"),
        ev("note_started", 6, consult="C1", physician="P1", hospital="H1"),
    ]

    p, _ = _p(events, at=10)

    assert p.availability is Availability.AVAILABLE
    assert p.activity is DerivedActivity.DOCUMENTATION
    assert p.decision_rule == "R9_DOCUMENTATION"
